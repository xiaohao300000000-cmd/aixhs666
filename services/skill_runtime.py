from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from scheduler import create_task
from services.daily_review_queue import prepare_daily_review_queue
from services.feishu_ai_review_sync import sync_feishu_ai_review_rows
from services.llm_lead_screening import run_llm_lead_screening
from services.skill_registry import ScreenHistoricalLeadsParameters, get_skill_definition, load_registered_campaign
from services.skill_run_report import rebuild_skill_run_report
from storage.models import CollectionTask, Comment, Content, LeadScreeningResult, SkillRun, SkillRunEvent

SKILL_TASK_TYPE = "skill_run_execute"
TERMINAL_STATUSES = {"cancelled", "failed", "succeeded"}
NON_INTERRUPTIBLE_STAGES = {"sync_feishu", "summarize"}


def _now() -> datetime:
    return datetime.now(UTC)


def _event(session: Session, run: SkillRun, event_type: str, *, event_key: str | None = None, message: str | None = None, data: dict[str, Any] | None = None) -> SkillRunEvent:
    if event_key:
        existing = session.scalar(select(SkillRunEvent).where(SkillRunEvent.event_key == event_key))
        if existing is not None:
            return existing
    sequence = int(session.scalar(select(func.max(SkillRunEvent.sequence)).where(SkillRunEvent.skill_run_id == run.id)) or 0) + 1
    item = SkillRunEvent(skill_run_id=run.id, sequence=sequence, event_key=event_key, event_type=event_type, stage=run.current_stage, status=run.status, message=message, progress_current=run.progress_current, progress_total=run.progress_total, data_json=data)
    session.add(item)
    session.flush()
    return item


def _project_history(session: Session, run: SkillRun) -> None:
    from services.feishu_skill_run_sync import sync_skill_run_history
    sync_skill_run_history(session, run)


def create_skill_run(session: Session, *, skill_key: str = "screen_historical_leads", requested_by: str | None = None, idempotency_key: str | None = None, feishu_chat_id: str | None = None, feishu_message_id: str | None = None) -> SkillRun:
    if idempotency_key:
        existing = session.scalar(select(SkillRun).where(SkillRun.idempotency_key == idempotency_key))
        if existing is not None:
            return existing
    definition = get_skill_definition(skill_key)
    run = SkillRun(skill_key=definition.key, skill_version=definition.version, status="draft", requested_by=requested_by, idempotency_key=idempotency_key, feishu_chat_id=feishu_chat_id, feishu_message_id=feishu_message_id)
    session.add(run)
    session.flush()
    _event(session, run, "created")
    return run


def update_skill_run_parameters(session: Session, run_id: int, parameters: dict[str, Any]) -> SkillRun:
    run = _run(session, run_id)
    if run.status not in {"draft", "previewed"}:
        raise ValueError(f"parameters cannot change in status {run.status}")
    run.parameters_json = ScreenHistoricalLeadsParameters.model_validate(parameters).model_dump()
    run.status = "draft"
    run.preview_json = None
    _event(session, run, "parameters_updated")
    return run


def preview_skill_run(session: Session, run_id: int, *, event_key: str | None = None) -> dict[str, Any]:
    run = _run(session, run_id)
    parameters = ScreenHistoricalLeadsParameters.model_validate(run.parameters_json or {})
    candidates = _candidate_refs(session, parameters)
    run.preview_json = {"candidate_count": len(candidates), "limit": parameters.limit, "campaign_id": parameters.campaign_id, "data_range": parameters.data_range, "source_types": parameters.source_types}
    run.checkpoint_json = {"candidates": candidates, "next_index": 0, "screening_ids": []}
    run.status = "previewed"
    run.progress_total = len(candidates)
    _event(session, run, "previewed", event_key=event_key, data=run.preview_json)
    _project_history(session, run)
    return dict(run.preview_json)


def queue_skill_run(session: Session, run_id: int, *, event_key: str | None = None) -> CollectionTask:
    run = _run(session, run_id)
    existing = session.scalar(select(CollectionTask).where(CollectionTask.task_type == SKILL_TASK_TYPE, CollectionTask.target_id == str(run.id), CollectionTask.status.in_(("pending", "retry", "running"))).order_by(CollectionTask.id.desc()))
    if existing is not None:
        _event(session, run, "duplicate_confirm", event_key=event_key)
        return existing
    if run.status not in {"previewed", "failed"}:
        raise ValueError(f"run cannot be queued from status {run.status}")
    run.status = "queued"
    run.error_code = None
    run.error_message = None
    task = create_task(session, task_type=SKILL_TASK_TYPE, platform="internal", target_id=str(run.id), payload_json={"skill_run_id": run.id}, max_attempts=1)
    _event(session, run, "queued", event_key=event_key, data={"task_id": task.id})
    _project_history(session, run)
    return task


