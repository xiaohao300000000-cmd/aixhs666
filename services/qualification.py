from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from platform_config.models import (
    CampaignConfig,
    LocationEvidence,
    LocationPolicy,
    LocationQualificationResult,
    PolicyAction,
    QualificationDecision,
    QualificationResult,
)
from storage.models import Comment, Content, LeadScreeningResult, PublicProfile


def evaluate_location_policy(
    evidence: list[LocationEvidence],
    policy: LocationPolicy,
) -> LocationQualificationResult:
    if not policy.required or policy.allow_nationwide:
        return LocationQualificationResult(
            resolved_location={},
            match_status="not_required",
            reason="location_not_required",
            confidence=1.0,
            evidence=evidence,
        )
    if not evidence:
        return LocationQualificationResult(
            resolved_location={},
            match_status="unknown",
            reason="no_location_evidence",
            confidence=0.0,
            evidence=[],
        )
    if _has_conflict(evidence):
        return LocationQualificationResult(
            resolved_location=_resolved_location(max(evidence, key=lambda item: item.confidence)),
            match_status="conflicting",
            reason="conflicting_location_evidence",
            confidence=max(item.confidence for item in evidence),
            evidence=evidence,
        )

    strongest = max(evidence, key=lambda item: item.confidence)
    resolved = _resolved_location(strongest)
    if _matches_policy(strongest, policy):
        return LocationQualificationResult(
            resolved_location=resolved,
            match_status="matched",
            reason="location_matched",
            confidence=strongest.confidence,
            evidence=evidence,
        )
    if policy.target_cities and strongest.normalized_city is None and strongest.normalized_province in policy.target_provinces:
        return LocationQualificationResult(
            resolved_location=resolved,
            match_status="unknown",
            reason="province_matched_city_missing",
            confidence=strongest.confidence,
            evidence=evidence,
        )
    if strongest.normalized_city in policy.nearby_regions:
        return LocationQualificationResult(
            resolved_location=resolved,
            match_status="not_matched",
            reason="nearby_region_lower_priority",
            confidence=strongest.confidence,
            evidence=evidence,
        )
    return LocationQualificationResult(
        resolved_location=resolved,
        match_status="not_matched",
        reason="location_not_matched",
        confidence=strongest.confidence,
        evidence=evidence,
    )


def qualify_screening_result(
    screening: LeadScreeningResult,
    campaign: CampaignConfig,
    *,
    location_evidence: list[LocationEvidence],
    now: datetime | None = None,
) -> QualificationResult:
    now = now or datetime.now(UTC)
    policy = campaign.qualification_policy
    location = evaluate_location_policy(location_evidence, policy.location_policy)
    reason_codes: list[str] = []
    hard_reject = False
    needs_review = False

    confidence = _confidence(screening)
    intent_score = int(round(confidence * 100))
    if intent_score < policy.minimum_intent_score or screening.review_status == "rejected" or screening.valuable is False:
        reason_codes.append("intent_too_low")
        hard_reject = True
    if _signal_age_days(screening, now) > policy.maximum_signal_age_days:
        reason_codes.append("signal_too_old")
        hard_reject = True
    if screening.review_status == "needs_review":
        reason_codes.append("model_uncertain")
        needs_review = True

    location_action = _location_action(location.match_status, policy.location_policy)
    if location.match_status == "unknown":
        reason_codes.append("location_unknown")
    elif location.match_status == "conflicting":
        reason_codes.append("location_conflicting")
    elif location.match_status == "not_matched":
        reason_codes.append("location_not_matched")

    if location_action == PolicyAction.REJECT:
        hard_reject = True
    elif location_action in {PolicyAction.NEEDS_REVIEW, PolicyAction.LOWER_PRIORITY}:
        needs_review = True

    if hard_reject:
        decision = QualificationDecision.REJECTED
    elif needs_review:
        decision = QualificationDecision.NEEDS_REVIEW
    else:
        decision = QualificationDecision.QUALIFIED

    return QualificationResult(
        decision=decision,
        reason_codes=_unique(reason_codes),
        human_readable_reason=_human_reason(reason_codes, decision),
        confidence=confidence,
        evidence_ids=_evidence_ids(screening, location_evidence),
        policy_version=campaign.version,
        location=location,
    )


