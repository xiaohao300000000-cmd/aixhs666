from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from services.lead_intent import LeadEntryType, LeadIntentAction, LeadIntentDecision, classify_lead_intent
from storage.models import Comment, Content, PublicProfile


@dataclass(frozen=True, slots=True)
class AIWorkbenchExport:
    customer_rows: list[dict[str, Any]]
    evidence_rows: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class _EvidenceCandidate:
    profile_key: str
    customer_name: str
    platform_user_id: str
    evidence_type: str
    raw_text: str
    decision: LeadIntentDecision
    source_link: str
    published_at: datetime | None
    content_id: str
    comment_id: str


ACTION_LABELS = {
    LeadIntentAction.COURSE: "课程安排",
    LeadIntentAction.INSTITUTION: "机构选择",
    LeadIntentAction.PRICE: "课程价格",
    LeadIntentAction.TRIAL: "试听体验",
    LeadIntentAction.ENROLLMENT: "报名计划",
    LeadIntentAction.EXAM_RETRY: "补考提升",
    LeadIntentAction.COMPARISON: "方案对比",
    LeadIntentAction.IMPROVEMENT: "能力提升",
}

RAW_INTENT_WORDS = (
    "多少钱",
    "价格多少",
    "费用多少",
    "收费多少",
    "课时费多少",
    "试听",
    "体验课",
    "报班",
    "要不要报",
    "需要报",
    "推荐机构",
    "机构推荐",
    "哪家机构",
    "线下机构",
    "线上机构",
    "推荐吗",
    "求推荐",
    "想找",
    "找老师",
    "可以教",
    "想让",
    "想给",
    "线上带",
    "线下课",
    "冲刺班",
    "一对一",
    "没过",
    "压线",
    "二刷",
    "重考",
    "再考",
    "哪个好",
    "怎么选",
    "纠结",
    "怎么提高",
    "怎么提升",
    "阅读弱",
    "听力弱",
    "写作弱",
    "跟不上",
)
OUT_OF_SCOPE_RAW_WORDS = ("PTE", "雅思", "托福", "考研", "成人英语", "四六级")
DIRECT_CUSTOMER_CONTENT_WORDS = (
    "请问",
    "求问",
    "求推荐",
    "推荐吗",
    "哪家",
    "有没有",
    "怎么选",
    "多少钱",
    "价格",
    "试听",
    "体验课",
    "想找",
    "想让",
    "想给",
    "要不要报",
    "需要报",
    "纠结",
    "没过",
    "压线",
    "二刷",
    "重考",
    "怎么提高",
    "怎么提升",
    "线上还是线下",
)


def build_ai_workbench_export(session: Session) -> AIWorkbenchExport:
    """Build Feishu Base rows after intent filtering existing crawled data."""
    evidence = _collect_intent_evidence(session)
    evidence.sort(key=lambda item: (item.profile_key, _datetime_sort_key(item.published_at), item.evidence_type))

    grouped: dict[str, list[_EvidenceCandidate]] = {}
    for item in evidence:
        grouped.setdefault(item.profile_key, []).append(item)

    customer_rows = [_build_customer_row(items) for items in grouped.values()]
    customer_rows.sort(
        key=lambda row: (
            _intent_rank(row["意向程度"]),
            int(row["证据数量"]),
            row["抓取时间"] or "",
        ),
        reverse=True,
    )
    evidence_rows = [_build_evidence_row(item) for item in evidence]
    return AIWorkbenchExport(customer_rows=customer_rows, evidence_rows=evidence_rows)


def _collect_intent_evidence(session: Session) -> list[_EvidenceCandidate]:
    candidates: list[_EvidenceCandidate] = []
    contents = session.scalars(select(Content).options(joinedload(Content.author_profile))).all()
    comments = session.scalars(
        select(Comment).options(joinedload(Comment.author_profile), joinedload(Comment.content))
    ).all()

    for content in contents:
        raw_text = _join_text(content.title, content.body_text)
        if not raw_text:
            continue
        if _has_out_of_scope_noise(raw_text):
            continue
        if not _has_raw_intent_signal(raw_text) or not _looks_like_direct_customer_content(raw_text):
            continue
        decision = classify_lead_intent(raw_text, source_entity_type="content")
        if decision.entry_type not in (LeadEntryType.PUSH, LeadEntryType.CONFIRM):
            continue
        profile = content.author_profile
        candidates.append(
            _EvidenceCandidate(
                profile_key=_profile_key(profile, fallback=f"content:{content.id}"),
                customer_name=_customer_name(profile),
                platform_user_id=_platform_user_id(profile, fallback=f"content:{content.id}"),
                evidence_type="content",
                raw_text=raw_text,
                decision=decision,
                source_link=content.url or _profile_url(profile),
                published_at=content.published_at,
                content_id=str(content.id),
                comment_id="",
            )
        )

    for comment in comments:
        raw_text = comment.body_text or ""
        if not raw_text.strip():
            continue
        if _has_out_of_scope_noise(raw_text):
            continue
        if not _has_raw_intent_signal(raw_text):
            continue
        parent_content = comment.content
        context_text = _join_text(parent_content.title if parent_content else None, parent_content.body_text if parent_content else None)
        decision = classify_lead_intent(raw_text, source_entity_type="comment", context_text=context_text)
        if decision.entry_type not in (LeadEntryType.PUSH, LeadEntryType.CONFIRM):
            continue
        profile = comment.author_profile
        candidates.append(
            _EvidenceCandidate(
                profile_key=_profile_key(profile, fallback=f"comment:{comment.id}"),
                customer_name=_customer_name(profile),
                platform_user_id=_platform_user_id(profile, fallback=f"comment:{comment.id}"),
                evidence_type="comment",
                raw_text=raw_text,
                decision=decision,
                source_link=(parent_content.url if parent_content else "") or _profile_url(profile),
                published_at=comment.published_at,
                content_id=str(parent_content.id) if parent_content else "",
                comment_id=str(comment.id),
            )
        )

    return candidates


