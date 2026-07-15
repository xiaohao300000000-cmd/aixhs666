from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Lead, LeadEvidence, LeadScreeningResult


PENDING_STATUSES = ("new", "needs_enrichment", "watch", "information_insufficient")
ACTION_STATUS = {
    "valid": ("qualified", "valid"),
    "invalid": ("ignored", "invalid"),
    "watch": ("watch", "watch"),
    "needs_information": ("information_insufficient", "needs_information"),
    "follow_up": ("qualified", "valid"),
}
REASON_REQUIRED_ACTIONS = {"invalid", "watch", "needs_information"}


def list_operator_leads(
    session: Session,
    *,
    status_filter: str | None = "pending",
    limit: int = 50,
) -> dict[str, Any]:
    bounded_limit = min(max(limit, 1), 200)
    statement = select(Lead)
    if status_filter == "pending":
        statement = statement.where(Lead.status.in_(PENDING_STATUSES))
    elif status_filter and status_filter != "all":
        statement = statement.where(Lead.status == status_filter)
    leads = session.scalars(statement).all()
    leads.sort(key=lambda item: (item.intent_score or 0, item.updated_at, item.id), reverse=True)
    items = [_lead_view(session, lead) for lead in leads[:bounded_limit]]
    return {
        "total": len(leads),
        "pending_total": sum(lead.status in PENDING_STATUSES for lead in leads),
        "items": items,
        "filters": ["pending", "all", *PENDING_STATUSES, "qualified", "ignored", "handled"],
    }


def get_operator_lead(session: Session, lead_id: int) -> dict[str, Any]:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise LookupError("lead not found")
    return _lead_view(session, lead)


def review_operator_lead(
    session: Session,
    lead_id: int,
    *,
    action: str,
    reason: str | None = None,
    owner_name: str | None = None,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    if action not in ACTION_STATUS:
        raise ValueError(f"unsupported lead review action: {action}")
    normalized_reason = (reason or "").strip() or None
    if action in REASON_REQUIRED_ACTIONS and normalized_reason is None:
        raise ValueError(f"reason is required for {action}")
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise LookupError("lead not found")

    lead_status, human_status = ACTION_STATUS[action]
    lead.status = lead_status
    lead.operator_note = normalized_reason or lead.operator_note
    if owner_name is not None:
        lead.owner_name = owner_name.strip() or None
    if action == "follow_up":
        lead.followup_status = "pending"
        lead.recommended_next_step = "进入人工跟进"
    lead.updated_at = datetime.now(UTC)

    screening = _latest_screening(session, lead)
    if screening is not None:
        screening.human_review_status = human_status
        screening.human_reviewer_id = reviewer_id
        screening.human_reviewed_at = datetime.now(UTC)
        screening.qualification_human_reason = normalized_reason
        if action == "valid" or action == "follow_up":
            screening.qualification_decision = "qualified"
        elif action == "invalid":
            screening.qualification_decision = "rejected"
        else:
            screening.qualification_decision = "needs_review"
    session.flush()
    return _lead_view(session, lead)


def _lead_view(session: Session, lead: Lead) -> dict[str, Any]:
    evidence = session.scalars(
        select(LeadEvidence)
        .where(LeadEvidence.lead_id == lead.id)
        .order_by(LeadEvidence.score_contribution.desc(), LeadEvidence.id.asc())
    ).all()
    screening = _latest_screening(session, lead)
    profile = lead.profile
    return {
        "id": lead.id,
        "display_name": profile.display_name or f"线索 #{lead.id}",
        "profile_url": profile.profile_url,
        "platform": lead.platform,
        "status": lead.status,
        "region_text": lead.region_text or profile.region_text,
        "demand_type": lead.demand_type,
        "product": lead.product,
        "intent_stage": lead.intent_stage,
        "intent_score": lead.intent_score,
        "information_completeness": lead.information_completeness,
        "known_info": lead.known_info_json or {},
        "missing_info": lead.missing_info_json or [],
        "recommended_next_step": lead.recommended_next_step,
        "owner_name": lead.owner_name,
        "operator_note": lead.operator_note,
        "followup_status": lead.followup_status,
        "first_seen_at": _iso(lead.first_seen_at),
        "last_seen_at": _iso(lead.last_seen_at),
        "updated_at": _iso(lead.updated_at),
        "evidence": [
            {
                "id": item.id,
                "source_type": item.source_entity_type,
                "source_id": item.source_entity_id,
                "text": item.evidence_text,
                "demand_type": item.demand_type,
                "intent_stage": item.intent_stage,
                "score": item.score_contribution,
            }
            for item in evidence
        ],
        "screening": _screening_view(screening),
    }


def _latest_screening(session: Session, lead: Lead) -> LeadScreeningResult | None:
    return session.scalar(
        select(LeadScreeningResult)
        .where(LeadScreeningResult.public_profile_id == lead.public_profile_id)
        .order_by(LeadScreeningResult.updated_at.desc(), LeadScreeningResult.id.desc())
        .limit(1)
    )


def _screening_view(screening: LeadScreeningResult | None) -> dict[str, Any] | None:
    if screening is None:
        return None
    context = screening.context_json or {}
    return {
        "id": screening.id,
        "model_name": screening.model_name,
        "valuable": screening.valuable,
        "intent_strength": screening.intent_strength,
        "confidence": screening.confidence,
        "evidence": screening.judgment_evidence_json or [],
        "review_status": screening.review_status,
        "status_reason": screening.status_reason,
        "human_review_status": screening.human_review_status,
        "human_reviewer_id": screening.human_reviewer_id,
        "human_reviewed_at": _iso(screening.human_reviewed_at),
        "qualification_decision": screening.qualification_decision,
        "reason_codes": screening.qualification_reason_codes_json or [],
        "human_reason": screening.qualification_human_reason,
        "policy_version": screening.qualification_policy_version,
        "source_url": context.get("source_url") or context.get("url"),
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()