def apply_qualification_result(screening: LeadScreeningResult, result: QualificationResult) -> None:
    screening.qualification_decision = result.decision.value
    screening.qualification_reason_codes_json = list(result.reason_codes)
    screening.qualification_human_reason = result.human_readable_reason
    screening.qualification_confidence = int(round(result.confidence * 100))
    screening.qualification_evidence_ids_json = list(result.evidence_ids)
    screening.qualification_policy_version = result.policy_version
    screening.qualification_location_json = {
        "resolved_location": result.location.resolved_location,
        "match_status": result.location.match_status.value,
        "reason": result.location.reason,
        "confidence": result.location.confidence,
        "evidence": [item.model_dump(mode="json") for item in result.location.evidence],
    }


def location_evidence_from_screening(
    screening: LeadScreeningResult,
    *,
    observed_at: datetime | None = None,
    session: Session | None = None,
) -> list[LocationEvidence]:
    observed = observed_at or screening.updated_at or screening.created_at or datetime.now(UTC)
    context = screening.context_json or {}
    evidence: list[LocationEvidence] = []
    if session is not None:
        evidence.extend(_structured_location_evidence(session, screening, observed_at=observed))
    profile_region = _clean(context.get("profile_region"))
    if profile_region:
        evidence.extend(_evidence_from_text("profile_location", profile_region, observed_at=observed, evidence_text=profile_region))
    post_location = _clean(context.get("post_location"))
    if post_location:
        evidence.extend(_evidence_from_text("post_location", post_location, observed_at=observed, evidence_text=post_location))
    content_text = " ".join(
        part
        for part in (_clean(context.get("post_title")), _clean(context.get("post_body")), _clean(context.get("parent_comment")))
        if part
    )
    if content_text:
        evidence.extend(_evidence_from_text("content_text", content_text, observed_at=observed, evidence_text="content_text"))
    comment_text = _clean(context.get("current_comment"))
    if comment_text:
        evidence.extend(_evidence_from_text("comment_text", comment_text, observed_at=observed, evidence_text="comment_text"))
    return _dedupe_evidence(evidence)


