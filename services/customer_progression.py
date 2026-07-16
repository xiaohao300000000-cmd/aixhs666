from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.daily_review_queue import complete_candidate_review
from storage.models import CustomerFollowupRecord, CustomerTimelineEvent, Lead, LeadScreeningResult


@dataclass(frozen=True)
class CustomerProgressionResult:
    customer_id: int
    customer_stage: str
    next_action: str
    timeline_event_id: int
    timeline_event_type: str
    screening_id: int | None
    idempotent_replay: bool
    followup_record_id: int | None = None
    crm_sync_status: str = "not_requested"

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "customer_stage": self.customer_stage,
            "next_action": self.next_action,
            "timeline_event_id": self.timeline_event_id,
            "timeline_event_type": self.timeline_event_type,
            "screening_id": self.screening_id,
            "idempotent_replay": self.idempotent_replay,
            "followup_record_id": self.followup_record_id,
            "crm_sync_status": self.crm_sync_status,
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
        existing_lead = session.get(Lead, lead_id)
        existing_data = existing.data_json or {}
        complete_candidate_review(
            session,
            decision=str(existing_data.get("action") or normalized_action),
            reviewed_at=existing.occurred_at,
            lead_id=lead_id,
            public_profile_id=existing_lead.public_profile_id if existing_lead is not None else None,
            screening_id=(
                int(existing_data["screening_id"])
                if existing_data.get("screening_id") is not None
                else None
            ),
        )
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
        lead.crm_stage = customer_stage
    elif normalized_action == "defer":
        lead.status = "watch"
        lead.followup_status = "deferred"
        lead.next_followup_at = defer_until
        lead.recommended_next_step = "等待重新提醒"
        customer_stage = "deferred"
        next_action = "wait_for_reactivation"
        human_status = "watch"
        qualification_decision = "needs_review"
        lead.crm_stage = customer_stage
    else:
        lead.status = "ignored"
        lead.followup_status = None
        lead.next_followup_at = None
        lead.recommended_next_step = "无需继续跟进"
        customer_stage = "invalid"
        next_action = "none"
        human_status = "invalid"
        qualification_decision = "rejected"
        lead.crm_stage = customer_stage

    lead.crm_sync_version = (lead.crm_sync_version or 0) + 1
    lead.updated_at = now
    if screening is not None:
        screening.human_review_status = human_status
        screening.human_reviewer_id = reviewer_id
        screening.human_reviewed_at = now
        screening.qualification_human_reason = normalized_reason
        screening.qualification_decision = qualification_decision
        screening.updated_at = now

    followup: CustomerFollowupRecord | None = None
    if normalized_action == "promote":
        followup = CustomerFollowupRecord(
            lead_id=lead.id,
            event_key=f"customer-followup:{event_key}:first-contact",
            occurred_at=now,
            action_type="待首次联系",
            channel="xhs_public_reply",
            result="pending",
            next_step="准备首次公开回复",
            source_entry="customer_progression",
            is_completed=False,
        )
        session.add(followup)
        session.flush()

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
            "followup_record_id": followup.id if followup is not None else None,
            "crm_sync_status": "pending",
            "crm_sync_version": lead.crm_sync_version,
        },
        occurred_at=now,
    )
    session.add(event)
    session.flush()
    complete_candidate_review(
        session,
        decision=normalized_action,
        reviewed_at=now,
        lead_id=lead.id,
        public_profile_id=lead.public_profile_id,
        screening_id=screening.id if screening is not None else None,
    )
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
        lead = Lead(
            platform=screening.platform,
            public_profile_id=screening.public_profile_id,
            status="new",
            demand_type=screening.demand_type,
            intent_stage=screening.intent_strength,
            intent_score=screening.confidence or 0,
            recommended_next_step="人工确认",
        )
        session.add(lead)
        session.flush()
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
        followup_record_id=(
            int(data["followup_record_id"]) if data.get("followup_record_id") is not None else None
        ),
        crm_sync_status=str(data.get("crm_sync_status") or "not_requested"),
    )
