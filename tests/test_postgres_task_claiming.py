from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from scheduler import TaskStatus, claim_next_task, create_task
from integrations.feishu.llm_review import claim_pending_llm_review_cards
from services.lead_screening_flow import claim_pending_llm_screenings
from storage.database import Base
from storage.models import LeadScreeningResult, PublicProfile


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


def test_claim_pending_llm_screenings_uses_postgres_skip_locked(postgres_session_pair) -> None:
    first_session, second_session = postgres_session_pair
    profile = PublicProfile(platform="xhs", platform_user_id="pg-user", display_name="PG 家长")
    first_session.add(profile)
    first_session.flush()
    first_screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=1,
        public_profile_id=profile.id,
        workflow_status="pending_llm",
    )
    second_screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=2,
        public_profile_id=profile.id,
        workflow_status="pending_llm",
    )
    first_session.add_all([first_screening, second_screening])
    first_session.commit()

    claimed_by_first = claim_pending_llm_screenings(first_session, limit=1)
    second_session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
    claimed_by_second = claim_pending_llm_screenings(second_session, limit=1)

    assert [row.id for row in claimed_by_first] == [first_screening.id]
    assert [row.id for row in claimed_by_second] == [second_screening.id]
    assert claimed_by_first[0].workflow_status == "screening"
    assert claimed_by_second[0].workflow_status == "screening"

    first_session.rollback()
    second_session.rollback()

    with Session(first_session.get_bind()) as verify:
        statuses = verify.scalars(select(LeadScreeningResult.workflow_status).order_by(LeadScreeningResult.id)).all()
        assert statuses == ["pending_llm", "pending_llm"]


def test_claim_pending_feishu_reviews_uses_postgres_skip_locked(postgres_session_pair) -> None:
    first_session, second_session = postgres_session_pair
    profile = PublicProfile(platform="xhs", platform_user_id="pg-feishu-user", display_name="PG 飞书家长")
    first_session.add(profile)
    first_session.flush()
    first_screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=11,
        public_profile_id=profile.id,
        review_status="needs_review",
        workflow_status="pending_feishu",
    )
    second_screening = LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=12,
        public_profile_id=profile.id,
        review_status="needs_review",
        workflow_status="pending_feishu",
    )
    first_session.add_all([first_screening, second_screening])
    first_session.commit()

    claimed_by_first = claim_pending_llm_review_cards(first_session, limit=1)
    second_session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
    claimed_by_second = claim_pending_llm_review_cards(second_session, limit=1)

    assert [row.id for row in claimed_by_first] == [first_screening.id]
    assert [row.id for row in claimed_by_second] == [second_screening.id]
    assert claimed_by_first[0].workflow_status == "sending"
    assert claimed_by_second[0].workflow_status == "sending"
    assert claimed_by_first[0].attempt_count == 1
    assert claimed_by_second[0].attempt_count == 1

    first_session.rollback()
    second_session.rollback()

    with Session(first_session.get_bind()) as verify:
        statuses = verify.scalars(select(LeadScreeningResult.workflow_status).order_by(LeadScreeningResult.id)).all()
        assert statuses == ["pending_feishu", "pending_feishu"]
