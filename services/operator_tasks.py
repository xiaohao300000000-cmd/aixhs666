from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.daily_review_queue import (
    business_date,
    extend_daily_review_queue,
    list_daily_review_queue,
    prepare_daily_review_queue,
)
from services.skill_registry import list_campaign_options, list_skill_definitions
from services.skill_run_report import build_run_candidates, rebuild_skill_run_report
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
from storage.models import ReviewQueueOperation, SkillRun


REPORT_REBUILD_OPERATION = "report_rebuild"
PREPARE_REVIEW_QUEUE_OPERATION = "prepare_review_queue"
CONTINUE_REVIEW_QUEUE_OPERATION = "continue_review_queue"


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


def get_operator_run_report(
    session: Session,
    run_id: int,
    *,
    rebuild: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    run = _get_run(session, run_id)
    if rebuild:
        return _run_idempotent_review_queue_operation(
            session,
            operation_kind=REPORT_REBUILD_OPERATION,
            queue_date=business_date(),
            idempotency_key=idempotency_key,
            request={"run_id": run.id},
            action=lambda: rebuild_skill_run_report(session, run.id),
        )
    if run.business_report_json is None:
        raise LookupError("business report has not been built")
    return dict(run.business_report_json)


def list_operator_run_candidates(
    session: Session,
    run_id: int,
    *,
    layer: str | None = None,
) -> dict[str, Any]:
    run = _get_run(session, run_id)
    items = build_run_candidates(session, run)
    if layer is not None:
        items = [item for item in items if item["layer"] == layer]
    return {
        "run_id": run.id,
        "layer": layer,
        "count": len(items),
        "items": items,
        "next_action": {
            "kind": "prepare_review_queue",
            "label": "准备审核队列",
            "href": f"/tasks?run_id={run.id}",
        },
    }


def prepare_operator_review_queue(
    session: Session,
    run_id: int,
    *,
    queue_date: date | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized_key = _require_idempotency_key(idempotency_key)
    run = _get_run(session, run_id)
    day = queue_date or business_date()

    def prepare() -> dict[str, Any]:
        report = rebuild_skill_run_report(session, run.id)
        queue = prepare_daily_review_queue(session, queue_date=day)
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
        session.flush()
        return {"run_id": run.id, **queue}

    result = _run_idempotent_review_queue_operation(
        session,
        operation_kind=PREPARE_REVIEW_QUEUE_OPERATION,
        queue_date=day,
        idempotency_key=normalized_key,
        request={"run_id": run.id},
        action=prepare,
    )
    return {"idempotency_key": normalized_key, **result}


def get_operator_review_queue(
    session: Session,
    *,
    queue_date: date | None = None,
    layer: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    return list_daily_review_queue(
        session,
        queue_date=queue_date,
        layer=layer,
        offset=offset,
        limit=limit,
    )


def continue_operator_review_queue(
    session: Session,
    *,
    queue_date: date | None = None,
    additional: int = 20,
    priority_only: bool = False,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized_key = _require_idempotency_key(idempotency_key)
    day = queue_date or business_date()
    result = _run_idempotent_review_queue_operation(
        session,
        operation_kind=CONTINUE_REVIEW_QUEUE_OPERATION,
        queue_date=day,
        idempotency_key=normalized_key,
        request={"additional": additional, "priority_only": priority_only},
        action=lambda: {
            "priority_only": priority_only,
            **extend_daily_review_queue(
                session,
                queue_date=day,
                additional=additional,
                priority_only=priority_only,
            ),
        },
    )
    return {"idempotency_key": normalized_key, **result}


def _run_idempotent_review_queue_operation(
    session: Session,
    *,
    operation_kind: str,
    queue_date: date,
    idempotency_key: str | None,
    request: dict[str, Any],
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    normalized_key = _require_idempotency_key(idempotency_key)
    key_hash = sha256(normalized_key.encode("utf-8")).hexdigest()
    normalized_request = _normalize_json_dict(request)
    existing = session.scalar(
        select(ReviewQueueOperation).where(
            ReviewQueueOperation.idempotency_key_hash == key_hash
        )
    )
    if existing is not None:
        if (
            existing.operation_kind != operation_kind
            or existing.queue_date != queue_date
            or existing.request_json != normalized_request
        ):
            raise ValueError("idempotency key conflicts with an existing operation")
        return deepcopy(existing.result_json)

    result = _normalize_json_dict(action())
    operation = ReviewQueueOperation(
        operation_kind=operation_kind,
        queue_date=queue_date,
        idempotency_key_hash=key_hash,
        request_json=normalized_request,
        result_json=deepcopy(result),
    )
    session.add(operation)
    session.flush()
    return deepcopy(result)


def _normalize_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def _get_run(session: Session, run_id: int) -> SkillRun:
    run = session.get(SkillRun, run_id)
    if run is None:
        raise LookupError("skill run not found")
    return run


def _require_idempotency_key(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


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
