from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Lead, LeadScreeningResult, SkillRun


LAYERS = (
    "priority_review",
    "standard_review",
    "uncertain_review",
    "automatic_exclusion",
)

_HARD_EXCLUSION_LABELS = {
    "advertisement": "明确广告",
    "promotion_account": "明确广告账号",
    "institution_account": "明确机构账号",
    "irrelevant": "明确无关",
    "exact_duplicate": "完全重复",
    "deleted_without_valid_evidence": "已删除且无有效证据",
    "hard_condition_violation": "明确违反 Campaign 硬条件",
    "location_not_matched": "明确违反地区硬条件",
    "test_data": "测试数据",
}
_SOFT_UNCERTAINTY_CODES = {
    "intent_too_low",
    "model_uncertain",
    "location_unknown",
    "location_conflicting",
    "signal_too_old",
    "information_insufficient",
}
_LAYER_PRIORITY = {
    "priority_review": 400,
    "standard_review": 300,
    "uncertain_review": 200,
    "automatic_exclusion": 100,
}
_INTENT_PRIORITY = {
    "high": 3,
    "medium": 2,
    "low": 1,
}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ScreeningClassification:
    layer: str
    reason: str
    priority_rank: int
    hard_exclusion_reason: str | None = None


def classify_screening(screening: LeadScreeningResult) -> ScreeningClassification:
    reason_codes = set(screening.qualification_reason_codes_json or [])
    hard_code = next((code for code in _HARD_EXCLUSION_LABELS if code in reason_codes), None)
    if hard_code is not None:
        label = _HARD_EXCLUSION_LABELS[hard_code]
        return ScreeningClassification("automatic_exclusion", label, 100, label)
    if screening.human_review_status == "invalid":
        label = "人工确认无效且没有新的有效证据"
        return ScreeningClassification("automatic_exclusion", label, 100, label)

    confidence = screening.confidence if screening.confidence is not None else 0
    is_soft_uncertain = bool(reason_codes & _SOFT_UNCERTAINTY_CODES) or any(
        (
            screening.valuable is False,
            screening.review_status == "rejected",
            screening.qualification_decision == "rejected",
            screening.intent_strength in {None, "low"},
            confidence < 70,
            not screening.judgment_evidence_json,
        )
    )
    if is_soft_uncertain:
        return ScreeningClassification(
            "uncertain_review",
            "信息或判断存在不确定性，按高召回原则保留人工审核",
            200 + confidence,
        )
    if screening.intent_strength == "high" or confidence >= 85:
        return ScreeningClassification(
            "priority_review",
            "需求信号或判断置信度较强",
            400 + confidence,
        )
    return ScreeningClassification("standard_review", "候选信息完整，进入普通审核", 300 + confidence)


def candidate_key(screening: LeadScreeningResult) -> str:
    if screening.public_profile_id is not None:
        return f"profile:{screening.public_profile_id}"
    return f"source:{screening.source_entity_type}:{screening.source_entity_id}"


def build_run_candidates(session: Session, run: SkillRun) -> list[dict[str, Any]]:
    raw_ids = (run.checkpoint_json or {}).get("screening_ids", [])
    screening_ids = [int(value) for value in raw_ids if str(value).isdigit()]
    if not screening_ids:
        return []
    screenings = session.scalars(
        select(LeadScreeningResult).where(LeadScreeningResult.id.in_(screening_ids))
    ).all()
    return build_candidates_from_screenings(session, screenings, run_id=run.id)


def build_candidates_from_screenings(
    session: Session,
    screenings: list[LeadScreeningResult],
    *,
    run_id: int | None = None,
    errors: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[LeadScreeningResult]] = {}
    for screening in screenings:
        groups.setdefault(candidate_key(screening), []).append(screening)

    items: list[dict[str, Any]] = []
    for key, values in groups.items():
        try:
            items.append(_group_view(session, run_id, key, values))
        except Exception as exc:
            if errors is None:
                raise
            errors.append({"candidate_key": key, "error": str(exc)[:240]})
    return sorted(items, key=_candidate_sort_key)


