from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import CustomerTimelineEvent, Lead, LeadScreeningResult


@dataclass(frozen=True)
class CustomerProgressionResult:
    customer_id: int
    customer_stage: str
    next_action: str
    timeline_event_id: int
    timeline_event_type: str
    screening_id: int | None
    idempotent_replay: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "customer_stage": self.customer_stage,
            "next_action": self.next_action,
            "timeline_event_id": self.timeline_event_id,
            "timeline_event_type": self.timeline_event_type,
            "screening_id": self.screening_id,
            "idempotent_replay": self.idempotent_replay,
        }


_ACTIONS = {"promote", "defer", "reject"}
_REASON_REQUIRED = {"defer", "reject"}
_EVENT_TYPES = {
    "promote": "candidate_promoted",
    "defer": "candidate_deferred",
    "reject": "candidate_rejected",
}


def progress_operator_lead(
    session: Session,
    lead_id: int,
    *,
    action: str,
    idempotency_key: str,
    reason: str | None = None,
    reviewer_id: str | None = None,
    defer_until: datetime | None = None,
    owner_name: str | None = None,
) -> CustomerProgressionResult:
    normalized_action = action.strip().casefold()
    if normalized_action not in _ACTIONS:
        raise ValueError(f"unsupported customer progression action: {action}")
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise ValueError("idempotency_key is required")
    normalized_reason = (reason or "").strip() or None
    if normalized_action in _REASON_REQUIRED and normalized_reason is None:
        raise ValueError(f"reason is required for {normalized_action}")
    if normalized_action == "defer" and defer_until is None:
        raise ValueError("defer_until is required for defer")
    if defer_until is not None:
        if defer_until.tzinfo is None:
            defer_until = defer_until.replace(tzinfo=UTC)
        if defer_until <= datetime.now(UTC):
            raise ValueError("defer_until must be in the future")

    event_key = f"customer-progression:{normalized_key}"
    existing = session.scalar(select(CustomerTimelineEvent).where(CustomerTimelineEvent.event_key == event_key))
    if existing is not None:
        if existing.lead_id != lead_id:
            raise ValueError("idempotency_key already belongs to another customer")
        return _result_from_event(existing, idempotent_replay=True)

    lead = session.get(Lead, lead_id)
    if lead is None:
        raise LookupError("lead not found")
    screening = _latest_screening(session, lead.public_profile_id)
    now = datetime.now(UTC)

    if owner_name is not None:
        lead.owner_name = owner_name.strip() or None
    lead.operator_note = normalized_reason or lead.operator_note
    lead.last_feedback_at = now

    if normalized_action == "promote":
        lead.status = "qualified"
        lead.followup_status = "pending"
        lead.next_followup_at = None
        lead.recommended_next_step = "准备首次公开回复"
        customer_stage = "awaiting_first_contact"
        next_action = "prepare_public_reply"
        human_status = "valid"
        qualification_decision = "qualified"
    elif normalized_action == "defer":
        lead.status = "watch"
        lead.followup_status = "deferred"
        lead.next_followup_at = defer_until
        lead.recommended_next_step = "等待重新提醒"
        customer_stage = "deferred"
        next_action = "wait_for_reactivation"
        human_status = "watch"
        qualification_decision = "needs_review"
    else:
        lead.status = "ignored"
        lead.followup_status = None
        lead.next_followup_at = None
        lead.recommended_next_step = "无需继续跟进"
        customer_stage = "invalid"
        next_action = "none"
        human_status = "invalid"
        qualification_decision = "rejected"

    lead.updated_at = now
    if screening is not None:
        screening.human_review_status = human_status
        screening.human_reviewer_id = reviewer_id
        screening.human_reviewed_at = now
        screening.qualification_human_reason = normalized_reason
        screening.qualification_decision = qualification_decision
        screening.updated_at = now

    event = CustomerTimelineEvent(
        lead_id=lead.id,
        event_key=event_key,
        event_type=_EVENT_TYPES[normalized_action],
        actor_id=reviewer_id,
        data_json={
            "action": normalized_action,
            "reason": normalized_reason,
            "customer_stage": customer_stage,
            "next_action": next_action,
            "screening_id": screening.id if screening is not None else None,
            "defer_until": defer_until.isoformat() if defer_until is not None else None,
        },
        occurred_at=now,
    )
    session.add(event)
    session.flush()
    return _result_from_event(event, idempotent_replay=False)


def promote_screening_customer(
    session: Session,
    screening_id: int,
    *,
    reviewer_id: str | None,
    idempotency_key: str,
    reason: str | None = None,
) -> CustomerProgressionResult:
    screening = session.get(LeadScreeningResult, screening_id)
    if screening is None:
        raise LookupError("screening result not found")
    if screening.public_profile_id is None:
        raise LookupError("screening result has no customer profile")
    lead = session.scalar(
        select(Lead).where(
            Lead.platform == screening.platform,
            Lead.public_profile_id == screening.public_profile_id,
        )
    )
    if lead is None:
        raise LookupError("lead not found for screening result")
    return progress_operator_lead(
        session,
        lead.id,
        action="promote",
        reason=reason,
        reviewer_id=reviewer_id,
        idempotency_key=idempotency_key,
    )


def _latest_screening(session: Session, public_profile_id: int) -> LeadScreeningResult | None:
    return session.scalar(
        select(LeadScreeningResult)
        .where(LeadScreeningResult.public_profile_id == public_profile_id)
        .order_by(LeadScreeningResult.updated_at.desc(), LeadScreeningResult.id.desc())
        .limit(1)
    )


def _result_from_event(event: CustomerTimelineEvent, *, idempotent_replay: bool) -> CustomerProgressionResult:
    data = event.data_json or {}
    return CustomerProgressionResult(
        customer_id=event.lead_id,
        customer_stage=str(data.get("customer_stage") or "unknown"),
        next_action=str(data.get("next_action") or "none"),
        timeline_event_id=event.id,
        timeline_event_type=event.event_type,
        screening_id=int(data["screening_id"]) if data.get("screening_id") is not None else None,
        idempotent_replay=idempotent_replay,
    )
