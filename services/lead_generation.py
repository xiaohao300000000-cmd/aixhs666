from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from intelligence.demand_chain import DemandEventType, DemandEventStage, classify_demand_event
from intelligence.text_processing import normalize_text
from services.lead_intent import LeadEntryType, LeadIntentAction, LeadIntentDecision, classify_lead_intent
from storage.models import Comment, Content, EnrichmentTask, Lead, LeadEvidence, PublicProfile


MANUAL_LEAD_STATUSES = {"handled", "ignored", "qualified"}
PRODUCT_KEYWORDS = {
    "PET": ("PET", "pet", "小五", "小六"),
    "KET": ("KET", "ket", "小剑桥"),
}
REGION_KEYWORDS = ("福州", "厦门", "泉州", "上海", "北京", "广州", "深圳", "杭州", "南京", "苏州")


@dataclass(frozen=True, slots=True)
class LeadGenerationResult:
    leads_created: int = 0
    leads_updated: int = 0
    evidence_created: int = 0
    enrichment_tasks_created: int = 0
    qualified_leads: int = 0
    needs_enrichment_leads: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "leads_created": self.leads_created,
            "leads_updated": self.leads_updated,
            "evidence_created": self.evidence_created,
            "enrichment_tasks_created": self.enrichment_tasks_created,
            "qualified_leads": self.qualified_leads,
            "needs_enrichment_leads": self.needs_enrichment_leads,
        }


@dataclass(frozen=True, slots=True)
class LeadSourceRecord:
    profile_id: int
    platform: str
    source_entity_type: str
    source_entity_id: int
    content_id: int | None
    comment_id: int | None
    text: str
    occurred_at: datetime
    region_text: str | None


@dataclass(frozen=True, slots=True)
class LeadCandidate:
    profile_id: int
    platform: str
    product: str | None
    demand_type: str
    intent_stage: str
    intent_score: int
    information_completeness: int
    known_info: dict[str, Any]
    missing_info: list[str]
    recommended_next_step: str
    evidence: list[tuple[LeadSourceRecord, int, str, str]]


def generate_leads_from_history(session: Session) -> LeadGenerationResult:
    profile_ids = set(session.scalars(select(PublicProfile.id)).all())
    return generate_leads_for_profiles(session, profile_ids)


def rebuild_auto_leads_from_history(session: Session) -> LeadGenerationResult:
    auto_leads = session.scalars(select(Lead).where(Lead.status.not_in(MANUAL_LEAD_STATUSES))).all()
    for lead in auto_leads:
        session.delete(lead)
    session.flush()
    return generate_leads_from_history(session)


def generate_leads_for_profiles(session: Session, profile_ids: set[int]) -> LeadGenerationResult:
    if not profile_ids:
        return LeadGenerationResult()
    profiles = {
        profile.id: profile
        for profile in session.scalars(select(PublicProfile).where(PublicProfile.id.in_(profile_ids))).all()
        if profile.id is not None
    }
    records_by_profile = _records_by_profile(session, set(profiles))
    counts = {
        "leads_created": 0,
        "leads_updated": 0,
        "evidence_created": 0,
        "enrichment_tasks_created": 0,
        "qualified_leads": 0,
        "needs_enrichment_leads": 0,
    }
    for profile_id, records in records_by_profile.items():
        candidate = _build_candidate(profiles[profile_id], records)
        if candidate is None:
            continue
        lead, created = _upsert_lead(session, profile=profiles[profile_id], candidate=candidate)
        counts["leads_created" if created else "leads_updated"] += 1 if created or lead.status not in MANUAL_LEAD_STATUSES else 0
        counts["evidence_created"] += _upsert_evidence(session, lead=lead, candidate=candidate)
        counts["enrichment_tasks_created"] += _upsert_enrichment_tasks(session, lead=lead, missing_info=candidate.missing_info)
        if lead.status == "qualified":
            counts["qualified_leads"] += 1
        elif lead.status == "needs_enrichment":
            counts["needs_enrichment_leads"] += 1
    session.flush()
    return LeadGenerationResult(**counts)


