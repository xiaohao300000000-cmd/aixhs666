"""Core collection task state transitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from storage.models import CollectionTask


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    RETRY = "retry"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


RUNNABLE_STATUSES = (TaskStatus.PENDING.value, TaskStatus.RETRY.value)
TERMINAL_STATUSES = (
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
)


class InvalidTaskTransition(ValueError):
    """Raised when a requested task transition is not valid."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def create_task(
    session: Session,
    *,
    task_type: str,
    platform: str,
    target_id: str | None = None,
    query_id: int | None = None,
    priority: int = 0,
    scheduled_at: datetime | None = None,
    payload_json: dict[str, Any] | None = None,
    cursor_json: dict[str, Any] | None = None,
    max_attempts: int = 3,
    now: datetime | None = None,
) -> CollectionTask:
    created_at = now or utc_now()
    task = CollectionTask(
        task_type=task_type,
        platform=platform,
        target_id=target_id,
        query_id=query_id,
        priority=priority,
        status=TaskStatus.PENDING.value,
        attempt_count=0,
        max_attempts=max_attempts,
        scheduled_at=scheduled_at or created_at,
        started_at=None,
        finished_at=None,
        last_error=None,
        worker_id=None,
        cursor_json=cursor_json,
        payload_json=payload_json,
    )
    session.add(task)
    session.flush()
    return task


def claim_next_task(session: Session, *, worker_id: str, now: datetime | None = None) -> CollectionTask | None:
    claimed_at = now or utc_now()
    task = session.scalars(
        select(CollectionTask)
        .where(CollectionTask.status.in_(RUNNABLE_STATUSES))
        .where(or_(CollectionTask.scheduled_at.is_(None), CollectionTask.scheduled_at <= claimed_at))
        .order_by(CollectionTask.priority.desc(), CollectionTask.scheduled_at.asc(), CollectionTask.id.asc())
        .limit(1)
    ).first()

    if task is None:
        return None

    task.status = TaskStatus.RUNNING.value
    task.worker_id = worker_id
    task.started_at = claimed_at
    task.finished_at = None
    session.flush()
    return task


def complete_task(session: Session, task_id: int, *, now: datetime | None = None) -> CollectionTask:
    task = _get_task(session, task_id)
    _ensure_status(task, {TaskStatus.RUNNING.value}, "complete")

    task.status = TaskStatus.COMPLETED.value
    task.finished_at = now or utc_now()
    task.last_error = None
    session.flush()
    return task


def mark_partial(
    session: Session,
    task_id: int,
    *,
    error: str | None = None,
    cursor_json: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> CollectionTask:
    task = _get_task(session, task_id)
    _ensure_status(task, {TaskStatus.RUNNING.value}, "mark partial")

    task.status = TaskStatus.PARTIAL.value
    task.finished_at = now or utc_now()
    if error is not None:
        task.last_error = error
    if cursor_json is not None:
        task.cursor_json = cursor_json
    session.flush()
    return task


def cancel_task(
    session: Session,
    task_id: int,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> CollectionTask:
    task = _get_task(session, task_id)
    if task.status in TERMINAL_STATUSES:
        raise InvalidTaskTransition(f"Cannot cancel task {task.id} from status {task.status}.")

    task.status = TaskStatus.CANCELLED.value
    task.finished_at = now or utc_now()
    task.worker_id = None
    if reason is not None:
        task.last_error = reason
    session.flush()
    return task


def fail_task(
    session: Session,
    task_id: int,
    *,
    error: str,
    retry_at: datetime | None = None,
    now: datetime | None = None,
) -> CollectionTask:
    failed_at = now or utc_now()
    task = _get_task(session, task_id)
    _ensure_status(task, {TaskStatus.RUNNING.value}, "fail")

    task.attempt_count = (task.attempt_count or 0) + 1
    task.last_error = error

    if task.attempt_count < task.max_attempts:
        task.status = TaskStatus.RETRY.value
        task.scheduled_at = retry_at or failed_at
        task.started_at = None
        task.finished_at = None
        task.worker_id = None
    else:
        task.status = TaskStatus.FAILED.value
        task.finished_at = failed_at

    session.flush()
    return task


def schedule_retry(
    session: Session,
    task_id: int,
    *,
    error: str | None = None,
    retry_at: datetime | None = None,
    now: datetime | None = None,
) -> CollectionTask:
    task = _get_task(session, task_id)
    if task.status in TERMINAL_STATUSES:
        raise InvalidTaskTransition(f"Cannot retry task {task.id} from status {task.status}.")

    task.status = TaskStatus.RETRY.value
    task.scheduled_at = retry_at or now or utc_now()
    task.started_at = None
    task.finished_at = None
    task.worker_id = None
    if error is not None:
        task.last_error = error
    session.flush()
    return task


def recover_timed_out_tasks(
    session: Session,
    *,
    timeout_after: timedelta,
    now: datetime | None = None,
    recovery_status: TaskStatus | str = TaskStatus.RETRY,
    error_message: str | None = None,
) -> list[CollectionTask]:
    recovered_at = now or utc_now()
    next_status = str(recovery_status)
    if next_status not in RUNNABLE_STATUSES:
        raise InvalidTaskTransition("Timed out tasks can only be recovered to pending or retry.")

    cutoff = recovered_at - timeout_after
    tasks = list(
        session.scalars(
            select(CollectionTask)
            .where(CollectionTask.status == TaskStatus.RUNNING.value)
            .where(CollectionTask.started_at.is_not(None))
            .where(CollectionTask.started_at <= cutoff)
            .order_by(CollectionTask.started_at.asc(), CollectionTask.id.asc())
        )
    )

    message = error_message or f"Task timed out after {timeout_after}."
    for task in tasks:
        task.status = next_status
        task.last_error = message
        task.worker_id = None
        task.started_at = None
        task.finished_at = None
        task.scheduled_at = recovered_at

    session.flush()
    return tasks


def _get_task(session: Session, task_id: int) -> CollectionTask:
    task = session.get(CollectionTask, task_id)
    if task is None:
        raise LookupError(f"Collection task {task_id} was not found.")
    return task


def _ensure_status(task: CollectionTask, allowed: set[str], action: str) -> None:
    if task.status not in allowed:
        raise InvalidTaskTransition(f"Cannot {action} task {task.id} from status {task.status}.")
