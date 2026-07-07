from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.database import SessionLocal
from storage.models import CollectionEvent, Comment, Content, PublicProfile


REGION_KEYS = ("ip_location", "ipLocation", "location", "region", "ip_location_text", "ip_location_name")


def build_backfill_location_report(session: Session, *, roots: Iterable[str | Path], apply: bool = False) -> dict[str, int | bool]:
    counts: dict[str, int | bool] = {
        "dry_run": not apply,
        "scanned": 0,
        "backfilled": 0,
        "conflicts": 0,
        "failures": 0,
        "contents_backfilled": 0,
        "comments_backfilled": 0,
        "profiles_backfilled": 0,
    }
    for record in _iter_records(roots):
        region_text = _public_region_text(record)
        if region_text is None:
            continue
        counts["scanned"] += 1
        try:
            _backfill_record(session, record=record, region_text=region_text, apply=apply, counts=counts)
        except Exception:  # noqa: BLE001 - report bad local records without aborting the whole backfill.
            counts["failures"] += 1
    if apply:
        session.flush()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill public XHS location fields from local JSONL and snapshots.")
    parser.add_argument("--root", action="append", dest="roots", help="Directory or file to scan. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Scan and report without modifying the database.")
    parser.add_argument("--apply", action="store_true", help="Apply idempotent empty-field backfills.")
    args = parser.parse_args(argv)
    roots = [Path(item) for item in (args.roots or _default_roots())]
    with SessionLocal() as session:
        report = build_backfill_location_report(session, roots=roots, apply=bool(args.apply))
        if args.apply:
            session.commit()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _default_roots() -> list[str]:
    return [
        os.getenv("MEDIACRAWLER_OUTPUT_ROOT", ".runtime/mediacrawler-runs"),
        os.getenv("WORKER_SNAPSHOT_ROOT", ".runtime/storage-snapshots"),
        os.getenv("XHS_SNAPSHOT_DIR", ".runtime/snapshots"),
    ]


def _backfill_record(
    session: Session,
    *,
    record: dict[str, Any],
    region_text: str,
    apply: bool,
    counts: dict[str, int | bool],
) -> None:
    comment_id = _clean(record.get("comment_id"))
    note_id = _clean(record.get("note_id"))
    creator_hash = _clean(record.get("creator_hash"))
    if comment_id is not None:
        _backfill_entity(
            session,
            model=Comment,
            platform_id_field="platform_comment_id",
            platform_id=comment_id,
            entity_type="comment",
            region_text=region_text,
            apply=apply,
            counts=counts,
            counter_key="comments_backfilled",
        )
    elif note_id is not None:
        _backfill_entity(
            session,
            model=Content,
            platform_id_field="platform_content_id",
            platform_id=note_id,
            entity_type="content",
            region_text=region_text,
            apply=apply,
            counts=counts,
            counter_key="contents_backfilled",
        )
    if creator_hash is not None:
        _backfill_entity(
            session,
            model=PublicProfile,
            platform_id_field="platform_user_id",
            platform_id=creator_hash,
            entity_type="public_profile",
            region_text=region_text,
            apply=apply,
            counts=counts,
            counter_key="profiles_backfilled",
        )


def _backfill_entity(
    session: Session,
    *,
    model: type[Comment] | type[Content] | type[PublicProfile],
    platform_id_field: str,
    platform_id: str,
    entity_type: str,
    region_text: str,
    apply: bool,
    counts: dict[str, int | bool],
    counter_key: str,
) -> None:
    field = getattr(model, platform_id_field)
    row = session.scalar(select(model).where(model.platform == "xhs").where(field == platform_id))
    if row is None:
        return
    existing = _clean(row.region_text)
    if existing is None:
        counts["backfilled"] += 1
        counts[counter_key] += 1
        if apply:
            row.region_text = region_text
        return
    if existing == region_text:
        return
    counts["conflicts"] += 1
    if apply:
        _record_conflict_once(session, entity_type=entity_type, entity_id=row.id, existing=existing, incoming=region_text)


def _record_conflict_once(session: Session, *, entity_type: str, entity_id: int, existing: str, incoming: str) -> None:
    existing_event = session.scalar(
        select(CollectionEvent)
        .where(CollectionEvent.event_type == "region_text_conflict")
        .where(CollectionEvent.entity_type == entity_type)
        .where(CollectionEvent.entity_id == entity_id)
        .where(CollectionEvent.event_data["incoming_region_text"].as_string() == incoming)
    )
    if existing_event is not None:
        return
    session.add(
        CollectionEvent(
            event_type="region_text_conflict",
            entity_type=entity_type,
            entity_id=entity_id,
            event_data={
                "field": "region_text",
                "existing_region_text": existing,
                "incoming_region_text": incoming,
                "source": "backfill_location_evidence",
            },
        )
    )


def _iter_records(roots: Iterable[str | Path]) -> Iterable[dict[str, Any]]:
    for root in roots:
        path = Path(root)
        if not path.exists():
            continue
        files = [path] if path.is_file() else sorted([*path.glob("**/*.jsonl"), *path.glob("**/*.json")])
        for file_path in files:
            yield from _records_from_file(file_path)


def _records_from_file(path: Path) -> Iterable[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if isinstance(payload, dict):
                    yield payload
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    yield from _walk_dicts(payload)


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _public_region_text(item: dict[str, Any]) -> str | None:
    for key in REGION_KEYS:
        value = _clean(item.get(key))
        if value is not None:
            return value
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


if __name__ == "__main__":
    raise SystemExit(main())