def _build_customer_row(items: list[_EvidenceCandidate]) -> dict[str, Any]:
    best = max(items, key=lambda item: (_decision_rank(item.decision), _datetime_sort_key(item.published_at)))
    all_text = "\n".join(item.raw_text for item in items)
    reasons = _unique_nonempty(item.decision.recommendation_reason for item in items)
    next_steps = _unique_nonempty(item.decision.suggested_next_step for item in items)
    latest = max((item.published_at for item in items if item.published_at), default=None)
    return {
        "客户": best.customer_name,
        "平台用户ID": best.platform_user_id,
        "意向程度": _intent_level(items),
        "需求摘要": _demand_summary(best),
        "课程/考试": _detect_product(all_text),
        "为什么推荐": "；".join(reasons),
        "下一步": next_steps[0] if next_steps else "",
        "状态": "待确认",
        "证据数量": len(items),
        "来源链接": best.source_link,
        "抓取时间": _format_datetime(latest),
    }


def _build_evidence_row(item: _EvidenceCandidate) -> dict[str, Any]:
    return {
        "证据标题": f"{item.customer_name}-{item.evidence_type}-{item.content_id or item.comment_id}",
        "平台用户ID": item.platform_user_id,
        "客户": item.customer_name,
        "证据类型": item.evidence_type,
        "AI判断": item.decision.entry_type.value,
        "置信度": item.decision.confidence,
        "动作": "、".join(ACTION_LABELS[action] for action in item.decision.actions),
        "为什么推荐": item.decision.recommendation_reason,
        "抓取原文": _truncate(item.raw_text, 1500),
        "来源链接": item.source_link,
        "发布时间": _format_datetime(item.published_at),
        "内容ID": item.content_id,
        "评论ID": item.comment_id,
    }


def _demand_summary(item: _EvidenceCandidate) -> str:
    need = item.decision.human_need or "家长有KET/PET相关咨询"
    return _truncate(f"{need}。原文：{item.raw_text}", 500)


def _intent_level(items: list[_EvidenceCandidate]) -> str:
    if any(item.decision.entry_type == LeadEntryType.PUSH or item.decision.confidence == "high" for item in items):
        return "高"
    if any(item.decision.entry_type == LeadEntryType.CONFIRM or item.decision.confidence == "medium" for item in items):
        return "中"
    return "低"


def _decision_rank(decision: LeadIntentDecision) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(decision.confidence, 0)


def _intent_rank(level: str) -> int:
    return {"高": 3, "中": 2, "低": 1}.get(level, 0)


def _detect_product(text: str) -> str:
    products: list[str] = []
    normalized = text.upper()
    if "KET" in normalized:
        products.append("KET")
    if "PET" in normalized:
        products.append("PET")
    if "小剑桥" in text:
        products.append("小剑桥")
    return "、".join(products)


def _profile_key(profile: PublicProfile | None, *, fallback: str) -> str:
    if profile:
        return f"{profile.platform}:{profile.platform_user_id}"
    return fallback


def _customer_name(profile: PublicProfile | None) -> str:
    if profile and profile.display_name:
        return profile.display_name
    return "未知用户"


def _platform_user_id(profile: PublicProfile | None, *, fallback: str) -> str:
    if profile:
        return profile.platform_user_id
    return fallback


def _profile_url(profile: PublicProfile | None) -> str:
    return profile.profile_url if profile and profile.profile_url else ""


def _join_text(*parts: str | None) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _has_raw_intent_signal(text: str) -> bool:
    return any(word in text for word in RAW_INTENT_WORDS)


def _has_out_of_scope_noise(text: str) -> bool:
    normalized = text.upper()
    return any(word in normalized for word in OUT_OF_SCOPE_RAW_WORDS)


def _looks_like_direct_customer_content(text: str) -> bool:
    return "?" in text or "？" in text or any(word in text for word in DIRECT_CUSTOMER_CONTENT_WORDS)


def _unique_nonempty(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _datetime_sort_key(value: datetime | None) -> str:
    return _format_datetime(value)


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
