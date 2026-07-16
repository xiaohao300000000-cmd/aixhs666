from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.customer_crm_sync import customer_base_record_url, miaoda_customer_url
from storage.models import (
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    FeishuBitableRecord,
    Lead,
    LeadEvidence,
    LeadScreeningResult,
    PublicProfile,
)


def list_operator_customers(
    session: Session,
    *,
    limit: int = 50,
    miaoda_base_url: str | None = None,
) -> dict[str, Any]:
    leads = session.scalars(
        select(Lead)
        .where(Lead.status == "qualified")
        .order_by(Lead.next_followup_at.asc().nullslast(), Lead.updated_at.desc(), Lead.id.desc())
        .limit(limit)
    ).all()
    items = [
        _customer_summary(session, lead, miaoda_base_url=miaoda_base_url)
        for lead in leads
    ]
    return {"items": items, "count": len(items)}


def get_operator_customer(
    session: Session,
    customer_id: int,
    *,
    miaoda_base_url: str | None = None,
) -> dict[str, Any]:
    lead = _customer_or_raise(session, customer_id)
    result = _customer_summary(session, lead, miaoda_base_url=miaoda_base_url)
    result.update(
        {
            "platform": lead.platform,
            "region": lead.region_text or lead.profile.region_text,
            "demand_type": lead.demand_type,
            "product": lead.product,
            "intent_stage": lead.intent_stage,
            "intent_score": lead.intent_score,
            "customer_tags": list(lead.customer_tags_json or []),
            "followup_note": lead.operator_note,
            "next_followup_at": _iso(lead.next_followup_at),
            "last_contact_at": _iso(lead.last_contact_at),
            "last_contact_result": lead.last_contact_result,
            "profile": {
                "platform_user_id": lead.profile.platform_user_id,
                "display_name": lead.profile.display_name,
                "profile_url": lead.profile.profile_url,
            },
            "evidence": [
                {
                    "id": item.id,
                    "source_entity_type": item.source_entity_type,
                    "source_entity_id": item.source_entity_id,
                    "text": item.evidence_text,
                }
                for item in session.scalars(
                    select(LeadEvidence).where(LeadEvidence.lead_id == lead.id).order_by(LeadEvidence.id)
                ).all()
            ],
        }
    )
    screening = session.scalar(
        select(LeadScreeningResult)
        .where(LeadScreeningResult.public_profile_id == lead.public_profile_id)
        .order_by(LeadScreeningResult.updated_at.desc(), LeadScreeningResult.id.desc())
        .limit(1)
    )
    result["ai_judgment"] = (
        {
            "screening_id": screening.id,
            "review_status": screening.review_status,
            "confidence": screening.confidence,
            "qualification_decision": screening.qualification_decision,
            "campaign": screening.qualification_policy_version,
        }
        if screening is not None
        else None
    )
    return result


def get_operator_customer_timeline(session: Session, customer_id: int) -> dict[str, Any]:
    lead = _customer_or_raise(session, customer_id)
    items: list[dict[str, Any]] = []
    for event in session.scalars(
        select(CustomerTimelineEvent)
        .where(CustomerTimelineEvent.lead_id == lead.id)
        .order_by(CustomerTimelineEvent.occurred_at, CustomerTimelineEvent.id)
    ).all():
        items.append(
            {
                "kind": "timeline_event",
                "id": event.id,
                "event_key": event.event_key,
                "event_type": event.event_type,
                "actor_id": event.actor_id,
                "data": event.data_json or {},
                "occurred_at": _iso(event.occurred_at),
                "_sort_at": _aware_utc(event.occurred_at),
            }
        )
    for followup in session.scalars(
        select(CustomerFollowupRecord)
        .where(CustomerFollowupRecord.lead_id == lead.id)
        .order_by(CustomerFollowupRecord.occurred_at, CustomerFollowupRecord.id)
    ).all():
        items.append(
            {
                "kind": "followup_record",
                "id": followup.id,
                "event_key": followup.event_key,
                "action_type": followup.action_type,
                "channel": followup.channel,
                "target": followup.target,
                "content": followup.content,
                "customer_reply": followup.customer_reply,
                "result": followup.result,
                "next_step": followup.next_step,
                "next_followup_at": _iso(followup.next_followup_at),
                "source_entry": followup.source_entry,
                "platform_evidence": followup.platform_evidence_json,
                "is_completed": followup.is_completed,
                "occurred_at": _iso(followup.occurred_at),
                "_sort_at": _aware_utc(followup.occurred_at),
            }
        )
    items.sort(key=lambda item: (item["_sort_at"], item["kind"], item["id"]))
    for item in items:
        item.pop("_sort_at", None)
    return {"customer_id": lead.id, "items": items, "count": len(items)}


def _customer_summary(
    session: Session,
    lead: Lead,
    *,
    miaoda_base_url: str | None,
) -> dict[str, Any]:
    profile = session.get(PublicProfile, lead.public_profile_id)
    mapping = session.scalar(
        select(FeishuBitableRecord)
        .where(
            FeishuBitableRecord.local_entity_type == "customer_crm",
            FeishuBitableRecord.local_entity_id == lead.id,
        )
        .order_by(FeishuBitableRecord.updated_at.desc(), FeishuBitableRecord.id.desc())
        .limit(1)
    )
    base_url = (
        customer_base_record_url(mapping.app_token, mapping.table_id, mapping.record_id)
        if mapping is not None and mapping.record_id
        else None
    )
    return {
        "customer_id": lead.id,
        "customer_name": profile.display_name if profile else f"客户 #{lead.id}",
        "crm_stage": lead.crm_stage,
        "next_step": lead.recommended_next_step,
        "sync_version": lead.crm_sync_version,
        "sync_status": mapping.last_sync_status if mapping is not None else "pending",
        "sync_error": mapping.last_error if mapping is not None else None,
        "base_record_url": base_url,
        "miaoda_detail_url": miaoda_customer_url(lead.id, base_url=miaoda_base_url),
        "updated_at": _iso(lead.updated_at),
    }


def _customer_or_raise(session: Session, customer_id: int) -> Lead:
    lead = session.get(Lead, customer_id)
    if (
        lead is None
        or lead.status != "qualified"
    ):
        raise LookupError("customer not found")
    return lead


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware_utc(value).isoformat() if value is not None else None
