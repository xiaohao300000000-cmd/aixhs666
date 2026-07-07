from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scripts.backfill_location_evidence import build_backfill_location_report
from storage.database import Base
from storage.models import CollectionEvent, Comment, Content, PublicProfile


def test_backfill_location_dry_run_does_not_write_database(tmp_path: Path) -> None:
    with _session() as session:
        _seed_rows(session)
        jsonl = tmp_path / "search_comments.jsonl"
        _write_jsonl(jsonl, [{"comment_id": "comment-1", "note_id": "note-1", "creator_hash": "commenter-1", "ip_location": "福州"}])

        report = build_backfill_location_report(session, roots=[tmp_path], apply=False)

        assert report["dry_run"] is True
        assert report["scanned"] == 1
        assert report["backfilled"] == 2
        assert report["conflicts"] == 0
        assert session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-1")).region_text is None
        assert session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "commenter-1")).region_text is None


def test_backfill_location_apply_is_idempotent_and_records_conflicts(tmp_path: Path) -> None:
    with _session() as session:
        _seed_rows(session)
        jsonl = tmp_path / "search_contents.jsonl"
        _write_jsonl(
            jsonl,
            [
                {"note_id": "note-1", "creator_hash": "author-1", "ip_location": "福建"},
                {"comment_id": "comment-1", "note_id": "note-1", "creator_hash": "commenter-1", "ip_location": "福州"},
                {"note_id": "note-conflict", "creator_hash": "author-conflict", "ip_location": "上海"},
            ],
        )

        first = build_backfill_location_report(session, roots=[tmp_path], apply=True)
        second = build_backfill_location_report(session, roots=[tmp_path], apply=True)

        assert first["dry_run"] is False
        assert first["scanned"] == 3
        assert first["backfilled"] == 5
        assert first["conflicts"] == 1
        assert second["backfilled"] == 0
        assert second["conflicts"] == 1
        assert session.scalar(select(Content).where(Content.platform_content_id == "note-1")).region_text == "福建"
        assert session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-1")).region_text == "福州"
        assert session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "author-1")).region_text == "福建"
        assert session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "commenter-1")).region_text == "福州"
        assert session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "author-conflict")).region_text == "上海"
        assert session.scalar(select(Content).where(Content.platform_content_id == "note-conflict")).region_text == "福建"
        event = session.scalar(select(CollectionEvent).where(CollectionEvent.event_type == "region_text_conflict"))
        assert event is not None
        assert event.event_data["incoming_region_text"] == "上海"


def _seed_rows(session: Session) -> None:
    session.add_all(
        [
            PublicProfile(platform="xhs", platform_user_id="author-1"),
            PublicProfile(platform="xhs", platform_user_id="commenter-1"),
            PublicProfile(platform="xhs", platform_user_id="author-conflict"),
            Content(platform="xhs", platform_content_id="note-1", content_type="note"),
            Content(platform="xhs", platform_content_id="note-conflict", content_type="note", region_text="福建"),
        ]
    )
    session.flush()
    content = session.scalar(select(Content).where(Content.platform_content_id == "note-1"))
    session.add(Comment(platform="xhs", platform_comment_id="comment-1", content_id=content.id, body_text="想了解"))
    session.commit()


def _write_jsonl(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)