def _records_by_profile(session: Session, profile_ids: set[int]) -> dict[int, list[LeadSourceRecord]]:
    records: dict[int, list[LeadSourceRecord]] = {profile_id: [] for profile_id in profile_ids}
    contents = session.scalars(select(Content).where(Content.author_profile_id.in_(profile_ids)).order_by(Content.id.asc())).all()
    for content in contents:
        if content.author_profile_id is None or content.id is None:
            continue
        text = " ".join(part for part in (content.title, content.body_text) if part)
        if text:
            records[content.author_profile_id].append(
                LeadSourceRecord(
                    profile_id=content.author_profile_id,
                    platform=content.platform,
                    source_entity_type="content",
                    source_entity_id=content.id,
                    content_id=content.id,
                    comment_id=None,
                    text=text,
                    occurred_at=content.published_at or content.first_seen_at,
                    region_text=content.region_text,
                )
            )
    comments = session.scalars(select(Comment).where(Comment.author_profile_id.in_(profile_ids)).order_by(Comment.id.asc())).all()
    for comment in comments:
        if comment.author_profile_id is None or comment.id is None:
            continue
        if comment.body_text:
            records[comment.author_profile_id].append(
                LeadSourceRecord(
                    profile_id=comment.author_profile_id,
                    platform=comment.platform,
                    source_entity_type="comment",
                    source_entity_id=comment.id,
                    content_id=comment.content_id,
                    comment_id=comment.id,
                    text=comment.body_text,
                    occurred_at=comment.published_at or comment.first_seen_at,
                    region_text=None,
                )
            )
    return records


def _build_candidate(profile: PublicProfile, records: list[LeadSourceRecord]) -> LeadCandidate | None:
    evidence: list[tuple[LeadSourceRecord, int, str, str]] = []
    combined_text = " ".join(record.text for record in records)
    decisions: list[LeadIntentDecision] = []
    product = _detect_product(combined_text)
    if product is None:
        return None
    for record in records:
        decision = classify_lead_intent(
            record.text,
            source_entity_type=record.source_entity_type,
            context_text=combined_text,
        )
        if decision.entry_type == LeadEntryType.SKIP:
            continue
        decisions.append(decision)
        event_type = _classify_lead_event(record.text, source_entity_type=record.source_entity_type)
        if event_type == DemandEventType.UNKNOWN:
            demand_type, intent_stage = _fallback_demand_from_intent(decision)
        else:
            demand_type = event_type.value
            intent_stage = _stage_for_event(event_type).value
        evidence.append((record, _score_record(record.text, event_type), demand_type, intent_stage))
    if not evidence:
        return None

    best = max(evidence, key=lambda item: item[1])
    best_decision = decisions[evidence.index(best)]
    region = profile.region_text or _first_region(record.region_text for record in records) or _detect_region(combined_text)
    demand_type = _best_demand_type([item[2] for item in evidence])
    intent_stage = _best_stage([item[3] for item in evidence])
    intent_score = min(100, max(item[1] for item in evidence) + max(0, len(evidence) - 1) * 5)
    known_info = {
        "platform": profile.platform,
        "platform_user_id": profile.platform_user_id,
        "display_name": profile.display_name,
        "profile_url": profile.profile_url,
        "region": region,
        "product": product,
        "demand_type": demand_type,
        "intent_stage": intent_stage,
        "evidence_count": len(evidence),
        "public_contact": profile.public_contact_text,
        "human_need": best_decision.human_need,
        "recommendation_reason": best_decision.recommendation_reason,
        "suggested_next_step": best_decision.suggested_next_step,
    }
    missing_info = _missing_info(known_info)
    completeness = _completeness(known_info)
    return LeadCandidate(
        profile_id=profile.id,
        platform=profile.platform,
        product=product,
        demand_type=demand_type,
        intent_stage=intent_stage,
        intent_score=intent_score,
        information_completeness=completeness,
        known_info={key: value for key, value in known_info.items() if value not in (None, "")},
        missing_info=missing_info,
        recommended_next_step=best_decision.suggested_next_step or _recommended_next_step(missing_info, intent_score, best[3]),
        evidence=evidence,
    )


def _upsert_lead(session: Session, *, profile: PublicProfile, candidate: LeadCandidate) -> tuple[Lead, bool]:
    lead = session.scalar(
        select(Lead).where(Lead.platform == candidate.platform, Lead.public_profile_id == candidate.profile_id)
    )
    created = lead is None
    now = _utc_now()
    if lead is None:
        lead = Lead(platform=candidate.platform, public_profile_id=candidate.profile_id, first_seen_at=now)
        session.add(lead)
        session.flush()
    lead.region_text = candidate.known_info.get("region") or profile.region_text
    lead.demand_type = candidate.demand_type
    lead.product = candidate.product
    lead.intent_stage = candidate.intent_stage
    lead.intent_score = candidate.intent_score
    lead.information_completeness = candidate.information_completeness
    lead.known_info_json = candidate.known_info
    lead.missing_info_json = candidate.missing_info
    lead.recommended_next_step = candidate.recommended_next_step
    lead.last_seen_at = now
    lead.updated_at = now
    if lead.status not in MANUAL_LEAD_STATUSES:
        lead.status = _automatic_status(candidate)
    return lead, created