def summarize_qualification_results(
    session: Session,
    campaign: CampaignConfig,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    counts = {
        "total_records": 0,
        "qualified": 0,
        "rejected": 0,
        "needs_review": 0,
        "location_matched": 0,
        "location_not_matched": 0,
        "location_unknown": 0,
        "location_conflicting": 0,
        "location_not_required": 0,
        "no_location_evidence": 0,
        "ip_only_evidence": 0,
    }
    rows = session.scalars(select(LeadScreeningResult).order_by(LeadScreeningResult.id.asc())).all()
    for screening in rows:
        evidence = location_evidence_from_screening(screening, observed_at=now, session=session)
        result = qualify_screening_result(screening, campaign, location_evidence=evidence, now=now)
        counts["total_records"] += 1
        counts[result.decision.value] += 1
        counts[f"location_{result.location.match_status.value}"] += 1
        if not evidence:
            counts["no_location_evidence"] += 1
        if evidence and all(item.source.value == "ip_region" for item in evidence):
            counts["ip_only_evidence"] += 1
    return counts


def _location_action(match_status: str, policy: LocationPolicy) -> PolicyAction:
    if match_status in {"matched", "not_required"}:
        return PolicyAction.ACCEPT
    if match_status == "unknown":
        return policy.unknown_action
    if match_status == "conflicting":
        return policy.conflict_action
    return policy.non_match_action


def _matches_policy(evidence: LocationEvidence, policy: LocationPolicy) -> bool:
    if policy.target_cities:
        return evidence.normalized_city in policy.target_cities
    if policy.target_provinces:
        return evidence.normalized_province in policy.target_provinces
    if policy.target_countries:
        return evidence.normalized_country in policy.target_countries
    return False


def _has_conflict(evidence: list[LocationEvidence]) -> bool:
    cities = {item.normalized_city for item in evidence if item.normalized_city}
    if len(cities) > 1:
        return True
    provinces = {item.normalized_province for item in evidence if item.normalized_province}
    return len(cities) == 0 and len(provinces) > 1


def _resolved_location(evidence: LocationEvidence) -> dict[str, str | None]:
    return {
        "country": evidence.normalized_country,
        "province": evidence.normalized_province,
        "city": evidence.normalized_city,
        "district": evidence.normalized_district,
        "raw_value": evidence.raw_value,
        "source": evidence.source.value,
    }


def _confidence(screening: LeadScreeningResult) -> float:
    if screening.confidence is None:
        return 0.0
    return max(0.0, min(1.0, float(screening.confidence) / 100.0))


def _signal_age_days(screening: LeadScreeningResult, now: datetime) -> int:
    updated_at = screening.updated_at or screening.created_at or now
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return max(0, (now.astimezone(UTC) - updated_at.astimezone(UTC)).days)


def _evidence_ids(screening: LeadScreeningResult, location_evidence: list[LocationEvidence]) -> list[str]:
    values: list[str] = []
    if screening.id is not None:
        values.append(f"lead_screening_result:{screening.id}")
    else:
        values.append(f"{screening.source_entity_type}:{screening.source_entity_id}")
    values.extend(f"location:{item.source.value}:{item.raw_value}" for item in location_evidence)
    return values


def _human_reason(reason_codes: list[str], decision: QualificationDecision) -> str:
    if not reason_codes:
        return "符合当前 Campaign 资格策略"
    labels = {
        "intent_too_low": "意向分不足",
        "signal_too_old": "信号过旧",
        "model_uncertain": "模型判断不确定",
        "location_unknown": "地区未知",
        "location_conflicting": "地区证据冲突",
        "location_not_matched": "地区不匹配",
    }
    joined = "；".join(labels.get(code, code) for code in _unique(reason_codes))
    return f"{decision.value}: {joined}"


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _structured_location_evidence(session: Session, screening: LeadScreeningResult, *, observed_at: datetime) -> list[LocationEvidence]:
    evidence: list[LocationEvidence] = []
    if screening.comment_id is not None:
        comment = session.get(Comment, screening.comment_id)
        if comment is not None and comment.region_text:
            evidence.extend(_evidence_from_text("ip_region", comment.region_text, observed_at=observed_at, evidence_text="comment.region_text"))
    if screening.content_id is not None:
        content = session.get(Content, screening.content_id)
        if content is not None and content.region_text:
            evidence.extend(_evidence_from_text("post_location", content.region_text, observed_at=observed_at, evidence_text="content.region_text"))
    if screening.public_profile_id is not None:
        profile = session.get(PublicProfile, screening.public_profile_id)
        if profile is not None and profile.region_text:
            evidence.extend(_evidence_from_text("profile_location", profile.region_text, observed_at=observed_at, evidence_text="profile.region_text"))
    return evidence


_CITY_TO_PROVINCE = {
    "北京": "北京",
    "上海": "上海",
    "广州": "广东",
    "深圳": "广东",
    "杭州": "浙江",
    "南京": "江苏",
    "苏州": "江苏",
    "成都": "四川",
    "重庆": "重庆",
    "武汉": "湖北",
    "西安": "陕西",
    "福州": "福建",
    "厦门": "福建",
    "泉州": "福建",
    "漳州": "福建",
    "天津": "天津",
    "郑州": "河南",
    "长沙": "湖南",
    "合肥": "安徽",
    "青岛": "山东",
    "宁波": "浙江",
    "佛山": "广东",
    "东莞": "广东",
}
_PROVINCES = {"中国", "福建", "上海", "北京", "广东", "浙江", "江苏", "四川", "重庆", "湖北", "陕西", "天津", "河南", "湖南", "安徽", "山东"}


def _evidence_from_text(source: str, text: str, *, observed_at: datetime, evidence_text: str) -> list[LocationEvidence]:
    values: list[LocationEvidence] = []
    for city, province in _CITY_TO_PROVINCE.items():
        if city in text:
            values.append(
                LocationEvidence(
                    source=source,
                    raw_value=city,
                    normalized_country="中国",
                    normalized_province=province,
                    normalized_city=city,
                    normalized_district=None,
                    confidence=0.65 if source in {"content_text", "comment_text"} else 0.85,
                    observed_at=observed_at,
                    evidence_text=evidence_text,
                )
            )
    if values:
        return values
    for province in _PROVINCES:
        if province != "中国" and province in text:
            values.append(
                LocationEvidence(
                    source=source,
                    raw_value=province,
                    normalized_country="中国",
                    normalized_province=province,
                    normalized_city=None,
                    normalized_district=None,
                    confidence=0.55 if source in {"content_text", "comment_text"} else 0.8,
                    observed_at=observed_at,
                    evidence_text=evidence_text,
                )
            )
    return values


def _dedupe_evidence(evidence: list[LocationEvidence]) -> list[LocationEvidence]:
    seen: set[tuple[str, str]] = set()
    result: list[LocationEvidence] = []
    for item in evidence:
        key = (item.source.value, item.raw_value)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _clean(value: object) -> str:
    return str(value).strip() if value else ""
