from __future__ import annotations

import hmac
import os
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from services.customer_crm_sync import sync_customer_crm
from services.customer_progression import progress_operator_lead
from services.contact_commands import (
    approve_contact_draft,
    confirm_contact_not_sent,
    edit_contact_draft,
    prepare_contact_draft,
    send_approved_contact,
)
from services.operator_customers import (
    get_operator_customer,
    get_operator_customer_timeline,
    get_operator_contact_attempt,
    list_operator_customers,
    require_operator_contact_attempt,
)
from services.operator_leads import get_operator_lead, list_operator_leads
from services.operator_tasks import (
    cancel_operator_run,
    continue_operator_review_queue,
    copy_operator_run,
    create_operator_run,
    get_operator_review_queue,
    get_operator_run,
    get_operator_run_report,
    list_operator_run_candidates,
    prepare_operator_review_queue,
    preview_operator_run,
    queue_operator_run,
    retry_operator_run,
    task_center_view,
)
from services.operator_workbench import build_operator_workbench
from storage.database import get_session


router = APIRouter(prefix="/operator/api", tags=["operator"])
SessionDep = Annotated[Session, Depends(get_session)]


def _require_operator_token(
    authorization: Annotated[str | None, Header()] = None,
    x_ops_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = os.getenv("OPS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator API is not configured",
        )
    bearer = authorization.removeprefix("Bearer ").strip() if authorization else None
    provided = bearer or x_ops_token or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid operator token")


OperatorAuth = Annotated[None, Depends(_require_operator_token)]


class LeadReviewPayload(BaseModel):
    action: str
    reason: str | None = None
    owner_name: str | None = None
    reviewer_id: str | None = None
    idempotency_key: str | None = None
    defer_until: datetime | None = None


class CreateRunPayload(BaseModel):
    skill_key: str = "screen_historical_leads"
    requested_by: str | None = None
    idempotency_key: str | None = None


class PreviewRunPayload(BaseModel):
    parameters: dict[str, Any]
    event_key: str | None = None


class RunActionPayload(BaseModel):
    event_key: str | None = None
    requested_by: str | None = None


class SyncCustomersPayload(BaseModel):
    customer_ids: list[int] | None = None
    idempotency_key: Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class IdempotencyPayload(BaseModel):
    idempotency_key: Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class PrepareReviewQueuePayload(IdempotencyPayload):
    queue_date: date | None = None


class ContinueReviewQueuePayload(IdempotencyPayload):
    queue_date: date | None = None
    additional: Annotated[int, Field(ge=1, le=200)] = 20
    priority_only: bool = False


class ContactPreparePayload(IdempotencyPayload):
    pass


class ContactDraftPayload(IdempotencyPayload):
    draft_revision: Annotated[int, Field(ge=1)]
    text: Annotated[str, Field(min_length=1, max_length=300, pattern=r".*\S.*")]
    operator: Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class ContactApprovalPayload(IdempotencyPayload):
    draft_revision: Annotated[int, Field(ge=1)]
    operator: Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


class ContactSendPayload(ContactApprovalPayload):
    confirmed: bool


class ContactRecoveryPayload(IdempotencyPayload):
    operator: Annotated[str, Field(min_length=1, pattern=r".*\S.*")]
    reason: Annotated[str, Field(min_length=1, max_length=1000, pattern=r".*\S.*")]


@router.get("/workbench")
def get_operator_workbench(session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    return build_operator_workbench(session)


@router.get("/leads")
def get_operator_leads(
    session: SessionDep,
    _: OperatorAuth,
    status_filter: str | None = "pending",
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return list_operator_leads(session, status_filter=status_filter, limit=limit)


@router.get("/leads/{lead_id}")
def get_operator_lead_detail(lead_id: int, session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    try:
        return get_operator_lead(session, lead_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/leads/{lead_id}/review")
def post_operator_lead_review(
    lead_id: int,
    payload: LeadReviewPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    try:
        legacy_actions = {
            "valid": "promote",
            "follow_up": "promote",
            "watch": "defer",
            "needs_information": "defer",
            "invalid": "reject",
        }
        action = legacy_actions.get(payload.action, payload.action)
        defer_until = payload.defer_until
        if action == "defer" and defer_until is None and payload.action in legacy_actions:
            defer_until = datetime.now(UTC) + timedelta(days=3)
        progression = progress_operator_lead(
            session,
            lead_id,
            action=action,
            reason=payload.reason,
            owner_name=payload.owner_name,
            reviewer_id=payload.reviewer_id,
            defer_until=defer_until,
            idempotency_key=payload.idempotency_key or f"operator-review:{uuid4().hex}",
        )
        lead = get_operator_lead(session, lead_id)
        session.commit()
        return {"lead": lead, "progression": progression.as_dict()}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/customers")
def get_operator_customers(
    session: SessionDep,
    _: OperatorAuth,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return list_operator_customers(session, limit=limit)


@router.post("/customers/sync")
def post_operator_customer_sync(
    payload: SyncCustomersPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    factory = sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)
    result = sync_customer_crm(factory, customer_ids=payload.customer_ids)
    return {"idempotency_key": payload.idempotency_key, "sync": result.to_dict()}


@router.get("/customers/{customer_id}")
def get_operator_customer_detail(customer_id: int, session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    try:
        return get_operator_customer(session, customer_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/customers/{customer_id}/timeline")
def get_operator_customer_timeline_view(
    customer_id: int,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    try:
        return get_operator_customer_timeline(session, customer_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/customers/{customer_id}/contact-attempt")
def get_operator_customer_contact_attempt(
    customer_id: int,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    try:
        return get_operator_contact_attempt(session, customer_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/customers/{customer_id}/contact-attempt/prepare")
def post_operator_customer_contact_prepare(
    customer_id: int,
    payload: ContactPreparePayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _contact_write(
        session,
        lambda: prepare_contact_draft(
            session,
            customer_id=customer_id,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.put("/customers/{customer_id}/contact-attempt/{attempt_id}/draft")
def put_operator_customer_contact_draft(
    customer_id: int,
    attempt_id: int,
    payload: ContactDraftPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    require_operator_contact_attempt(session, customer_id=customer_id, attempt_id=attempt_id)
    return _contact_write(
        session,
        lambda: edit_contact_draft(
            session,
            reply_id=attempt_id,
            draft_revision=payload.draft_revision,
            text=payload.text,
            operator=payload.operator,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.post("/customers/{customer_id}/contact-attempt/{attempt_id}/approve")
def post_operator_customer_contact_approve(
    customer_id: int,
    attempt_id: int,
    payload: ContactApprovalPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    require_operator_contact_attempt(session, customer_id=customer_id, attempt_id=attempt_id)
    return _contact_write(session, lambda: approve_contact_draft(session, reply_id=attempt_id, **payload.model_dump()))


@router.post("/customers/{customer_id}/contact-attempt/{attempt_id}/send")
def post_operator_customer_contact_send(
    customer_id: int,
    attempt_id: int,
    payload: ContactSendPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    require_operator_contact_attempt(session, customer_id=customer_id, attempt_id=attempt_id)
    return _contact_write(session, lambda: send_approved_contact(session, reply_id=attempt_id, **payload.model_dump()))


@router.post("/customers/{customer_id}/contact-attempt/{attempt_id}/confirm-not-sent")
def post_operator_customer_contact_confirm_not_sent(
    customer_id: int,
    attempt_id: int,
    payload: ContactRecoveryPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    require_operator_contact_attempt(session, customer_id=customer_id, attempt_id=attempt_id)
    return _contact_write(session, lambda: confirm_contact_not_sent(session, reply_id=attempt_id, **payload.model_dump()))


@router.get("/tasks")
def get_operator_tasks(
    session: SessionDep,
    _: OperatorAuth,
    limit: Annotated[int, Field(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    return task_center_view(session, limit=limit)


@router.get("/tasks/runs/{run_id}")
def get_operator_task_run(run_id: int, session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    try:
        return get_operator_run(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/runs/{run_id}/report")
def get_operator_task_report(run_id: int, session: SessionDep, _: OperatorAuth) -> dict[str, Any]:
    try:
        return get_operator_run_report(session, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/runs/{run_id}/report/rebuild")
def post_operator_task_report_rebuild(
    run_id: int,
    payload: IdempotencyPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(
        session,
        lambda: get_operator_run_report(
            session,
            run_id,
            rebuild=True,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.get("/tasks/runs/{run_id}/candidates")
def get_operator_task_candidates(
    run_id: int,
    session: SessionDep,
    _: OperatorAuth,
    layer: str | None = None,
) -> dict[str, Any]:
    try:
        return list_operator_run_candidates(session, run_id, layer=layer)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/runs/{run_id}/review-queue")
def post_operator_task_review_queue(
    run_id: int,
    payload: PrepareReviewQueuePayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(
        session,
        lambda: prepare_operator_review_queue(
            session,
            run_id,
            queue_date=payload.queue_date,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.get("/review-queue")
def get_operator_daily_review_queue(
    session: SessionDep,
    _: OperatorAuth,
    queue_date: date | None = None,
    layer: str | None = None,
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return get_operator_review_queue(
        session,
        queue_date=queue_date,
        layer=layer,
        offset=offset,
        limit=limit,
    )


@router.post("/review-queue/continue")
def post_operator_daily_review_queue_continue(
    payload: ContinueReviewQueuePayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(
        session,
        lambda: continue_operator_review_queue(
            session,
            queue_date=payload.queue_date,
            additional=payload.additional,
            priority_only=payload.priority_only,
            idempotency_key=payload.idempotency_key,
        ),
    )


@router.post("/tasks/runs")
def post_operator_task_run(
    payload: CreateRunPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    try:
        result = create_operator_run(
            session,
            skill_key=payload.skill_key,
            requested_by=payload.requested_by,
            idempotency_key=payload.idempotency_key,
        )
        session.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tasks/runs/{run_id}/preview")
def post_operator_task_preview(
    run_id: int,
    payload: PreviewRunPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(
        session,
        lambda: preview_operator_run(
            session,
            run_id,
            parameters=payload.parameters,
            event_key=payload.event_key,
        ),
    )


@router.post("/tasks/runs/{run_id}/queue")
def post_operator_task_queue(
    run_id: int,
    payload: RunActionPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(session, lambda: queue_operator_run(session, run_id, event_key=payload.event_key))


@router.post("/tasks/runs/{run_id}/cancel")
def post_operator_task_cancel(
    run_id: int,
    payload: RunActionPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(session, lambda: cancel_operator_run(session, run_id, event_key=payload.event_key))


@router.post("/tasks/runs/{run_id}/retry")
def post_operator_task_retry(
    run_id: int,
    payload: RunActionPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(session, lambda: retry_operator_run(session, run_id, event_key=payload.event_key))


@router.post("/tasks/runs/{run_id}/copy")
def post_operator_task_copy(
    run_id: int,
    payload: RunActionPayload,
    session: SessionDep,
    _: OperatorAuth,
) -> dict[str, Any]:
    return _task_write(
        session,
        lambda: copy_operator_run(
            session,
            run_id,
            requested_by=payload.requested_by,
            event_key=payload.event_key,
        ),
    )


def _task_write(session: Session, action: Any) -> dict[str, Any]:
    try:
        result = action()
        session.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _contact_write(session: Session, action: Any) -> dict[str, Any]:
    try:
        result = action()
        session.commit()
        return result
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