def rebuild_skill_run_report(session: Session, run_id: int) -> dict[str, Any]:
    run = session.get(SkillRun, run_id)
    if run is None:
        raise LookupError("skill run not found")
    if run.status != "succeeded":
        raise ValueError("business report can only be built for a succeeded run")

    candidates = build_run_candidates(session, run)
    counts = {layer: 0 for layer in LAYERS}
    exclusion_reasons: dict[str, int] = {}
    for item in candidates:
        counts[str(item["layer"])] += 1
        if item["layer"] == "automatic_exclusion":
            reason = str(item["hard_exclusion_reason"] or "明确自动排除")
            exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1

    reviewable_count = sum(counts[layer] for layer in LAYERS[:3])
    processed = int((run.result_summary_json or {}).get("processed_count", len(candidates)) or 0)
    if reviewable_count:
        conclusion = (
            f"本次分析 {processed} 条公开内容，合并得到 {reviewable_count} 个待审核候选，"
            f"其中 {counts['priority_review']} 个为高优先级。"
        )
        next_action = {
            "kind": "review_run_candidates",
            "label": "审核本次候选",
            "href": f"/leads?run_id={run.id}",
        }
    else:
        conclusion = "本次运行已完成，但没有发现需要进入人工审核的候选。"
        next_action = {
            "kind": "view_run_details",
            "label": "查看运行详情",
            "href": f"/tasks?run_id={run.id}",
        }

    sync = dict((run.result_summary_json or {}).get("feishu_sync", {}) or {})
    report = {
        "version": 1,
        "run_id": run.id,
        "conclusion": conclusion,
        "scope": {
            "campaign_id": (run.parameters_json or {}).get("campaign_id"),
            "data_range": (run.parameters_json or {}).get("data_range"),
            "source_types": (run.parameters_json or {}).get("source_types"),
            "processed_count": processed,
            "candidate_count": len(candidates),
        },
        "counts": counts,
        "exclusion_reasons": exclusion_reasons,
        "candidates": candidates,
        "queue": {"prepared": 0, "quality_control": 0, "emergency": 0},
        "destinations": {
            "postgresql": {"status": "persisted", "detail": "原始筛选与业务报告均已保留"},
            "miaoda": {"status": "ready", "href": f"/leads?run_id={run.id}"},
            "base": _sync_destination(sync),
            "feishu": {"status": "summary_ready"},
        },
        "next_action": next_action,
        "technical_details": {
            "default_collapsed": True,
            "references": ["result_summary_json", "checkpoint_json", "skill_run_events"],
        },
    }
    run.business_report_json = report
    session.flush()
    return report


def _group_view(
    session: Session,
    run_id: int | None,
    key: str,
    screenings: list[LeadScreeningResult],
) -> dict[str, Any]:
    classified = [(item, classify_screening(item)) for item in screenings]
    reviewable = [pair for pair in classified if pair[1].layer != "automatic_exclusion"]
    pool = reviewable or classified
    representative, classification = max(
        pool,
        key=lambda pair: (
            _LAYER_PRIORITY[pair[1].layer],
            pair[0].confidence or 0,
            pair[0].updated_at,
            pair[0].id or 0,
        ),
    )
    ordered_screenings = sorted(screenings, key=lambda item: item.id or 0)
    candidate_updated_at = max(
        (_as_utc(item.updated_at) for item in ordered_screenings),
        default=_EPOCH,
    )
    lead = None
    if representative.public_profile_id is not None:
        lead = session.scalar(
            select(Lead).where(
                Lead.platform == representative.platform,
                Lead.public_profile_id == representative.public_profile_id,
            )
        )
    evidence: list[str] = []
    for screening in ordered_screenings:
        for value in screening.judgment_evidence_json or []:
            cleaned = str(value).strip()
            if cleaned and cleaned not in evidence:
                evidence.append(cleaned[:240])
    return {
        "run_id": run_id,
        "candidate_key": key,
        "lead_id": lead.id if lead is not None else None,
        "public_profile_id": representative.public_profile_id,
        "representative_screening_id": representative.id,
        "screening_ids": [item.id for item in ordered_screenings],
        "layer": classification.layer,
        "reason": classification.reason,
        "hard_exclusion_reason": classification.hard_exclusion_reason,
        "intent_strength": representative.intent_strength,
        "confidence": representative.confidence,
        "updated_at": candidate_updated_at.isoformat(),
        "priority_rank": classification.priority_rank,
        "evidence": evidence[:5],
        "status": "reviewed" if representative.human_review_status else "pending",
        "miaoda_href": f"/leads?candidate_key={key}",
        "next_action": "人工审核" if classification.layer != "automatic_exclusion" else "排除抽检",
    }


def _candidate_sort_key(item: dict[str, Any]) -> tuple[int, int, int, float, int, str]:
    layer = str(item["layer"])
    intent = str(item.get("intent_strength") or "").lower()
    updated_at = _as_utc(datetime.fromisoformat(str(item["updated_at"])))
    return (
        -_LAYER_PRIORITY.get(layer, 0),
        -_INTENT_PRIORITY.get(intent, 0),
        -int(item.get("confidence") or 0),
        -updated_at.timestamp(),
        -int(item["representative_screening_id"]),
        str(item["candidate_key"]),
    )


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return _EPOCH
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sync_destination(sync: dict[str, Any]) -> dict[str, Any]:
    if int(sync.get("dry_run", 0) or 0):
        return {"status": "not_written", "detail": "dry-run，未写入 Base"}
    if int(sync.get("failed", 0) or 0):
        return {"status": "partial_failure", "detail": "部分记录同步失败"}
    if sync:
        return {"status": "synced", "detail": "筛选结果已完成 Base/飞书投影"}
    return {"status": "not_requested", "detail": "本次没有请求外部投影"}
