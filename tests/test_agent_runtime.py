from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from services.agent_runtime import rank_leads_for_workbench, select_queries_for_agent
from storage.database import Base
from storage.models import Lead, PublicProfile, Query


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_select_queries_prefers_active_high_priority_queries(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add_all(
            [
                Query(query_text="低优先", platform="xhs", query_type="seed", status="active", priority=1),
                Query(query_text="高优先", platform="xhs", query_type="seed", status="active", priority=9),
                Query(query_text="暂停", platform="xhs", query_type="seed", status="paused", priority=99),
            ]
        )
        session.commit()

    with factory() as session:
        ids = select_queries_for_agent(session, limit=1)
        query = session.get(Query, ids[0])
        assert query is not None
        assert query.query_text == "高优先"


def test_rank_leads_outputs_user_facing_rows(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="u1", display_name="福州家长")
        session.add(profile)
        session.flush()
        session.add(
            Lead(
                platform="xhs",
                public_profile_id=profile.id,
                status="needs_enrichment",
                product="PET",
                demand_type="exam_retry",
                intent_stage="exploring",
                intent_score=82,
                information_completeness=70,
                known_info_json={
                    "human_need": "孩子PET二刷需要冲刺",
                    "recommendation_reason": "明确问二刷冲刺班",
                },
                missing_info_json=["contact"],
                recommended_next_step="先确认考试时间",
            )
        )
        session.commit()

    with factory() as session:
        rows = rank_leads_for_workbench(session)

    assert len(rows) == 1
    assert rows[0].customer == "福州家长"
    assert rows[0].status_label == "待确认"
    assert rows[0].need == "孩子PET二刷需要冲刺"
    assert rows[0].next_step == "先确认考试时间"