def request_skill_run_cancel(session: Session, run_id: int, *, event_key: str | None = None) -> SkillRun:
    run = _run(session, run_id)
    if run.status in TERMINAL_STATUSES:
        _event(session, run, "duplicate_cancel", event_key=event_key)
        return run
    if run.current_stage in NON_INTERRUPTIBLE_STAGES:
        raise ValueError("run has entered a non-interruptible stage")
    run.cancel_requested_at = _now()
    if run.status in {"draft", "previewed", "queued"}:
        run.status = "cancelled"
        run.finished_at = _now()
        task = session.scalar(select(CollectionTask).where(CollectionTask.task_type == SKILL_TASK_TYPE, CollectionTask.target_id == str(run.id), CollectionTask.status.in_(("pending", "retry"))))
        if task is not None:
            task.status = "cancelled"
            task.finished_at = _now()
    else:
        run.status = "cancel_requested"
    _event(session, run, "cancel_requested", event_key=event_key)
    return run


def retry_skill_run(session: Session, run_id: int, *, event_key: str | None = None) -> CollectionTask:
    run = _run(session, run_id)
    if run.status != "failed":
        raise ValueError("only failed runs can be retried")
    run.retry_count += 1
    run.status = "previewed"
    run.current_stage = None
    run.finished_at = None
    run.cancel_requested_at = None
    _event(session, run, "retry_requested", event_key=event_key)
    return queue_skill_run(session, run.id)


def copy_skill_run(session: Session, run_id: int, *, requested_by: str | None = None, event_key: str | None = None) -> SkillRun:
    source = _run(session, run_id)
    if event_key:
        existing_event = session.scalar(select(SkillRunEvent).where(SkillRunEvent.event_key == event_key))
        copied_id = (existing_event.data_json or {}).get("copied_run_id") if existing_event is not None else None
        if copied_id:
            return _run(session, int(copied_id))
    copied = create_skill_run(session, skill_key=source.skill_key, requested_by=requested_by or source.requested_by)
    copied.parameters_json = dict(source.parameters_json or {})
    copied.copied_from_run_id = source.id
    _event(session, source, "copied", event_key=event_key, data={"copied_run_id": copied.id})
    _project_history(session, copied)
    return copied


def finalize_skill_run(
    session: Session,
    run: SkillRun,
    *,
    raw_summary: dict[str, Any],
    queue_date: date | None = None,
) -> dict[str, Any]:
    run.result_summary_json = dict(raw_summary)
    run.status = "succeeded"
    run.current_stage = "summarize"
    run.progress_percent = 100
    run.finished_at = run.finished_at or _now()
    report = rebuild_skill_run_report(session, run.id)
    queue = prepare_daily_review_queue(session, queue_date=queue_date)
    report = {
        **report,
        "queue": {
            "scope": "global_unreviewed_backlog",
            "prepared": queue["total"],
            "quality_control": queue["quality_control"],
            "emergency": queue["emergency"],
            "backlog": queue["backlog"],
            "errors": queue["errors"],
        },
    }
    run.business_report_json = report
    _event(
        session,
        run,
        "succeeded",
        event_key=f"skill-run:{run.id}:succeeded",
        data=run.result_summary_json,
    )
    session.flush()
    return report


