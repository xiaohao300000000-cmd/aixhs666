from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from collectors import CollectedProfile, PlatformAdapter
from scheduler import TaskStatus, complete_task, fail_task
from storage import ingest_profile, save_json_snapshot
from storage.models import CollectionTask


PROFILE_TASK_TYPES = frozenset({"profile", "collect_profile", "profile_collection"})


class ProfileCollectionError(ValueError):
    """Raised when a profile collection task is malformed."""


def run_profile_task(
    session: Session,
    *,
    task: CollectionTask,
    adapter: PlatformAdapter,
    snapshot_root: str | Path = "snapshots",
) -> CollectionTask:
    try:
        _validate_task(task, adapter=adapter)
        platform_user_id = _platform_user_id(task)

        profile = adapter.get_profile(platform_user_id)
        _validate_profile(profile, task=task, platform_user_id=platform_user_id)
        stored = ingest_profile(session, profile)

        save_json_snapshot(
            session,
            entity_type="profile",
            entity_id=stored.id,
            snapshot_type="profile",
            payload=_snapshot_payload(task=task, profile=profile),
            snapshot_root=snapshot_root,
        )

        return complete_task(session, task.id)
    except Exception as exc:
        if task.status == TaskStatus.RUNNING.value:
            fail_task(session, task.id, error=str(exc))
        raise


def _validate_task(task: CollectionTask, *, adapter: PlatformAdapter) -> None:
    if task.status != TaskStatus.RUNNING.value:
        raise ProfileCollectionError(f"profile task must be running, got {task.status}")
    if task.task_type not in PROFILE_TASK_TYPES:
        raise ProfileCollectionError(f"unsupported task type: {task.task_type}")
    if task.platform != adapter.platform:
        raise ProfileCollectionError(f"task platform {task.platform} does not match adapter platform {adapter.platform}")
    _platform_user_id(task)


def _platform_user_id(task: CollectionTask) -> str:
    if task.target_id:
        return task.target_id

    payload_json = task.payload_json or {}
    platform_user_id = payload_json.get("platform_user_id")
    if platform_user_id:
        return str(platform_user_id)

    raise ProfileCollectionError("profile task requires target_id or payload_json.platform_user_id")


def _validate_profile(profile: CollectedProfile, *, task: CollectionTask, platform_user_id: str) -> None:
    if profile.platform != task.platform:
        raise ProfileCollectionError(f"profile platform {profile.platform} does not match task platform {task.platform}")
    if profile.platform_user_id != platform_user_id:
        raise ProfileCollectionError(
            f"adapter returned profile {profile.platform_user_id} for requested {platform_user_id}"
        )


def _snapshot_payload(*, task: CollectionTask, profile: CollectedProfile) -> dict[str, Any]:
    return {
        "task": {
            "platform": task.platform,
            "task_type": task.task_type,
            "target_id": task.target_id,
        },
        "request": {
            "platform_user_id": profile.platform_user_id,
        },
        "response": {
            "profile": profile,
        },
    }
