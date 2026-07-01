from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from scheduler import TaskStatus
from storage.models import CollectionTask


class PartialResumeError(ValueError):
    """Raised when a partial task cannot be resumed by a worker."""


def start_partial_task(
    session: Session,
    *,
    task_id: int,
    worker_id: str,
    allowed_task_types: frozenset[str],
) -> CollectionTask:
    task = session.get(CollectionTask, task_id)
    if task is None:
        raise PartialResumeError(f"collection task {task_id} was not found")
    if task.status != TaskStatus.PARTIAL.value:
        raise PartialResumeError(f"task {task.id} must be partial, got {task.status}")
    if task.task_type not in allowed_task_types:
        raise PartialResumeError(f"unsupported task type: {task.task_type}")

    cursor_json = task.cursor_json or {}
    if cursor_json.get("has_more") is not True:
        raise PartialResumeError(f"partial task {task.id} does not have more pages")
    if cursor_json.get("next_cursor") is None:
        raise PartialResumeError(f"partial task {task.id} is missing next_cursor")

    task.status = TaskStatus.RUNNING.value
    task.worker_id = worker_id
    task.started_at = datetime.now(UTC)
    task.finished_at = None
    session.flush()
    return task