def _upsert_evidence(session: Session, *, lead: Lead, candidate: LeadCandidate) -> int:
    created = 0
    for record, score, demand_type, intent_stage in candidate.evidence:
        existing = session.scalar(
            select(LeadEvidence).where(
                LeadEvidence.lead_id == lead.id,
                LeadEvidence.source_entity_type == record.source_entity_type,
                LeadEvidence.source_entity_id == record.source_entity_id,
            )
        )
        if existing is not None:
            continue
        session.add(
            LeadEvidence(
                lead_id=lead.id,
                source_entity_type=record.source_entity_type,
                source_entity_id=record.source_entity_id,
                content_id=record.content_id,
                comment_id=record.comment_id,
                evidence_text=record.text,
                demand_type=demand_type,
                intent_stage=intent_stage,
                score_contribution=score,
            )
        )
        created += 1
    return created


def _upsert_enrichment_tasks(session: Session, *, lead: Lead, missing_info: list[str]) -> int:
    created = 0
    for item in missing_info:
        task_type = f"fill_{item}"
        existing = session.scalar(
            select(EnrichmentTask).where(EnrichmentTask.lead_id == lead.id, EnrichmentTask.task_type == task_type)
        )
        if existing is not None:
            continue
        session.add(EnrichmentTask(lead_id=lead.id, task_type=task_type, status="pending", reason=_missing_reason(item)))
        created += 1
    return created


def _detect_product(text: str) -> str | None:
    normalized = normalize_text(text)
    for product, keywords in PRODUCT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return product
    return None


def _detect_region(text: str) -> str | None:
    return next((region for region in REGION_KEYWORDS if region in text), None)


def _first_region(values: Any) -> str | None:
    return next((value for value in values if value), None)


def _stage_for_event(event_type: DemandEventType) -> DemandEventStage:
    if event_type == DemandEventType.PRICE or event_type == DemandEventType.TRIAL:
        return DemandEventStage.ACTION_READY
    if event_type == DemandEventType.COMPARISON:
        return DemandEventStage.EVALUATING
    if event_type == DemandEventType.EXAM_RETRY:
        return DemandEventStage.RECOVERY
    if event_type == DemandEventType.PLANNING:
        return DemandEventStage.PLANNING
    if event_type == DemandEventType.COMPLAINT:
        return DemandEventStage.DISSATISFIED
    return DemandEventStage.EXPLORING


def _classify_lead_event(text: str, *, source_entity_type: str) -> DemandEventType:
    normalized = normalize_text(text)
    if not _has_lead_intent(normalized, source_entity_type=source_entity_type):
        return DemandEventType.UNKNOWN
    if any(word in normalized for word in ("二刷", "再考", "重考", "压线", "没过", "没通过", "刷分")):
        return DemandEventType.EXAM_RETRY
    return classify_demand_event(text)


def _has_lead_intent(normalized_text: str, *, source_entity_type: str) -> bool:
    strong_content_intent_words = (
        "求推荐",
        "求问",
        "想问",
        "请问",
        "想找",
        "哪家",
        "哪个好",
        "怎么选",
        "有没有",
        "价格多少",
        "多少钱",
        "试听",
        "体验课",
    )
    content_problem_words = (
        "二刷",
        "再考",
        "重考",
        "压线",
        "没过",
        "没通过",
        "来得及",
    )
    if source_entity_type == "content":
        if _is_provider_or_guide_content(normalized_text):
            return False
        return any(word in normalized_text for word in (*strong_content_intent_words, *content_problem_words))
    if _is_provider_comment(normalized_text) or _is_promo_comment(normalized_text) or _is_no_need_comment(normalized_text):
        return False
    comment_intent_words = (
        *strong_content_intent_words,
        *content_problem_words,
        "价格",
        "报课",
        "报班",
        "课程",
        "线上带",
        "带PET",
        "带KET",
        "机构",
    )
    return any(
        word in normalized_text
        for word in comment_intent_words
    )


def _is_provider_or_guide_content(normalized_text: str) -> bool:
    return any(
        word in normalized_text
        for word in (
            "教了",
            "老师",
            "佬师",
            "机构问我",
            "托管机构",
            "能不能教",
            "小班教学",
            "教学大纲",
            "备考攻略",
            "备考经验",
            "总结出来",
            "十条建议",
            "学习顺序",
            "刷题顺序",
            "扣分点",
            "普及一下",
            "分享",
            "整理了",
            "给大家参考",
        )
    )


def _is_provider_comment(normalized_text: str) -> bool:
    return any(
        word in normalized_text
        for word in (
            "独立老师",
            "我是老师",
            "我是一个老师",
            "生源",
            "我半道接手",
            "我一直建议",
            "家长逼着",
            "我带KET",
            "我带PET",
        )
    )


