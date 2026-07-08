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
VALID_STATUSES = {
    "new",
    "needs_enrichment",
    "qualified",
    "watch",
    "information_insufficient",
    "duplicate",
    "handled",
    "ignored",
}
JUDGMENT_ACTIONS = [
    {"status": "qualified", "label": "有效"},
    {"status": "ignored", "label": "无效"},
    {"status": "watch", "label": "观察"},
    {"status": "information_insufficient", "label": "信息不足"},
    {"status": "duplicate", "label": "重复"},
    {"status": "handled", "label": "已联系"},
]


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
    leads = session.scalars(select(Lead)).all()
    summary = {
        "today_new": session.scalar(
            select(func.count(Lead.id)).where(Lead.status == "new", Lead.first_seen_at >= today_start)
        )
        or 0,
        "needs_enrichment": session.scalar(select(func.count(Lead.id)).where(Lead.status == "needs_enrichment")) or 0,
        "qualified": session.scalar(select(func.count(Lead.id)).where(Lead.status == "qualified")) or 0,
        "handled": session.scalar(select(func.count(Lead.id)).where(Lead.status == "handled")) or 0,
        "ignored": session.scalar(select(func.count(Lead.id)).where(Lead.status == "ignored")) or 0,
        "watch": session.scalar(select(func.count(Lead.id)).where(Lead.status == "watch")) or 0,
        "information_insufficient": session.scalar(
            select(func.count(Lead.id)).where(Lead.status == "information_insufficient")
        )
        or 0,
        "duplicate": session.scalar(select(func.count(Lead.id)).where(Lead.status == "duplicate")) or 0,
        "priority_immediate": 0,
        "priority_today": 0,
        "priority_observe": 0,
        "priority_insufficient": 0,
        "priority_stale": 0,
    }
    for lead in leads:
        bucket = _priority_bucket(lead)
        if bucket == "立即处理":
            summary["priority_immediate"] += 1
        elif bucket == "今日内处理":
            summary["priority_today"] += 1
        elif bucket == "可观察":
            summary["priority_observe"] += 1
        elif bucket == "信息不足":
            summary["priority_insufficient"] += 1
        elif bucket == "过期/低优先级":
            summary["priority_stale"] += 1
    return summary


