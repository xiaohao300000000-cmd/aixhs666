from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.skill_registry import list_campaign_options, list_skill_definitions
from services.skill_runtime import (
    copy_skill_run,
    create_skill_run,
    preview_skill_run,
    queue_skill_run,
    request_skill_run_cancel,
    retry_skill_run,
    skill_run_result_view,
    update_skill_run_parameters,
)
from storage.models import SkillRun


def task_center_view(session: Session, *, limit: int = 30) -> dict[str, Any]:
    bounded_limit = min(max(limit, 1), 100)
    runs = session.scalars(
        select(SkillRun).order_by(SkillRun.updated_at.desc(), SkillRun.id.desc()).limit(bounded_limit)
    ).all()
    campaigns = [
        {
            "id": item.campaign_id,
            "name": item.name,
            "service_mode": item.service_mode,
            "location_summary": item.location_summary,
        }
        for item in list_campaign_options()
    ]
    templates = [
        {
            "key": item.key,
            "name": item.name,
            "version": item.version,
            "description": item.description,
            "stages": list(item.stages),
            "external_read": False,
            "external_write": False,
            "cancellable": True,
            "retryable": True,
            "defaults": {
                "data_range": "all",
                "source_types": "content_and_comment",
                "limit": 50,
                "campaign_id": campaigns[0]["id"] if campaigns else "",
            },
        }
        for item in list_skill_definitions()
    ]
    return {"templates": templates, "campaigns": campaigns, "runs": [_run_view(run) for run in runs]}


def create_operator_run(
    session: Session,
    *,
    skill_key: str = "screen_historical_leads",
    requested_by: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    run = create_skill_run(
        session,
        skill_key=skill_key,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
    )
    session.flush()
    return _run_view(run)


def preview_operator_run(
    session: Session,
    run_id: int,
    *,
    parameters: dict[str, Any],
    event_key: str | None = None,
) -> dict[str, Any]:
    update_skill_run_parameters(session, run_id, parameters)
    preview_skill_run(session, run_id, event_key=event_key)
    session.flush()
    return _run_view(_get_run(session, run_id))


def queue_operator_run(session: Session, run_id: int, *, event_key: str | None = None) -> dict[str, Any]:
    queue_skill_run(session, run_id, event_key=event_key)
    session.flush()
    return _run_view(_get_run(session, run_id))


def cancel_operator_run(session: Session, run_id: int, *, event_key: str | None = None) -> dict[str, Any]:
    run = request_skill_run_cancel(session, run_id, event_key=event_key)
    session.flush()
    return _run_view(run)


def retry_operator_run(session: Session, run_id: int, *, event_key: str | None = None) -> dict[str, Any]:
    retry_skill_run(session, run_id, event_key=event_key)
    session.flush()
    return _run_view(_get_run(session, run_id))


def copy_operator_run(
    session: Session,
    run_id: int,
    *,
    requested_by: str | None = None,
    event_key: str | None = None,
) -> dict[str, Any]:
    run = copy_skill_run(session, run_id, requested_by=requested_by, event_key=event_key)
    session.flush()
    return _run_view(run)


def get_operator_run(session: Session, run_id: int) -> dict[str, Any]:
    return _run_view(_get_run(session, run_id))


def _get_run(session: Session, run_id: int) -> SkillRun:
    run = session.get(SkillRun, run_id)
    if run is None:
        raise LookupError("skill run not found")
    return run


def _run_view(run: SkillRun) -> dict[str, Any]:
    base = skill_run_result_view(run)
    base.update(
        {
            "skill_version": run.skill_version,
            "requested_by": run.requested_by,
            "retry_count": run.retry_count,
            "copied_from_run_id": run.copied_from_run_id,
            "created_at": _iso(run.created_at),
            "updated_at": _iso(run.updated_at),
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "events": [
                {
                    "sequence": event.sequence,
                    "type": event.event_type,
                    "stage": event.stage,
                    "status": event.status,
                    "message": event.message,
                    "progress_current": event.progress_current,
                    "progress_total": event.progress_total,
                    "data": event.data_json or {},
                    "created_at": _iso(event.created_at),
                }
                for event in run.events
            ],
        }
    )
    return base


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()