def _is_promo_comment(normalized_text: str) -> bool:
    return any(
        word in normalized_text
        for word in (
            "专业机构",
            "靠谱机构",
            "同团队",
            "系统规划",
            "稳步规划",
            "少走太多弯路",
            "上岸",
            "培训不上",
            "机构帮孩子",
        )
    )


def _is_no_need_comment(normalized_text: str) -> bool:
    return any(
        word in normalized_text
        for word in (
            "没有报班",
            "没报英文班",
            "不为考试",
            "不为考级",
            "无所谓",
            "节约钱和时间",
        )
    )


def _score_record(text: str, event_type: DemandEventType) -> int:
    base = {
        DemandEventType.PRICE: 78,
        DemandEventType.TRIAL: 82,
        DemandEventType.COMPARISON: 68,
        DemandEventType.EXAM_RETRY: 72,
        DemandEventType.PLANNING: 60,
        DemandEventType.COMPLAINT: 64,
        DemandEventType.QUESTION: 52,
        DemandEventType.UNKNOWN: 0,
    }[event_type]
    normalized = normalize_text(text)
    if any(word in normalized for word in ("求推荐", "哪家", "机构", "冲刺班")):
        base += 8
    if any(word in normalized for word in ("试听", "价格", "多少钱")):
        base += 10
    return min(base, 100)


def _best_demand_type(values: list[str]) -> str:
    for value in ("exam_retry", "trial", "price", "comparison", "complaint", "planning", "question"):
        if value in values:
            return value
    return values[0]


def _best_stage(values: list[str]) -> str:
    for value in ("action_ready", "recovery", "evaluating", "dissatisfied", "planning", "exploring"):
        if value in values:
            return value
    return values[0]


def _fallback_demand_from_intent(decision: LeadIntentDecision) -> tuple[str, str]:
    for action in decision.actions:
        mapped = _ACTION_TO_DEMAND.get(action)
        if mapped is not None:
            return mapped
    return DemandEventType.QUESTION.value, DemandEventStage.EXPLORING.value


_ACTION_TO_DEMAND: dict[LeadIntentAction, tuple[str, str]] = {
    LeadIntentAction.PRICE: (DemandEventType.PRICE.value, DemandEventStage.ACTION_READY.value),
    LeadIntentAction.TRIAL: (DemandEventType.TRIAL.value, DemandEventStage.ACTION_READY.value),
    LeadIntentAction.INSTITUTION: (DemandEventType.COMPARISON.value, DemandEventStage.EVALUATING.value),
    LeadIntentAction.COMPARISON: (DemandEventType.COMPARISON.value, DemandEventStage.EVALUATING.value),
    LeadIntentAction.EXAM_RETRY: (DemandEventType.EXAM_RETRY.value, DemandEventStage.RECOVERY.value),
    LeadIntentAction.COURSE: (DemandEventType.PLANNING.value, DemandEventStage.PLANNING.value),
    LeadIntentAction.ENROLLMENT: (DemandEventType.PLANNING.value, DemandEventStage.PLANNING.value),
    LeadIntentAction.IMPROVEMENT: (DemandEventType.QUESTION.value, DemandEventStage.EXPLORING.value),
}


def _missing_info(known_info: dict[str, Any]) -> list[str]:
    missing = []
    if not known_info.get("region"):
        missing.append("region")
    if not known_info.get("public_contact"):
        missing.append("contact")
    if not known_info.get("product"):
        missing.append("product")
    if not known_info.get("intent_stage"):
        missing.append("intent_stage")
    return missing


def _completeness(known_info: dict[str, Any]) -> int:
    keys = ("region", "product", "demand_type", "intent_stage", "public_contact")
    present = sum(1 for key in keys if known_info.get(key))
    return int(present / len(keys) * 100)


def _automatic_status(candidate: LeadCandidate) -> str:
    if candidate.intent_score >= 80 and candidate.information_completeness >= 80:
        return "qualified"
    if candidate.missing_info:
        return "needs_enrichment"
    return "new"


def _recommended_next_step(missing_info: list[str], intent_score: int, stage: str) -> str:
    if "contact" in missing_info:
        return "补充公开联系方式后人工判断是否可跟进"
    if "region" in missing_info:
        return "补充地区信息，确认是否属于可服务范围"
    if intent_score >= 80 or stage == DemandEventStage.ACTION_READY.value:
        return "查看证据原文，准备人工跟进"
    return "继续观察该用户后续公开表达"


def _missing_reason(item: str) -> str:
    return {
        "region": "缺少地区，无法判断服务范围",
        "contact": "缺少公开联系方式，无法直接跟进",
        "product": "缺少明确课程或产品",
        "intent_stage": "缺少明确意向阶段",
    }.get(item, f"缺少{item}")


def _utc_now() -> datetime:
    return datetime.now(UTC)
