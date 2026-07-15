from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.operator_leads import get_operator_lead, list_operator_leads, review_operator_lead
from services.operator_tasks import (
    cancel_operator_run,
    copy_operator_run,
    create_operator_run,
    get_operator_run,
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
        result = review_operator_lead(
            session,
            lead_id,
            action=payload.action,
            reason=payload.reason,
            owner_name=payload.owner_name,
            reviewer_id=payload.reviewer_id,
        )
        session.commit()
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
