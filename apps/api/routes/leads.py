from __future__ import annotations

from datetime import UTC, datetime, time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.lead_generation import generate_leads_from_history
from storage.database import get_session
from storage.models import EnrichmentTask, Lead, LeadEvidence


router = APIRouter(tags=["leads"])
SessionDep = Annotated[Session, Depends(get_session)]
VALID_STATUSES = {"new", "needs_enrichment", "qualified", "handled", "ignored"}


class LeadStatusPayload(BaseModel):
    status: str


@router.get("/leads", response_class=HTMLResponse)
def leads_page() -> HTMLResponse:
    template = Path(__file__).resolve().parents[1] / "templates" / "leads.html"
    return HTMLResponse(template.read_text(encoding="utf-8"))


@router.get("/leads/static/{filename}")
def leads_static(filename: str) -> FileResponse:
    if filename not in {"leads.css", "leads.js"}:
        raise HTTPException(status_code=404, detail="Static file not found")
    return FileResponse(Path(__file__).resolve().parents[1] / "static" / filename)


@router.get("/api/leads/summary")
def leads_summary(session: SessionDep) -> dict[str, int]:
    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    return {
        "today_new": session.scalar(
            select(func.count(Lead.id)).where(Lead.status == "new", Lead.first_seen_at >= today_start)
        )
        or 0,
        "needs_enrichment": session.scalar(select(func.count(Lead.id)).where(Lead.status == "needs_enrichment")) or 0,
        "qualified": session.scalar(select(func.count(Lead.id)).where(Lead.status == "qualified")) or 0,
        "handled": session.scalar(select(func.count(Lead.id)).where(Lead.status == "handled")) or 0,
        "ignored": session.scalar(select(func.count(Lead.id)).where(Lead.status == "ignored")) or 0,
    }


@router.get("/api/leads")
def list_leads(
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    page_size: int = 50,
) -> dict[str, Any]:
    page_size = min(max(page_size, 1), 200)
    statement = select(Lead).order_by(Lead.intent_score.desc(), Lead.last_seen_at.desc(), Lead.id.desc()).limit(page_size)
    if status_filter:
        statement = statement.where(Lead.status == status_filter)
    leads = session.scalars(statement).all()
    return {"items": [_lead_card(session, lead) for lead in leads]}


@router.post("/api/leads/backfill")
def backfill_leads(session: SessionDep) -> dict[str, Any]:
    result = generate_leads_from_history(session)
    session.commit()
    return {"leads": result.to_dict()}


@router.post("/api/leads/{lead_id}/status")
def update_lead_status(lead_id: int, payload: LeadStatusPayload, session: SessionDep) -> dict[str, Any]:
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid lead status")
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead.status = payload.status
    lead.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(lead)
    return _lead_card(session, lead)


def _lead_card(session: Session, lead: Lead) -> dict[str, Any]:
    evidence = session.scalars(
        select(LeadEvidence).where(LeadEvidence.lead_id == lead.id).order_by(LeadEvidence.score_contribution.desc(), LeadEvidence.id.asc())
    ).all()
    tasks = session.scalars(
        select(EnrichmentTask).where(EnrichmentTask.lead_id == lead.id).order_by(EnrichmentTask.id.asc())
    ).all()
    profile = lead.profile
    return {
        "id": lead.id,
        "status": lead.status,
        "platform": lead.platform,
        "public_profile_id": lead.public_profile_id,
        "platform_user_id": profile.platform_user_id if profile else None,
        "display_name": profile.display_name if profile else None,
        "profile_url": profile.profile_url if profile else None,
        "region_text": lead.region_text,
        "demand_type": lead.demand_type,
        "product": lead.product,
        "intent_stage": lead.intent_stage,
        "intent_score": lead.intent_score,
        "information_completeness": lead.information_completeness,
        "known_info": lead.known_info_json or {},
        "missing_info": lead.missing_info_json or [],
        "recommended_next_step": lead.recommended_next_step,
        "first_seen_at": _iso(lead.first_seen_at),
        "last_seen_at": _iso(lead.last_seen_at),
        "evidence": [
            {
                "id": item.id,
                "source_entity_type": item.source_entity_type,
                "source_entity_id": item.source_entity_id,
                "content_id": item.content_id,
                "comment_id": item.comment_id,
                "evidence_text": item.evidence_text,
                "demand_type": item.demand_type,
                "intent_stage": item.intent_stage,
                "score_contribution": item.score_contribution,
            }
            for item in evidence
        ],
        "enrichment_tasks": [
            {
                "id": task.id,
                "task_type": task.task_type,
                "status": task.status,
                "reason": task.reason,
            }
            for task in tasks
        ],
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
