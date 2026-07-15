from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.operator_workbench import build_operator_workbench
from storage.database import Base
from storage.models import CollectionTask, Lead, LeadEvidence, PublicProfile, SkillRun, WorkerHeartbeat


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_build_operator_workbench_counts_review_queue_and_runs() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="u-1", display_name="林女士")
        session.add(profile)
        session.flush()
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="new",
            region_text="福州",
            demand_type="少儿英语",
            intent_stage="比较机构",
            intent_score=88,
            recommended_next_step="核对孩子年级和目标考试",
        )
        session.add(lead)
        session.flush()
        session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_entity_type="comment",
                source_entity_id=101,
                evidence_text="孩子准备 KET，正在比较机构。",
                score_contribution=20,
            )
        )
        session.add(
            SkillRun(
                skill_key="screen_historical_leads",
                skill_version=1,
                status="running",
                current_stage="screening",
                progress_current=20,
                progress_total=50,
                progress_percent=40,
            )
        )
        session.commit()

        payload = build_operator_workbench(session)

    assert payload["attention"] == {
        "review_queue": 1,
        "running_skills": 1,
        "failed_tasks": 0,
        "stale_workers": 0,
    }
    assert payload["lead_queue"][0]["display_name"] == "林女士"
    assert payload["lead_queue"][0]["evidence_text"] == "孩子准备 KET，正在比较机构。"
    assert payload["skill_runs"][0]["progress_percent"] == 40
    assert payload["next_action"]["kind"] == "review_leads"


def test_build_operator_workbench_reports_stale_worker_and_failed_tasks() -> None:
    factory = _factory()
    now = datetime.now(UTC)
    with factory() as session:
        session.add(
            CollectionTask(
                task_type="search",
                platform="xhs",
                target_id="福州少儿英语",
                status="failed",
                last_error="browser disconnected",
            )
        )
        session.add(
            WorkerHeartbeat(
                worker_id="worker-stale",
                status="running",
                started_at=now - timedelta(hours=1),
                last_heartbeat_at=now - timedelta(minutes=8),
            )
        )
        session.add(
            WorkerHeartbeat(
                worker_id="worker-live",
                status="idle",
                started_at=now - timedelta(hours=1),
                last_heartbeat_at=now - timedelta(seconds=20),
            )
        )
        session.commit()

        payload = build_operator_workbench(session, now=now)

    assert payload["attention"]["failed_tasks"] == 1
    assert payload["attention"]["stale_workers"] == 1
    assert payload["task_failures"][0]["last_error"] == "browser disconnected"
    assert payload["workers"][0]["health"] == "stale"
    assert payload["workers"][1]["health"] == "healthy"
    assert payload["next_action"]["kind"] == "inspect_failure"


def test_build_operator_workbench_returns_empty_sections_for_empty_database() -> None:
    factory = _factory()
    with factory() as session:
        payload = build_operator_workbench(session)

    assert payload["attention"] == {
        "review_queue": 0,
        "running_skills": 0,
        "failed_tasks": 0,
        "stale_workers": 0,
    }
    assert payload["lead_queue"] == []
    assert payload["skill_runs"] == []
    assert payload["task_failures"] == []
    assert payload["workers"] == []
    assert payload["next_action"]["kind"] == "none"
