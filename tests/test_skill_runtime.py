from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from services.skill_runtime import (
    copy_skill_run,
    create_skill_run,
    execute_skill_run,
    finalize_skill_run,
    preview_skill_run,
    queue_skill_run,
    request_skill_run_cancel,
    retry_skill_run,
    update_skill_run_parameters,
)
from storage.database import Base
from storage.models import (
    CollectionTask,
    Comment,
    Content,
    LeadScreeningResult,
    ReviewQueueItem,
    SkillRun,
    SkillRunEvent,
)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _campaign_id() -> str:
    from services.skill_registry import list_campaign_options
    return list_campaign_options()[0].campaign_id


def test_preview_queue_duplicate_and_cancel() -> None:
    factory = _factory()
    with factory() as session:
        content = Content(platform="xhs", platform_content_id="c1", content_type="note", body_text="需要课程")
        session.add(content)
        session.flush()
        session.add(Comment(platform="xhs", platform_comment_id="m1", content_id=content.id, body_text="想报名"))
        run = create_skill_run(session, requested_by="ou_1", idempotency_key="create:e1")
        update_skill_run_parameters(session, run.id, {"campaign_id": _campaign_id(), "limit": 10})
        preview = preview_skill_run(session, run.id, event_key="preview:e2")
        first = queue_skill_run(session, run.id, event_key="confirm:e3")
        second = queue_skill_run(session, run.id, event_key="confirm:e4")
        cancelled = request_skill_run_cancel(session, run.id, event_key="cancel:e5")
        session.commit()

        assert preview["candidate_count"] == 2
        assert first.id == second.id
        assert cancelled.status == "cancelled"
        assert session.scalar(select(CollectionTask).where(CollectionTask.target_id == str(run.id))) is not None


def test_failed_retry_and_copy_preserve_parameters() -> None:
    factory = _factory()
    with factory() as session:
        run = create_skill_run(session, requested_by="ou_1")
        update_skill_run_parameters(session, run.id, {"campaign_id": _campaign_id(), "limit": 5})
        run.status = "failed"
        run.error_message = "forced"
        retry_task = retry_skill_run(session, run.id, event_key="retry:e1")
        copied = copy_skill_run(session, run.id, requested_by="ou_2", event_key="copy:e2")
        duplicate_copy = copy_skill_run(session, run.id, requested_by="ou_2", event_key="copy:e2")
        session.commit()

        assert retry_task.task_type == "skill_run_execute"
        assert run.status == "queued"
        assert run.retry_count == 1
        assert copied.status == "draft"
        assert copied.parameters_json == run.parameters_json
        assert copied.copied_from_run_id == run.id
        assert duplicate_copy.id == copied.id


def test_finalize_skill_run_builds_global_report_queue_without_losing_raw_audit_facts() -> None:
    factory = _factory()
    business_day = date(2026, 7, 16)
    with factory() as session:
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=901,
            valuable=True,
            review_status="accepted",
            intent_strength="high",
            confidence=93,
            judgment_evidence_json=["明确询问今天试听"],
        )
        session.add(screening)
        session.flush()
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="running",
            current_stage="summarize",
            checkpoint_json={"screening_ids": [screening.id], "next_index": 1},
        )
        session.add(run)
        session.flush()
        session.add(
            SkillRunEvent(
                skill_run_id=run.id,
                sequence=1,
                event_type="candidate_screened",
                data_json={"raw": "preserved"},
            )
        )
        raw_summary = {"processed_count": 1, "legacy_key": "preserved"}

        first = finalize_skill_run(
            session,
            run,
            raw_summary=raw_summary,
            queue_date=business_day,
        )
        session.commit()
        first_item_ids = session.scalars(select(ReviewQueueItem.id)).all()
        second = finalize_skill_run(
            session,
            run,
            raw_summary=raw_summary,
            queue_date=business_day,
        )
        session.commit()

        assert first == second
        assert run.status == "succeeded"
        assert run.result_summary_json == raw_summary
        assert run.checkpoint_json == {"screening_ids": [screening.id], "next_index": 1}
        assert run.business_report_json["queue"]["prepared"] == 1
        assert run.business_report_json["queue"]["scope"] == "global_unreviewed_backlog"
        assert session.scalars(select(ReviewQueueItem.id)).all() == first_item_ids
        events = session.scalars(
            select(SkillRunEvent).where(SkillRunEvent.skill_run_id == run.id)
        ).all()
        assert [event.event_type for event in events].count("succeeded") == 1
        assert events[0].data_json == {"raw": "preserved"}


def test_execute_skill_run_summarize_uses_human_report_and_global_queue_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    with factory() as session:
        content = Content(
            platform="xhs",
            platform_content_id="summarize-content",
            content_type="note",
            body_text="想了解 PET 二刷课程",
        )
        session.add(content)
        session.flush()
        run = create_skill_run(session, requested_by="operator")
        update_skill_run_parameters(
            session,
            run.id,
            {
                "campaign_id": _campaign_id(),
                "limit": 1,
                "data_range": "all",
                "source_types": "content_only",
            },
        )
        preview_skill_run(session, run.id)
        run.status = "queued"
        run_id = run.id
        session.commit()

    def fake_screen(session: Session, **kwargs) -> None:
        source_id = next(iter(kwargs["source_entity_ids"]))
        session.add(
            LeadScreeningResult(
                platform="xhs",
                source_entity_type="content",
                source_entity_id=source_id,
                valuable=True,
                review_status="accepted",
                intent_strength="high",
                confidence=91,
                judgment_evidence_json=["明确询问课程"],
            )
        )
        session.flush()

    class SyncResult:
        def to_dict(self) -> dict[str, int]:
            return {
                "customers_created": 0,
                "evidence_created": 0,
                "customers_updated": 0,
                "evidence_updated": 0,
                "failed": 0,
                "dry_run": 0,
            }

    monkeypatch.setattr("services.skill_runtime.run_llm_lead_screening", fake_screen)
    monkeypatch.setattr(
        "services.skill_runtime.sync_feishu_ai_review_rows",
        lambda *_args, **_kwargs: SyncResult(),
    )
    monkeypatch.setattr("services.skill_runtime._project_history", lambda *_args: None)

    execute_skill_run(factory, run_id)

    with factory() as session:
        stored = session.get(SkillRun, run_id)
        assert stored is not None
        assert stored.status == "succeeded"
        assert stored.business_report_json is not None
        assert stored.business_report_json["queue"]["scope"] == "global_unreviewed_backlog"
        assert session.scalar(select(ReviewQueueItem)) is not None
