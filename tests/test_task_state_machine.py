from datetime import UTC, datetime, timedelta

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scheduler import (
    InvalidTaskTransition,
    TaskStatus,
    cancel_task,
    claim_next_task,
    complete_task,
    create_task,
    fail_task,
    mark_partial,
    recover_timed_out_tasks,
    schedule_retry,
)
from storage.database import Base


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_claim_next_task_only_claims_runnable_tasks(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    runnable = create_task(
        session,
        task_type="collect_content",
        platform="xhs",
        priority=10,
        scheduled_at=now - timedelta(minutes=1),
        now=now,
    )
    retry = create_task(
        session,
        task_type="collect_comments",
        platform="xhs",
        priority=5,
        scheduled_at=now - timedelta(minutes=2),
        now=now,
    )
    retry.status = TaskStatus.RETRY.value

    future = create_task(
        session,
        task_type="future",
        platform="xhs",
        scheduled_at=now + timedelta(hours=1),
        now=now,
    )
    blocked = create_task(session, task_type="blocked", platform="xhs", now=now)
    blocked.status = TaskStatus.BLOCKED.value
    cancelled = create_task(session, task_type="cancelled", platform="xhs", now=now)
    cancelled.status = TaskStatus.CANCELLED.value
    partial = create_task(session, task_type="partial", platform="xhs", now=now)
    partial.status = TaskStatus.PARTIAL.value
    session.flush()

    claimed = claim_next_task(session, worker_id="worker-a", now=now)

    assert claimed is runnable
    assert claimed.status == TaskStatus.RUNNING.value
    assert claimed.worker_id == "worker-a"
    assert claimed.started_at == now

    next_claimed = claim_next_task(session, worker_id="worker-b", now=now)

    assert next_claimed is retry
    assert claim_next_task(session, worker_id="worker-c", now=now) is None
    assert future.status == TaskStatus.PENDING.value
    assert blocked.status == TaskStatus.BLOCKED.value
    assert cancelled.status == TaskStatus.CANCELLED.value
    assert partial.status == TaskStatus.PARTIAL.value


def test_complete_task_marks_running_task_completed(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    task = create_task(session, task_type="collect_content", platform="xhs", now=now)
    claim_next_task(session, worker_id="worker-a", now=now)

    completed = complete_task(session, task.id, now=now + timedelta(minutes=5))

    assert completed.status == TaskStatus.COMPLETED.value
    assert completed.finished_at == now + timedelta(minutes=5)
    assert completed.last_error is None


def test_fail_task_retries_until_max_attempts_without_affecting_other_tasks(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    failing = create_task(
        session,
        task_type="collect_content",
        platform="xhs",
        priority=10,
        max_attempts=2,
        now=now,
    )
    other = create_task(session, task_type="collect_profile", platform="xhs", priority=1, now=now)

    claimed = claim_next_task(session, worker_id="worker-a", now=now)
    assert claimed is failing

    retried = fail_task(session, failing.id, error="temporary throttle", now=now + timedelta(minutes=1))

    assert retried.status == TaskStatus.RETRY.value
    assert retried.attempt_count == 1
    assert retried.worker_id is None
    assert retried.last_error == "temporary throttle"
    assert other.status == TaskStatus.PENDING.value

    claimed_again = claim_next_task(session, worker_id="worker-b", now=now + timedelta(minutes=2))
    assert claimed_again is failing

    failed = fail_task(session, failing.id, error="still throttled", now=now + timedelta(minutes=3))

    assert failed.status == TaskStatus.FAILED.value
    assert failed.attempt_count == 2
    assert failed.finished_at == now + timedelta(minutes=3)
    assert failed.last_error == "still throttled"
    assert other.status == TaskStatus.PENDING.value


def test_recover_timed_out_tasks_restores_only_stale_running_tasks(session: Session) -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    stale = create_task(
        session,
        task_type="stale",
        platform="xhs",
        priority=5,
        scheduled_at=now - timedelta(hours=3),
        now=now,
    )
    fresh = create_task(
        session,
        task_type="fresh",
        platform="xhs",
        priority=4,
        scheduled_at=now - timedelta(hours=3),
        now=now,
    )
    untouched = create_task(session, task_type="untouched", platform="xhs", priority=3, now=now)

    claim_next_task(session, worker_id="worker-a", now=now - timedelta(hours=2))
    claim_next_task(session, worker_id="worker-b", now=now - timedelta(minutes=5))
    session.flush()

    recovered = recover_timed_out_tasks(
        session,
        timeout_after=timedelta(minutes=30),
        now=now,
        recovery_status=TaskStatus.RETRY,
        error_message="worker heartbeat expired",
    )

    assert recovered == [stale]
    assert stale.status == TaskStatus.RETRY.value
    assert stale.worker_id is None
    assert stale.started_at is None
    assert stale.scheduled_at == now
    assert stale.last_error == "worker heartbeat expired"
    assert fresh.status == TaskStatus.RUNNING.value
    assert fresh.worker_id == "worker-b"
    assert untouched.status == TaskStatus.PENDING.value


def test_recover_timed_out_tasks_can_restore_to_pending(session: Session) -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    task = create_task(
        session,
        task_type="stale",
        platform="xhs",
        scheduled_at=now - timedelta(hours=2),
        now=now,
    )
    claim_next_task(session, worker_id="worker-a", now=now - timedelta(hours=1))

    recovered = recover_timed_out_tasks(
        session,
        timeout_after=timedelta(minutes=30),
        now=now,
        recovery_status=TaskStatus.PENDING,
    )

    assert recovered == [task]
    assert task.status == TaskStatus.PENDING.value
    assert task.last_error is not None


def test_schedule_retry_resets_non_terminal_task_for_future_claim(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    retry_at = now + timedelta(minutes=15)
    task = create_task(session, task_type="collect_comments", platform="xhs", now=now)
    claim_next_task(session, worker_id="worker-a", now=now)
    mark_partial(
        session,
        task.id,
        error="cursor saved",
        now=now + timedelta(minutes=2),
    )

    retried = schedule_retry(
        session,
        task.id,
        error="resume from cursor",
        retry_at=retry_at,
    )

    assert retried.status == TaskStatus.RETRY.value
    assert retried.worker_id is None
    assert retried.started_at is None
    assert retried.finished_at is None
    assert retried.scheduled_at == retry_at
    assert retried.last_error == "resume from cursor"


@pytest.mark.parametrize("terminal_status", [TaskStatus.COMPLETED, TaskStatus.CANCELLED])
def test_schedule_retry_rejects_terminal_tasks(session: Session, terminal_status: TaskStatus) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    task = create_task(session, task_type="collect_content", platform="xhs", now=now)
    claim_next_task(session, worker_id="worker-a", now=now)
    if terminal_status == TaskStatus.COMPLETED:
        complete_task(session, task.id, now=now + timedelta(minutes=1))
    else:
        cancel_task(session, task.id, reason="stopped", now=now + timedelta(minutes=1))

    with pytest.raises(InvalidTaskTransition):
        schedule_retry(session, task.id, error="try again", retry_at=now + timedelta(minutes=5))

    assert task.status == terminal_status.value


def test_cancel_task_rejects_completed_task(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    task = create_task(session, task_type="collect_content", platform="xhs", now=now)
    claim_next_task(session, worker_id="worker-a", now=now)
    complete_task(session, task.id, now=now + timedelta(minutes=1))

    with pytest.raises(InvalidTaskTransition):
        cancel_task(session, task.id, reason="too late", now=now + timedelta(minutes=2))

    assert task.status == TaskStatus.COMPLETED.value


def test_mark_partial_and_cancel_set_explicit_statuses(session: Session) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    partial_task = create_task(session, task_type="collect_comments", platform="xhs", priority=5, now=now)
    cancel_candidate = create_task(session, task_type="collect_profile", platform="xhs", priority=1, now=now)

    claim_next_task(session, worker_id="worker-a", now=now)
    marked = mark_partial(
        session,
        partial_task.id,
        error="page limit reached",
        cursor_json={"cursor": "next-page"},
        now=now + timedelta(minutes=4),
    )
    cancelled = cancel_task(session, cancel_candidate.id, reason="user cancelled", now=now + timedelta(minutes=5))

    assert marked.status == TaskStatus.PARTIAL.value
    assert marked.finished_at == now + timedelta(minutes=4)
    assert marked.last_error == "page limit reached"
    assert marked.cursor_json == {"cursor": "next-page"}
    assert cancelled.status == TaskStatus.CANCELLED.value
    assert cancelled.finished_at == now + timedelta(minutes=5)
    assert cancelled.last_error == "user cancelled"
