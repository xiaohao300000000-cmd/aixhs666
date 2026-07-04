from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from services.agent_runtime import rank_leads_for_workbench, run_agent_cycle, select_queries_for_agent
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


def test_run_agent_cycle_is_noop_when_no_active_queries(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="u1", display_name="已有客户")
        session.add(profile)
        session.flush()
        session.add(
            Lead(
                platform="xhs",
                public_profile_id=profile.id,
                status="qualified",
                product="PET",
                demand_type="exam_retry",
                intent_stage="decision",
                intent_score=90,
                information_completeness=90,
                known_info_json={"human_need": "需要考前冲刺"},
                missing_info_json=[],
                recommended_next_step="直接跟进试听时间",
            )
        )
        session.commit()

    class StubRunner:
        def __init__(self) -> None:
            self.called = False

        def run_cycle(self, **_: object) -> dict[str, object]:
            self.called = True
            raise AssertionError("run_cycle should not be called without active queries")

    runner = StubRunner()

    payload = run_agent_cycle(factory, runner)

    assert runner.called is False
    assert payload["pipeline"] is None
    assert len(payload["workbench_rows"]) == 1
    assert payload["workbench_rows"][0]["customer"] == "已有客户"


def test_run_agent_cycle_runs_pipeline_for_selected_queries(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(Query(query_text="PET", platform="xhs", query_type="seed", status="active", priority=10))
        session.commit()

    class StubRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run_cycle(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"status": "completed", "result_data": {"agent": {"workbench_candidates": 0}}}

    runner = StubRunner()

    payload = run_agent_cycle(factory, runner, query_limit=2, collection_limit=7)

    assert runner.calls == [{"query_ids": [1], "collection_limit": 7, "requested_by": "agent"}]
    assert payload["pipeline"]["status"] == "completed"
    assert payload["pipeline"]["result_data"]["agent"] == {"workbench_candidates": 0}
    assert payload["workbench_rows"] == []