@router.get("/api/leads")
def list_leads(
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    page_size: int = 50,
) -> dict[str, Any]:
    page_size = min(max(page_size, 1), 200)
    statement = select(Lead)
    if status_filter:
        statement = statement.where(Lead.status == status_filter)
    leads = session.scalars(statement).all()
    leads.sort(key=_lead_sort_key, reverse=True)
    return {"items": [_lead_card(session, lead) for lead in leads[:page_size]]}


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
    evidence_payload = [_evidence_card(item) for item in evidence]
    return {
        "id": lead.id,
        "status": lead.status,
        "status_label": _status_label(lead.status),
        "business_summary": _business_summary(lead, evidence),
        "priority_bucket": _priority_bucket(lead),
        "sla_due_label": _sla_due_label(lead),
        "freshness_label": _freshness_label(lead.last_seen_at),
        "source_role": _source_role(evidence[0].source_entity_type if evidence else None),
        "why_recommended": _why_recommended(lead, evidence),
        "judgment_actions": JUDGMENT_ACTIONS,
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
        "evidence": evidence_payload,
        "evidence_context": evidence_payload,
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


def _lead_sort_key(lead: Lead) -> tuple[int, int, datetime, int]:
    bucket_rank = {
        "立即处理": 5,
        "今日内处理": 4,
        "可观察": 3,
        "信息不足": 2,
        "过期/低优先级": 1,
    }.get(_priority_bucket(lead), 0)
    return (bucket_rank, lead.intent_score or 0, lead.last_seen_at or lead.first_seen_at, lead.id or 0)


def _priority_bucket(lead: Lead) -> str:
    age_hours = _age_hours(lead.last_seen_at or lead.first_seen_at)
    if lead.status in {"handled", "ignored", "duplicate"}:
        return "过期/低优先级"
    if lead.status == "information_insufficient" or lead.information_completeness < 40:
        return "信息不足"
    if lead.status == "watch":
        return "可观察"
    if lead.intent_score >= 70 and age_hours <= 24:
        return "立即处理"
    if lead.intent_score >= 50 and age_hours <= 72:
        return "今日内处理"
    if lead.intent_score >= 40 and age_hours <= 168:
        return "可观察"
    return "过期/低优先级"


def _sla_due_label(lead: Lead) -> str:
    bucket = _priority_bucket(lead)
    return {
        "立即处理": "24小时内处理",
        "今日内处理": "今日内处理",
        "可观察": "7天内复看",
        "信息不足": "补充信息后再判断",
        "过期/低优先级": "低优先级",
    }[bucket]


def _freshness_label(value: datetime | None) -> str:
    if value is None:
        return "未知时间"
    hours = _age_hours(value)
    if hours < 1:
        return "刚刚"
    if hours < 24:
        return f"{hours}小时前"
    days = max(1, hours // 24)
    return f"{days}天前"


def _age_hours(value: datetime | None) -> int:
    if value is None:
        return 999999
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - current).total_seconds() // 3600))


def _source_role(source_entity_type: str | None) -> str:
    return {
        "comment": "评论者表达需求",
        "content": "发帖人表达需求",
    }.get(source_entity_type or "", "需求主体不确定")


def _why_recommended(lead: Lead, evidence: list[LeadEvidence]) -> list[str]:
    reasons: list[str] = []
    if evidence:
        source = "评论原文" if evidence[0].source_entity_type == "comment" else "原帖"
        reasons.append(f"{source}明确提到 {_short_reason(evidence[0].evidence_text)}")
    if lead.intent_score >= 70:
        reasons.append(f"意向分 {lead.intent_score}，属于高优先级线索")
    elif lead.intent_score >= 50:
        reasons.append(f"意向分 {lead.intent_score}，需要今日内判断")
    else:
        reasons.append(f"意向分 {lead.intent_score}，建议先观察")
    if lead.region_text:
        reasons.append(f"地区已知：{lead.region_text}")
    elif lead.missing_info_json:
        reasons.append(f"仍缺少：{'、'.join(str(item) for item in lead.missing_info_json)}")
    return reasons[:3]


def _short_reason(text: str) -> str:
    compact = " ".join(text.split())
    compact = compact.replace("孩子 ", "").replace("孩子", "")
    compact = compact.replace("，想找", "和")
    if len(compact) <= 28:
        return compact
    return compact[:28].rstrip() + "..."


def _business_summary(lead: Lead, evidence: list[LeadEvidence]) -> str:
    profile_name = lead.profile.display_name if lead.profile and lead.profile.display_name else "用户"
    product = lead.product or "课程"
    demand = _demand_label(lead.demand_type)
    if evidence and evidence[0].source_entity_type == "comment":
        return f"{profile_name}咨询 {product} {demand}，评论区表达备考需求"
    return f"{profile_name}咨询 {product} {demand}，原帖表达相关需求"


def _demand_label(value: str | None) -> str:
    return {
        "exam_retry": "二刷冲刺班",
        "price": "课程价格",
        "institution": "机构选择",
        "course": "课程安排",
        "improvement": "能力提升",
    }.get(value or "", "相关需求")


def _status_label(status_value: str) -> str:
    return {
        "new": "新发现",
        "needs_enrichment": "待判断",
        "qualified": "有效",
        "watch": "观察",
        "information_insufficient": "信息不足",
        "duplicate": "重复",
        "handled": "已联系",
        "ignored": "已忽略",
    }.get(status_value, status_value)


def _evidence_card(item: LeadEvidence) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_entity_type": item.source_entity_type,
        "source_entity_id": item.source_entity_id,
        "source_role": _source_role(item.source_entity_type),
        "content_id": item.content_id,
        "comment_id": item.comment_id,
        "evidence_text": item.evidence_text,
        "full_text": item.evidence_text,
        "demand_type": item.demand_type,
        "intent_stage": item.intent_stage,
        "score_contribution": item.score_contribution,
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
