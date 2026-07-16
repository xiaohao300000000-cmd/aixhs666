from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.operator_tasks import (
    cancel_operator_run,
    copy_operator_run,
    create_operator_run,
    continue_operator_review_queue,
    get_operator_review_queue,
    get_operator_run_report,
    list_operator_run_candidates,
    prepare_operator_review_queue,
    preview_operator_run,
    queue_operator_run,
    retry_operator_run,
    task_center_view,
)
from services.skill_registry import list_campaign_options
from storage.database import Base
from storage.models import Content, LeadScreeningResult, SkillRun


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_task_center_lists_registered_template_and_history() -> None:
    factory = _factory()
    with factory() as session:
        run = create_operator_run(session, requested_by="operator", idempotency_key="create-1")
        session.commit()

        payload = task_center_view(session, limit=20)

        assert payload["templates"][0]["key"] == "screen_historical_leads"
        assert payload["templates"][0]["external_write"] is False
        assert payload["runs"][0]["id"] == run["id"]
        assert payload["runs"][0]["events"][0]["type"] == "created"


def test_operator_run_preview_queue_cancel_copy_and_retry() -> None:
    factory = _factory()
    campaign_id = list_campaign_options()[0].campaign_id
    with factory() as session:
        session.add(Content(platform="xhs", platform_content_id="operator-c1", content_type="note", body_text="想报名"))
        session.flush()
        run = create_operator_run(session, requested_by="operator", idempotency_key="create-2")
        run_id = run["id"]

        previewed = preview_operator_run(
            session,
            run_id,
            parameters={"campaign_id": campaign_id, "limit": 10, "data_range": "all", "source_types": "content_only"},
            event_key="preview-2",
        )
        queued = queue_operator_run(session, run_id, event_key="queue-2")
        cancelled = cancel_operator_run(session, run_id, event_key="cancel-2")
        copied = copy_operator_run(session, run_id, requested_by="operator", event_key="copy-2")

        failed = session.get(SkillRun, copied["id"])
        assert failed is not None
        failed.status = "failed"
        failed.error_message = "forced"
        retried = retry_operator_run(session, failed.id, event_key="retry-2")
        session.commit()

        assert previewed["status"] == "previewed"
        assert previewed["preview"]["candidate_count"] == 1
        assert queued["status"] == "queued"
        assert cancelled["status"] == "cancelled"
        assert copied["copied_from_run_id"] == run_id
        assert retried["status"] == "queued"


def test_operator_report_drilldown_and_queue_preparation_are_idempotent() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        screenings = [
            _screening(1, "priority"),
            _screening(2, "uncertain"),
            _screening(3, "excluded"),
        ]
        session.add_all(screenings)
        session.flush()
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json={"screening_ids": [item.id for item in screenings]},
            result_summary_json={"processed_count": 3, "api_key": "must-not-leak"},
        )
        session.add(run)
        session.flush()

        rebuilt = get_operator_run_report(
            session,
            run.id,
            rebuild=True,
            idempotency_key="report-rebuild-1",
        )
        exclusions = list_operator_run_candidates(
            session,
            run.id,
            layer="automatic_exclusion",
        )
        first = prepare_operator_review_queue(
            session,
            run.id,
            queue_date=business_day,
            idempotency_key="prepare-queue-1",
        )
        session.commit()
        second = prepare_operator_review_queue(
            session,
            run.id,
            queue_date=business_day,
            idempotency_key="prepare-queue-1",
        )
        queue = get_operator_review_queue(session, queue_date=business_day)

        assert rebuilt["run_id"] == run.id
        assert rebuilt["next_action"]["label"] == "审核本次候选"
        assert "must-not-leak" not in str(rebuilt)
        assert exclusions["count"] == 1
        assert exclusions["items"][0]["layer"] == "automatic_exclusion"
        assert first["item_ids"] == second["item_ids"]
        assert first["candidate_keys"] == second["candidate_keys"]
        assert queue["progress"] == {
            "completed": 0,
            "target": 3,
            "pending": 3,
            "quality_control": 2,
        }


def test_operator_queue_writes_require_idempotency_key_and_support_priority_only() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        screenings = [_screening(index, "priority") for index in range(1, 4)]
        session.add_all(screenings)
        session.flush()
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json={"screening_ids": [item.id for item in screenings]},
            result_summary_json={"processed_count": 3},
        )
        session.add(run)
        session.flush()

        with pytest.raises(ValueError, match="idempotency_key is required"):
            prepare_operator_review_queue(
                session,
                run.id,
                queue_date=business_day,
                idempotency_key=" ",
            )
        with pytest.raises(ValueError, match="idempotency_key is required"):
            continue_operator_review_queue(
                session,
                queue_date=business_day,
                additional=20,
                priority_only=True,
                idempotency_key="",
            )

        result = continue_operator_review_queue(
            session,
            queue_date=business_day,
            additional=20,
            priority_only=True,
            idempotency_key="continue-priority-1",
        )

        assert result["created"] == 3
        assert result["priority_only"] is True


def _screening(source_id: int, kind: str) -> LeadScreeningResult:
    values = {
        "priority": {
            "valuable": True,
            "review_status": "accepted",
            "intent_strength": "high",
            "confidence": 92,
            "qualification_reason_codes_json": [],
        },
        "uncertain": {
            "valuable": False,
            "review_status": "rejected",
            "intent_strength": "low",
            "confidence": 40,
            "qualification_reason_codes_json": ["location_unknown"],
        },
        "excluded": {
            "valuable": False,
            "review_status": "rejected",
            "intent_strength": "medium",
            "confidence": 90,
            "qualification_reason_codes_json": ["institution_account"],
        },
    }[kind]
    return LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=source_id,
        judgment_evidence_json=[f"evidence-{source_id}"],
        qualification_decision="needs_review",
        **values,
    )
