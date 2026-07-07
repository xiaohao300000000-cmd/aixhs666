from __future__ import annotations

from datetime import UTC, datetime, timedelta

from platform_config.loader import load_campaign_config
from platform_config.models import LocationEvidence
from services.qualification import apply_qualification_result, evaluate_location_policy, qualify_screening_result
from storage.models import LeadScreeningResult


def test_nationwide_online_location_unknown_is_not_rejected() -> None:
    config = load_campaign_config("configs/campaigns/ielts_nationwide_online.json")
    screening = _screening(confidence=82, review_status="accepted")

    result = qualify_screening_result(screening, config, location_evidence=[], now=_now())

    assert result.decision == "qualified"
    assert result.location.match_status == "not_required"
    assert "location_unknown" not in result.reason_codes


def test_fuzhou_offline_explicit_non_match_is_rejected() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")
    evidence = [
        LocationEvidence(
            source="ip_region",
            raw_value="上海",
            normalized_country="中国",
            normalized_province="上海",
            normalized_city="上海",
            normalized_district=None,
            confidence=0.9,
            observed_at=_now(),
            evidence_text="IP属地：上海",
        )
    ]

    location = evaluate_location_policy(evidence, config.qualification_policy.location_policy)
    result = qualify_screening_result(_screening(confidence=88), config, location_evidence=evidence, now=_now())

    assert location.match_status == "not_matched"
    assert result.decision == "rejected"
    assert "location_not_matched" in result.reason_codes


def test_fuzhou_offline_unknown_location_needs_review() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")

    result = qualify_screening_result(_screening(confidence=88), config, location_evidence=[], now=_now())

    assert result.decision == "needs_review"
    assert result.location.match_status == "unknown"
    assert "location_unknown" in result.reason_codes


def test_ip_city_match_is_matched() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")
    evidence = [
        LocationEvidence(
            source="ip_region",
            raw_value="福州",
            normalized_country="中国",
            normalized_province="福建",
            normalized_city="福州",
            normalized_district=None,
            confidence=0.95,
            observed_at=_now(),
            evidence_text="IP属地：福州",
        )
    ]

    location = evaluate_location_policy(evidence, config.qualification_policy.location_policy)

    assert location.match_status == "matched"
    assert location.resolved_location["city"] == "福州"


def test_province_only_ip_does_not_infer_city_match() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")
    evidence = [
        LocationEvidence(
            source="ip_region",
            raw_value="福建",
            normalized_country="中国",
            normalized_province="福建",
            normalized_city=None,
            normalized_district=None,
            confidence=0.85,
            observed_at=_now(),
            evidence_text="IP属地：福建",
        )
    ]

    location = evaluate_location_policy(evidence, config.qualification_policy.location_policy)

    assert location.match_status == "unknown"
    assert "city_missing" in location.reason


def test_conflicting_location_evidence_needs_review() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")
    evidence = [
        LocationEvidence(
            source="ip_region",
            raw_value="福州",
            normalized_country="中国",
            normalized_province="福建",
            normalized_city="福州",
            normalized_district=None,
            confidence=0.95,
            observed_at=_now(),
            evidence_text="IP属地：福州",
        ),
        LocationEvidence(
            source="comment_text",
            raw_value="我在上海",
            normalized_country="中国",
            normalized_province="上海",
            normalized_city="上海",
            normalized_district=None,
            confidence=0.6,
            observed_at=_now(),
            evidence_text="评论：我在上海",
        ),
    ]

    result = qualify_screening_result(_screening(confidence=88), config, location_evidence=evidence, now=_now())

    assert result.location.match_status == "conflicting"
    assert result.decision == "needs_review"
    assert "location_conflicting" in result.reason_codes


def test_location_not_required_returns_not_required() -> None:
    config = load_campaign_config("configs/campaigns/ielts_nationwide_online.json")

    location = evaluate_location_policy([], config.qualification_policy.location_policy)

    assert location.match_status == "not_required"
    assert location.reason == "location_not_required"


def test_reason_codes_include_intent_and_signal_age() -> None:
    config = load_campaign_config("configs/campaigns/ielts_nationwide_online.json")
    old_screening = _screening(confidence=40, review_status="rejected", updated_at=_now() - timedelta(days=120))

    result = qualify_screening_result(old_screening, config, location_evidence=[], now=_now())

    assert result.decision == "rejected"
    assert "intent_too_low" in result.reason_codes
    assert "signal_too_old" in result.reason_codes
    assert result.policy_version == config.version
    assert result.confidence == 0.4


def test_qualification_result_can_be_saved_without_overwriting_workflow_state() -> None:
    config = load_campaign_config("configs/campaigns/ielts_nationwide_online.json")
    screening = _screening(confidence=88, review_status="accepted")
    screening.workflow_status = "sent"

    result = qualify_screening_result(screening, config, location_evidence=[], now=_now())
    apply_qualification_result(screening, result)

    assert screening.qualification_decision == "qualified"
    assert screening.qualification_reason_codes_json == []
    assert screening.qualification_human_reason == "符合当前 Campaign 资格策略"
    assert screening.qualification_confidence == 88
    assert screening.qualification_policy_version == "ielts_nationwide_online_v1"
    assert screening.qualification_location_json["match_status"] == "not_required"
    assert screening.review_status == "accepted"
    assert screening.workflow_status == "sent"


def _screening(
    *,
    confidence: int,
    review_status: str = "accepted",
    updated_at: datetime | None = None,
) -> LeadScreeningResult:
    return LeadScreeningResult(
        platform="xhs",
        source_entity_type="comment",
        source_entity_id=1,
        review_status=review_status,
        workflow_status="llm_done",
        valuable=review_status != "rejected",
        confidence=confidence,
        status_reason="test reason",
        updated_at=updated_at or _now(),
    )


def _now() -> datetime:
    return datetime(2026, 7, 7, tzinfo=UTC)
