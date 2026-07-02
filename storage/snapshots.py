from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from storage.models import CollectionEvent, Snapshot


DEFAULT_SNAPSHOT_ROOT = Path("snapshots")


def save_json_snapshot(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    snapshot_type: str,
    payload: Any,
    snapshot_root: str | Path = DEFAULT_SNAPSHOT_ROOT,
) -> Snapshot:
    """Persist a deterministic JSON snapshot file and record its metadata."""

    serialized = stable_json_dumps(payload)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    snapshot_path = _snapshot_path(
        Path(snapshot_root),
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot_type=snapshot_type,
        content_hash=content_hash,
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(serialized + "\n", encoding="utf-8")

    snapshot = Snapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        snapshot_type=snapshot_type,
        object_storage_path=str(snapshot_path),
        content_hash=content_hash,
    )
    session.add(snapshot)
    session.flush()
    session.add(
        CollectionEvent(
            event_type="snapshot_saved",
            entity_type=entity_type,
            entity_id=entity_id,
            event_data={
                "snapshot_id": snapshot.id,
                "snapshot_type": snapshot_type,
                "object_storage_path": str(snapshot_path),
            },
        )
    )
    session.flush()
    return snapshot


def stable_json_dumps(payload: Any) -> str:
    return json.dumps(
        _to_jsonable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _snapshot_path(
    snapshot_root: Path,
    *,
    entity_type: str,
    entity_id: int,
    snapshot_type: str,
    content_hash: str,
) -> Path:
    return snapshot_root / entity_type / str(entity_id) / snapshot_type / f"{content_hash}.json"
