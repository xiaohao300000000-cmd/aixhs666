from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scheduler import TaskStatus, claim_next_task, create_task
from storage.database import Base


pytestmark = pytest.mark.postgres


@pytest.fixture()
def postgres_url() -> str:
    url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is required for PostgreSQL concurrency tests")
    return url


@pytest.fixture()
def postgres_session_pair(postgres_url: str):
    engine = create_engine(postgres_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    first = Session(engine)
    second = Session(engine)
    try:
        yield first, second
    finally:
        first.close()
        second.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_claim_next_task_uses_postgres_skip_locked(postgres_session_pair) -> None:
    first_session, second_session = postgres_session_pair
    now = datetime(2026, 1, 1, tzinfo=UTC)
    first_task = create_task(
        first_session,
        task_type="search",
        platform="xhs",
        priority=10,
        scheduled_at=now - timedelta(minutes=1),
        now=now,
    )
    second_task = create_task(
        first_session,
        task_type="search",
        platform="xhs",
        priority=5,
        scheduled_at=now - timedelta(minutes=1),
        now=now,
    )
    first_session.commit()

    claimed_by_first = claim_next_task(first_session, worker_id="worker-a", now=now)
    second_session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
    claimed_by_second = claim_next_task(second_session, worker_id="worker-b", now=now)

    assert claimed_by_first is not None
    assert claimed_by_second is not None
    assert claimed_by_first.id == first_task.id
    assert claimed_by_second.id == second_task.id
    assert claimed_by_first.worker_id == "worker-a"
    assert claimed_by_second.worker_id == "worker-b"

    first_session.rollback()
    second_session.rollback()

    with Session(first_session.get_bind()) as verify:
        tasks = verify.query(type(first_task)).order_by(type(first_task).id).all()
        assert [task.status for task in tasks] == [TaskStatus.PENDING.value, TaskStatus.PENDING.value]