def execute_skill_run(session_factory: sessionmaker[Session], run_id: int, *, llm_client: Any = None, customer_client: Any = None, evidence_client: Any = None, progress_callback: Callable[[int], None] | None = None) -> SkillRun:
    def notify() -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(run_id)
        except Exception:
            return

    try:
        with session_factory() as session:
            run = _run(session, run_id)
            if run.status == "cancelled":
                return run
            parameters = ScreenHistoricalLeadsParameters.model_validate(run.parameters_json or {})
            if not run.checkpoint_json:
                preview_skill_run(session, run.id)
            run.status = "running"
            run.current_stage = "prepare"
            run.started_at = run.started_at or _now()
            _event(session, run, "stage_started")
            session.commit()

        campaign = load_registered_campaign(parameters.campaign_id)
        while True:
            with session_factory() as session:
                run = _run(session, run_id)
                checkpoint = dict(run.checkpoint_json or {})
                candidates = list(checkpoint.get("candidates", []))
                index = int(checkpoint.get("next_index", 0))
                if run.status == "cancel_requested" or run.cancel_requested_at:
                    run.status = "cancelled"; run.finished_at = _now(); _event(session, run, "cancelled"); _project_history(session, run); session.commit(); return run
                if index >= len(candidates):
                    break
                candidate = candidates[index]
                run.current_stage = "screen"
                session.commit()
            with session_factory() as session:
                run_llm_lead_screening(session, client=llm_client, source_entity_types={candidate["entity_type"]}, source_entity_ids={int(candidate["entity_id"])}, limit=1, campaign=campaign)
                screening = session.scalar(select(LeadScreeningResult).where(LeadScreeningResult.source_entity_type == candidate["entity_type"], LeadScreeningResult.source_entity_id == int(candidate["entity_id"])))
                run = _run(session, run_id)
                checkpoint = dict(run.checkpoint_json or {})
                ids = list(checkpoint.get("screening_ids", []))
                if screening is not None and screening.id not in ids:
                    ids.append(screening.id)
                checkpoint["screening_ids"] = ids; checkpoint["next_index"] = index + 1
                run.checkpoint_json = checkpoint; run.progress_current = index + 1; run.progress_total = len(candidates); run.progress_percent = int(((index + 1) / max(1, len(candidates))) * 80)
                _event(session, run, "candidate_screened", data=candidate)
                session.commit()
            notify()

        with session_factory() as session:
            run = _run(session, run_id); run.current_stage = "sync_feishu"; _event(session, run, "stage_started"); ids = set((run.checkpoint_json or {}).get("screening_ids", []))
            sync_result = sync_feishu_ai_review_rows(session, customer_client=customer_client, evidence_client=evidence_client, screening_ids=ids)
            run.current_stage = "summarize"
            screenings = session.scalars(select(LeadScreeningResult).where(LeadScreeningResult.id.in_(ids))).all() if ids else []
            sync_data = sync_result.to_dict()
            raw_summary = {"processed_count": len(screenings), "valid_demands": sum(item.valuable is True for item in screenings), "high_intent_customers": sum(item.intent_strength == "high" for item in screenings), "needs_confirmation": sum(item.review_status == "needs_review" or item.qualification_decision == "needs_review" for item in screenings), "feishu_sync": {**sync_data, "created": sync_data.get("customers_created", 0) + sync_data.get("evidence_created", 0), "updated": sync_data.get("customers_updated", 0) + sync_data.get("evidence_updated", 0)}}
            finalize_skill_run(session, run, raw_summary=raw_summary)
            _project_history(session, run); session.commit()
            notify()
            return run
    except Exception as exc:
        with session_factory() as session:
            run = _run(session, run_id); run.status = "failed"; run.error_code = type(exc).__name__; run.error_message = str(exc); run.finished_at = _now(); _event(session, run, "failed", message=str(exc)); _project_history(session, run); session.commit(); return run


def skill_run_result_view(run: SkillRun) -> dict[str, Any]:
    return {"id": run.id, "skill_key": run.skill_key, "status": run.status, "stage": run.current_stage, "progress": {"current": run.progress_current, "total": run.progress_total, "percent": run.progress_percent}, "parameters": run.parameters_json or {}, "preview": run.preview_json or {}, "result": run.result_summary_json or {}, "error": {"code": run.error_code, "message": run.error_message} if run.error_message else None}


def _candidate_refs(session: Session, parameters: ScreenHistoricalLeadsParameters) -> list[dict[str, Any]]:
    cutoff = None
    if parameters.data_range == "last_30_days": cutoff = _now() - timedelta(days=30)
    if parameters.data_range == "last_90_days": cutoff = _now() - timedelta(days=90)
    refs: list[dict[str, Any]] = []
    if parameters.source_types in {"content_and_comment", "content_only"}:
        statement = select(Content.id).order_by(Content.id.desc())
        if cutoff is not None: statement = statement.where(func.coalesce(Content.published_at, Content.created_at) >= cutoff)
        refs.extend({"entity_type": "content", "entity_id": value} for value in session.scalars(statement).all())
    if parameters.source_types in {"content_and_comment", "comment_only"}:
        statement = select(Comment.id).order_by(Comment.id.desc())
        if cutoff is not None: statement = statement.where(func.coalesce(Comment.published_at, Comment.created_at) >= cutoff)
        refs.extend({"entity_type": "comment", "entity_id": value} for value in session.scalars(statement).all())
    return refs[:parameters.limit]


def _run(session: Session, run_id: int) -> SkillRun:
    run = session.get(SkillRun, run_id)
    if run is None: raise ValueError(f"skill run not found: {run_id}")
    return run
