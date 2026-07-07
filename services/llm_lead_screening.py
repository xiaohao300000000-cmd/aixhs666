from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from intelligence.text_processing import normalize_text
from services.lead_screening_flow import LLM_DONE, PENDING_LLM, SCREENING
from storage.models import Comment, Content, Lead, LeadEvidence, LeadScreeningResult, PublicProfile


REVIEW_CONFIDENCE_THRESHOLD = 0.65
HIGH_CONFIDENCE_THRESHOLD = 0.75
DEFAULT_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_API_URL = "https://api.deepseek.com"
DEFAULT_QUALIFICATION_CAMPAIGN_CONFIG = (
    Path(__file__).resolve().parents[1] / "configs" / "campaigns" / "education_fuzhou_offline.json"
)
JUNK_TEXTS = {"哈哈", "哈哈哈", "蹲", "蹲蹲", "dd", "1", "mark", "收藏", "路过", "看看"}
SPAM_WORDS = ("私信领取", "加我领取", "资料包", "求资料", "求分享", "无偿分享", "领资料")
REGION_KEYWORDS = ("福州", "厦门", "泉州", "上海", "北京", "广州", "深圳", "杭州", "南京", "苏州")
PRODUCT_KEYWORDS = {
    "PET": ("PET", "pet", "小五", "小六"),
    "KET": ("KET", "ket", "小剑桥"),
}


@dataclass(frozen=True, slots=True)
class LeadScreeningContext:
    source_entity_type: str
    source_entity_id: int
    platform: str
    content_id: int | None
    comment_id: int | None
    public_profile_id: int | None
    post_title: str
    post_body: str
    current_comment: str
    parent_comment: str
    author_display_name: str
    profile_region: str
    profile_bio: str
    source_url: str = ""

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "source_entity_type": self.source_entity_type,
            "source_entity_id": self.source_entity_id,
            "post_title": self.post_title,
            "post_body": self.post_body,
            "current_comment": self.current_comment,
            "parent_comment": self.parent_comment,
            "author_display_name": self.author_display_name,
            "profile_region": self.profile_region,
            "profile_bio": self.profile_bio,
            "source_url": self.source_url,
        }


@dataclass(frozen=True, slots=True)
class LLMLeadScreeningDecision:
    valuable: bool
    demand_type: str
    intent_strength: str
    judgment_evidence: tuple[str, ...]
    confidence: float
    reason: str
    review_required: bool = False
    raw_json: dict[str, Any] | None = None
    model_name: str | None = None


class LeadScreeningClient(Protocol):
    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        """Return the LLM decision for one post or comment context."""


@dataclass(frozen=True, slots=True)
class LeadScreeningRunResult:
    candidates: int = 0
    filtered: int = 0
    skipped_existing: int = 0
    screened: int = 0
    accepted: int = 0
    rejected: int = 0
    needs_review: int = 0
    leads_created: int = 0
    leads_updated: int = 0
    evidence_created: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "candidates": self.candidates,
            "filtered": self.filtered,
            "skipped_existing": self.skipped_existing,
            "screened": self.screened,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "needs_review": self.needs_review,
            "leads_created": self.leads_created,
            "leads_updated": self.leads_updated,
            "evidence_created": self.evidence_created,
            "failed": self.failed,
        }


class OpenAICompatibleLeadScreeningClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        api_url: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("LLM_LEAD_SCREENING_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.model = model or os.getenv("LLM_LEAD_SCREENING_MODEL", DEFAULT_MODEL_NAME)
        self.api_url = _chat_completions_url(api_url or os.getenv("LLM_LEAD_SCREENING_API_URL", DEFAULT_API_URL))
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise RuntimeError("LLM_LEAD_SCREENING_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY is required")

    def screen(self, context: LeadScreeningContext) -> LLMLeadScreeningDecision:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是教育获客线索筛选助手。只输出 JSON，不要输出 Markdown。"
                        "判断对象是小红书公开帖子或评论。"
                        "规则过滤只做基础清洗，你必须根据上下文判断是否值得人工跟进。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": (
                                "判断这条内容是否是有价值客户线索。输出字段："
                                "valuable(boolean), demand_type(string), intent_strength(high/medium/low), "
                                "judgment_evidence(array of string), confidence(0-1), reason(string), "
                                "review_required(boolean)。不确定时 review_required=true。"
                            ),
                            "context": context.to_prompt_payload(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM request failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        content = payload["choices"][0]["message"]["content"]
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            content_preview = str(content)[:200]
            raise RuntimeError(f"LLM returned invalid JSON content: {content_preview!r}") from exc
        return _decision_from_json(raw, model_name=self.model)


def run_llm_lead_screening(
    session: Session,
    *,
    client: LeadScreeningClient | None = None,
    source_entity_types: set[str] | None = None,
    source_entity_ids: set[int] | None = None,
    limit: int | None = None,
    reprocess: bool = False,
) -> LeadScreeningRunResult:
    client = client or OpenAICompatibleLeadScreeningClient()
    source_entity_types = source_entity_types or {"content", "comment"}
    counts = {key: 0 for key in LeadScreeningRunResult().to_dict()}
    seen_texts: set[str] = set()
    attempted = 0

    for context in _iter_contexts(
        session,
        source_entity_types=source_entity_types,
        source_entity_ids=source_entity_ids,
        limit=None,
    ):
        counts["candidates"] += 1
        normalized_source = _normalized_source_text(context)
        if _is_garbage_text(normalized_source) or normalized_source in seen_texts:
            counts["filtered"] += 1
            continue
        seen_texts.add(normalized_source)
        existing = _existing_screening(session, context)
        if not reprocess and existing is not None and existing.workflow_status != PENDING_LLM:
            counts["skipped_existing"] += 1
            continue
        screening = _ensure_pending_screening(session, context, existing=existing)
        claimed = _claim_llm_screening(session, screening)
        if claimed is None:
            counts["skipped_existing"] += 1
            continue

        try:
            decision = client.screen(context)
        except Exception as exc:  # noqa: BLE001 - keep failed LLM calls visible in DB.
            _save_failed_screening(session, context, error_message=str(exc), screening=claimed)
            counts["failed"] += 1
            attempted += 1
            if limit is not None and attempted >= limit:
                break
            continue

        screening = _save_screening_result(session, context, decision, screening=claimed)
        _apply_default_qualification(session, screening)
        counts["screened"] += 1
        counts[screening.review_status] += 1
        if screening.review_status in {"accepted", "needs_review"} and context.public_profile_id is not None:
            lead, created = _upsert_lead_from_screening(session, context, decision, screening.review_status)
            counts["leads_created" if created else "leads_updated"] += 1
            counts["evidence_created"] += _upsert_evidence(session, lead=lead, context=context, decision=decision)
        attempted += 1
        if limit is not None and attempted >= limit:
            break

    session.flush()
    return LeadScreeningRunResult(**counts)


def _iter_contexts(
    session: Session,
    *,
    source_entity_types: set[str],
    source_entity_ids: set[int] | None,
    limit: int | None,
) -> Iterable[LeadScreeningContext]:
    emitted = 0
    if "content" in source_entity_types:
        statement = select(Content).options(joinedload(Content.author_profile)).order_by(Content.id.asc())
        if source_entity_ids:
            statement = statement.where(Content.id.in_(source_entity_ids))
        for content in session.scalars(statement).all():
            if content.id is None:
                continue
            yield _content_context(content)
            emitted += 1
            if limit is not None and emitted >= limit:
                return

    if "comment" in source_entity_types:
        statement = (
            select(Comment)
            .options(
                joinedload(Comment.content),
                joinedload(Comment.parent_comment),
                joinedload(Comment.author_profile),
            )
            .order_by(Comment.id.asc())
        )
        if source_entity_ids:
            statement = statement.where(Comment.id.in_(source_entity_ids))
        for comment in session.scalars(statement).all():
            if comment.id is None:
                continue
            yield _comment_context(comment)
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def _content_context(content: Content) -> LeadScreeningContext:
    profile = content.author_profile
    return LeadScreeningContext(
        source_entity_type="content",
        source_entity_id=int(content.id),
        platform=content.platform,
        content_id=content.id,
        comment_id=None,
        public_profile_id=content.author_profile_id,
        post_title=content.title or "",
        post_body=content.body_text or "",
        current_comment="",
        parent_comment="",
        author_display_name=(profile.display_name if profile else "") or "",
        profile_region=(profile.region_text if profile else "") or "",
        profile_bio=(profile.bio if profile else "") or "",
        source_url=content.url or "",
    )


def _comment_context(comment: Comment) -> LeadScreeningContext:
    profile = comment.author_profile
    content = comment.content
    parent = comment.parent_comment
    return LeadScreeningContext(
        source_entity_type="comment",
        source_entity_id=int(comment.id),
        platform=comment.platform,
        content_id=comment.content_id,
        comment_id=comment.id,
        public_profile_id=comment.author_profile_id,
        post_title=(content.title if content else "") or "",
        post_body=(content.body_text if content else "") or "",
        current_comment=comment.body_text or "",
        parent_comment=(parent.body_text if parent else "") or "",
        author_display_name=(profile.display_name if profile else "") or "",
        profile_region=(profile.region_text if profile else "") or "",
        profile_bio=(profile.bio if profile else "") or "",
        source_url=(content.url if content else "") or "",
    )


def _decision_from_json(raw: dict[str, Any], *, model_name: str) -> LLMLeadScreeningDecision:
    evidence = raw.get("judgment_evidence") or raw.get("判断证据") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    confidence = _confidence_to_float(raw.get("confidence") or raw.get("置信度") or 0)
    return LLMLeadScreeningDecision(
        valuable=bool(raw.get("valuable", raw.get("是否有价值", False))),
        demand_type=str(raw.get("demand_type") or raw.get("需求类型") or "unknown"),
        intent_strength=str(raw.get("intent_strength") or raw.get("意向强度") or "low"),
        judgment_evidence=tuple(str(item) for item in evidence if str(item).strip()),
        confidence=confidence,
        reason=str(raw.get("reason") or raw.get("判断原因") or ""),
        review_required=bool(raw.get("review_required") or raw.get("需要人工审核") or False),
        raw_json=raw,
        model_name=model_name,
    )


def _ensure_pending_screening(
    session: Session,
    context: LeadScreeningContext,
    *,
    existing: LeadScreeningResult | None,
) -> LeadScreeningResult:
    now = _utc_now()
    if existing is not None:
        return existing
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        inserted_id = session.scalar(
            insert(LeadScreeningResult)
            .values(
                platform=context.platform,
                source_entity_type=context.source_entity_type,
                source_entity_id=context.source_entity_id,
                content_id=context.content_id,
                comment_id=context.comment_id,
                public_profile_id=context.public_profile_id,
                context_json=context.to_prompt_payload(),
                review_status="needs_review",
                workflow_status=PENDING_LLM,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["source_entity_type", "source_entity_id"])
            .returning(LeadScreeningResult.id)
        )
        if inserted_id is not None:
            inserted = session.get(LeadScreeningResult, inserted_id)
            if inserted is not None:
                return inserted
        existing = _existing_screening(session, context)
        if existing is not None:
            return existing
    screening = LeadScreeningResult(
        platform=context.platform,
        source_entity_type=context.source_entity_type,
        source_entity_id=context.source_entity_id,
        content_id=context.content_id,
        comment_id=context.comment_id,
        public_profile_id=context.public_profile_id,
        context_json=context.to_prompt_payload(),
        review_status="needs_review",
        workflow_status=PENDING_LLM,
        created_at=now,
        updated_at=now,
    )
    session.add(screening)
    session.flush()
    return screening


def _claim_llm_screening(session: Session, screening: LeadScreeningResult) -> LeadScreeningResult | None:
    claimed = session.scalar(
        select(LeadScreeningResult)
        .where(LeadScreeningResult.id == screening.id)
        .where(LeadScreeningResult.workflow_status == PENDING_LLM)
        .with_for_update(skip_locked=True)
    )
    if claimed is None:
        return None
    claimed.workflow_status = SCREENING
    claimed.last_error = None
    claimed.updated_at = _utc_now()
    session.flush()
    return claimed


def _save_screening_result(
    session: Session,
    context: LeadScreeningContext,
    decision: LLMLeadScreeningDecision,
    *,
    screening: LeadScreeningResult | None = None,
) -> LeadScreeningResult:
    screening = screening or _existing_screening(session, context)
    now = _utc_now()
    if screening is None:
        screening = LeadScreeningResult(
            platform=context.platform,
            source_entity_type=context.source_entity_type,
            source_entity_id=context.source_entity_id,
            created_at=now,
        )
        session.add(screening)
    review_status = _review_status(decision)
    screening.content_id = context.content_id
    screening.comment_id = context.comment_id
    screening.public_profile_id = context.public_profile_id
    screening.model_name = decision.model_name
    screening.valuable = decision.valuable
    screening.demand_type = decision.demand_type
    screening.intent_strength = decision.intent_strength
    screening.confidence = _confidence_to_score(decision.confidence)
    screening.judgment_evidence_json = list(decision.judgment_evidence)
    screening.context_json = context.to_prompt_payload()
    screening.llm_raw_json = decision.raw_json
    screening.review_status = review_status
    screening.status_reason = decision.reason
    screening.error_message = None
    screening.workflow_status = LLM_DONE
    screening.last_error = None
    screening.updated_at = now
    return screening


def _apply_default_qualification(session: Session, screening: LeadScreeningResult) -> None:
    from platform_config.loader import load_campaign_config
    from services.qualification import (
        apply_qualification_result,
        location_evidence_from_screening,
        qualify_screening_result,
    )

    campaign_config_path = os.getenv("LEAD_QUALIFICATION_CAMPAIGN_CONFIG") or DEFAULT_QUALIFICATION_CAMPAIGN_CONFIG
    campaign = load_campaign_config(campaign_config_path)
    evidence = location_evidence_from_screening(screening, session=session)
    result = qualify_screening_result(screening, campaign, location_evidence=evidence)
    apply_qualification_result(screening, result)


def _save_failed_screening(
    session: Session,
    context: LeadScreeningContext,
    *,
    error_message: str,
    screening: LeadScreeningResult | None = None,
) -> None:
    screening = screening or _existing_screening(session, context)
    now = _utc_now()
    if screening is None:
        screening = LeadScreeningResult(
            platform=context.platform,
            source_entity_type=context.source_entity_type,
            source_entity_id=context.source_entity_id,
            created_at=now,
        )
        session.add(screening)
    screening.content_id = context.content_id
    screening.comment_id = context.comment_id
    screening.public_profile_id = context.public_profile_id
    screening.context_json = context.to_prompt_payload()
    screening.review_status = "needs_review"
    screening.error_message = error_message
    screening.workflow_status = PENDING_LLM
    screening.last_error = error_message
    screening.updated_at = now


def _upsert_lead_from_screening(
    session: Session,
    context: LeadScreeningContext,
    decision: LLMLeadScreeningDecision,
    review_status: str,
) -> tuple[Lead, bool]:
    if context.public_profile_id is None:
        raise RuntimeError("Cannot create lead without public_profile_id")
    profile = session.get(PublicProfile, context.public_profile_id)
    if profile is None:
        raise RuntimeError(f"Cannot create lead for missing profile {context.public_profile_id}")
    lead = session.scalar(select(Lead).where(Lead.platform == context.platform, Lead.public_profile_id == context.public_profile_id))
    created = lead is None
    now = _utc_now()
    if lead is None:
        lead = Lead(platform=context.platform, public_profile_id=context.public_profile_id, first_seen_at=now)
        session.add(lead)
        session.flush()
    combined_text = " ".join(
        part
        for part in (context.post_title, context.post_body, context.parent_comment, context.current_comment, profile.bio)
        if part
    )
    product = _detect_product(combined_text)
    region = profile.region_text or _detect_region(combined_text)
    confidence_score = _confidence_to_score(decision.confidence)
    lead.region_text = region
    lead.demand_type = decision.demand_type
    lead.product = product
    lead.intent_stage = _intent_stage(decision.intent_strength)
    lead.intent_score = confidence_score
    lead.information_completeness = _information_completeness(region=region, product=product, decision=decision)
    lead.known_info_json = {
        "platform": context.platform,
        "platform_user_id": profile.platform_user_id,
        "display_name": profile.display_name,
        "profile_url": profile.profile_url,
        "region": region,
        "product": product,
        "demand_type": decision.demand_type,
        "intent_strength": decision.intent_strength,
        "llm_screening": {
            "valuable": decision.valuable,
            "demand_type": decision.demand_type,
            "intent_strength": decision.intent_strength,
            "judgment_evidence": list(decision.judgment_evidence),
            "confidence": round(decision.confidence, 4),
            "review_status": review_status,
            "reason": decision.reason,
            "model_name": decision.model_name,
        },
    }
    lead.missing_info_json = _missing_info(region=region, product=product, profile=profile)
    lead.recommended_next_step = _recommended_next_step(decision, review_status)
    lead.last_seen_at = now
    lead.updated_at = now
    if lead.status not in {"handled", "ignored", "qualified"}:
        lead.status = _lead_status(decision, review_status)
    return lead, created


def _upsert_evidence(
    session: Session,
    *,
    lead: Lead,
    context: LeadScreeningContext,
    decision: LLMLeadScreeningDecision,
) -> int:
    existing = session.scalar(
        select(LeadEvidence).where(
            LeadEvidence.lead_id == lead.id,
            LeadEvidence.source_entity_type == context.source_entity_type,
            LeadEvidence.source_entity_id == context.source_entity_id,
        )
    )
    if existing is not None:
        existing.demand_type = decision.demand_type
        existing.intent_stage = _intent_stage(decision.intent_strength)
        existing.score_contribution = _confidence_to_score(decision.confidence)
        return 0
    session.add(
        LeadEvidence(
            lead_id=lead.id,
            source_entity_type=context.source_entity_type,
            source_entity_id=context.source_entity_id,
            content_id=context.content_id,
            comment_id=context.comment_id,
            evidence_text=_source_text(context),
            demand_type=decision.demand_type,
            intent_stage=_intent_stage(decision.intent_strength),
            score_contribution=_confidence_to_score(decision.confidence),
        )
    )
    return 1


def _existing_screening(session: Session, context: LeadScreeningContext) -> LeadScreeningResult | None:
    return session.scalar(
        select(LeadScreeningResult).where(
            LeadScreeningResult.source_entity_type == context.source_entity_type,
            LeadScreeningResult.source_entity_id == context.source_entity_id,
        )
    )


def _review_status(decision: LLMLeadScreeningDecision) -> str:
    if decision.review_required or decision.confidence < REVIEW_CONFIDENCE_THRESHOLD:
        return "needs_review"
    return "accepted" if decision.valuable else "rejected"


def _lead_status(decision: LLMLeadScreeningDecision, review_status: str) -> str:
    if review_status == "needs_review":
        return "needs_review"
    if decision.intent_strength == "high" and decision.confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "qualified"
    return "needs_enrichment"


def _intent_stage(intent_strength: str) -> str:
    return {
        "high": "action_ready",
        "medium": "evaluating",
        "low": "exploring",
    }.get(intent_strength, "exploring")


def _recommended_next_step(decision: LLMLeadScreeningDecision, review_status: str) -> str:
    if review_status == "needs_review":
        return "这条判断不确定，先人工查看原文再决定是否跟进"
    if decision.intent_strength == "high":
        return "查看证据原文，准备人工跟进"
    return "人工确认需求是否匹配，再决定是否跟进"


def _missing_info(*, region: str | None, product: str | None, profile: PublicProfile) -> list[str]:
    missing = []
    if not region:
        missing.append("region")
    if not product:
        missing.append("product")
    if not profile.public_contact_text:
        missing.append("contact")
    return missing


def _information_completeness(
    *,
    region: str | None,
    product: str | None,
    decision: LLMLeadScreeningDecision,
) -> int:
    present = sum(1 for value in (region, product, decision.demand_type, decision.intent_strength) if value)
    return int(present / 4 * 100)


def _detect_product(text: str) -> str | None:
    normalized = normalize_text(text)
    for product, keywords in PRODUCT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return product
    return None


def _detect_region(text: str) -> str | None:
    return next((region for region in REGION_KEYWORDS if region in text), None)


def _normalized_source_text(context: LeadScreeningContext) -> str:
    return normalize_text(_source_text(context)).strip().lower()


def _source_text(context: LeadScreeningContext) -> str:
    if context.source_entity_type == "comment":
        return context.current_comment
    return " ".join(part for part in (context.post_title, context.post_body) if part)


def _is_garbage_text(normalized_text: str) -> bool:
    compact = normalized_text.replace(" ", "")
    if len(compact) < 4:
        return True
    if compact in JUNK_TEXTS:
        return True
    return any(word in normalized_text for word in SPAM_WORDS)


def _confidence_to_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed > 1:
        parsed = parsed / 100
    return max(0.0, min(parsed, 1.0))


def _confidence_to_score(value: float) -> int:
    return int(round(_confidence_to_float(value) * 100))


def _chat_completions_url(api_url: str) -> str:
    normalized = api_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _utc_now() -> datetime:
    return datetime.now(UTC)
