from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from collectors import CollectedContent, CollectedProfile, PlatformAdapter
from scheduler import TaskStatus, claim_next_task, complete_task, fail_task
from storage import ingest_content, ingest_profile, save_json_snapshot
from storage.models import CollectionTask


DETAIL_TASK_TYPES = frozenset({"collect_content", "content_detail"})


class DetailCollectionError(ValueError):
    """Raised when a detail collection task is malformed."""


def run_next_detail_task(
    session: Session,
    *,
    adapter: PlatformAdapter,
    worker_id: str,
    snapshot_root: str | Path = "snapshots",
) -> CollectionTask | None:
    task = claim_next_task(session, worker_id=worker_id)
    if task is None:
        return None

    if task.task_type not in DETAIL_TASK_TYPES:
        fail_task(session, task.id, error=f"unsupported task type: {task.task_type}")
        raise DetailCollectionError(f"unsupported task type: {task.task_type}")

    return run_detail_task(
        session,
        task=task,
        adapter=adapter,
        snapshot_root=snapshot_root,
    )


def run_detail_task(
    session: Session,
    *,
    task: CollectionTask,
    adapter: PlatformAdapter,
    snapshot_root: str | Path = "snapshots",
) -> CollectionTask:
    try:
        _validate_task(task, adapter=adapter)
        platform_content_id = _platform_content_id(task)

        detail = adapter.get_content(platform_content_id)
        _validate_detail(detail, task=task, platform_content_id=platform_content_id)
        author_profile = _load_author_profile(adapter, detail)
        if author_profile is not None:
            ingest_profile(session, author_profile)
        content = ingest_content(session, detail)

        save_json_snapshot(
            session,
            entity_type="content",
            entity_id=content.id,
            snapshot_type="content_detail",
            payload=_snapshot_payload(task=task, detail=detail, author_profile=author_profile),
            snapshot_root=snapshot_root,
        )

        return complete_task(session, task.id)
    except Exception as exc:
        if task.status == TaskStatus.RUNNING.value:
            fail_task(session, task.id, error=str(exc))
        raise


def _validate_task(task: CollectionTask, *, adapter: PlatformAdapter) -> None:
    if task.status != TaskStatus.RUNNING.value:
        raise DetailCollectionError(f"detail task must be running, got {task.status}")
    if task.task_type not in DETAIL_TASK_TYPES:
        raise DetailCollectionError(f"unsupported task type: {task.task_type}")
    if task.platform != adapter.platform:
        raise DetailCollectionError(f"task platform {task.platform} does not match adapter platform {adapter.platform}")
    _platform_content_id(task)


def _platform_content_id(task: CollectionTask) -> str:
    if task.target_id:
        return task.target_id

    payload_json = task.payload_json or {}
    platform_content_id = payload_json.get("platform_content_id")
    if platform_content_id:
        return str(platform_content_id)

    raise DetailCollectionError("detail task requires target_id or payload_json.platform_content_id")


def _validate_detail(detail: CollectedContent, *, task: CollectionTask, platform_content_id: str) -> None:
    if detail.platform != task.platform:
        raise DetailCollectionError(f"detail platform {detail.platform} does not match task platform {task.platform}")
    if detail.platform_content_id != platform_content_id:
        raise DetailCollectionError(
            f"adapter returned content {detail.platform_content_id} for requested {platform_content_id}"
        )


def _load_author_profile(adapter: PlatformAdapter, detail: CollectedContent) -> CollectedProfile | None:
    if detail.platform_author_id is None:
        return None
    return adapter.get_profile(detail.platform_author_id)


def _snapshot_payload(
    *,
    task: CollectionTask,
    detail: CollectedContent,
    author_profile: CollectedProfile | None,
) -> dict[str, Any]:
    return {
        "task": {
            "platform": task.platform,
            "task_type": task.task_type,
            "target_id": task.target_id,
        },
        "request": {
            "platform_content_id": detail.platform_content_id,
        },
        "response": {
            "content": detail,
            "author_profile": author_profile,
        },
    }
