from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from services.pipeline_runner import PipelineRunner
from storage.models import Lead, Query


STATUS_LABELS = {
    "new": "新发现",
    "needs_enrichment": "待确认",
    "qualified": "可跟进",
    "handled": "已跟进",
    "ignored": "不合适",
}


@dataclass(frozen=True, slots=True)
class AgentLeadRow:
    lead_id: int
    customer: str
    need: str
    product: str
    intent_level: str
    reason: str
    next_step: str
    status_label: str
    source_url: str
    discovered_at: str


def select_queries_for_agent(session: Session, *, limit: int = 3) -> list[int]:
    rows = session.scalars(
        select(Query)
        .where(Query.status == "active")
        .order_by(Query.priority.desc(), Query.last_run_at.asc().nullsfirst(), Query.id.asc())
        .limit(limit)
    ).all()
    return [query.id for query in rows if query.id is not None]


def rank_leads_for_workbench(session: Session, *, limit: int = 50) -> list[AgentLeadRow]:
    leads = session.scalars(
        select(Lead)
        .where(Lead.status.in_(("new", "needs_enrichment", "qualified")))
        .order_by(Lead.intent_score.desc(), Lead.last_seen_at.desc(), Lead.id.desc())
        .limit(limit)
    ).all()
    return [_lead_to_row(lead) for lead in leads if lead.id is not None]


def run_agent_cycle(
    session_factory: sessionmaker[Session],
    runner: PipelineRunner,
    *,
    query_limit: int = 3,
    collection_limit: int = 20,
) -> dict[str, Any]:
    with session_factory() as session:
        query_ids = select_queries_for_agent(session, limit=query_limit)
    result = None
    if query_ids:
        result = runner.run_cycle(query_ids=query_ids, collection_limit=collection_limit, requested_by="agent")
    with session_factory() as session:
        rows = rank_leads_for_workbench(session)
    return {"pipeline": result, "workbench_rows": [asdict(row) for row in rows]}


def _lead_to_row(lead: Lead) -> AgentLeadRow:
    profile = lead.profile
    known = lead.known_info_json or {}
    customer = profile.display_name if profile and profile.display_name else (profile.platform_user_id if profile else f"lead-{lead.id}")
    need = str(known.get("human_need") or _fallback_need(lead))
    reason = str(known.get("recommendation_reason") or "系统根据公开内容判断有跟进价值")
    return AgentLeadRow(
        lead_id=lead.id,
        customer=customer,
        need=need,
        product=lead.product or "未知",
        intent_level=_intent_level(lead.intent_score),
        reason=reason,
        next_step=lead.recommended_next_step or "先人工确认需求是否真实",
        status_label=STATUS_LABELS.get(lead.status, "待确认"),
        source_url=profile.profile_url if profile and profile.profile_url else "",
        discovered_at=lead.first_seen_at.isoformat() if lead.first_seen_at else "",
    )


def _fallback_need(lead: Lead) -> str:
    product = lead.product or "课程"
    if lead.demand_type == "exam_retry":
        return f"家长可能需要{product}二刷或冲刺帮助"
    return f"家长可能在咨询{product}相关问题"


def _intent_level(score: int) -> str:
    if score >= 80:
        return "高"
    if score >= 60:
        return "中"
    return "低"
