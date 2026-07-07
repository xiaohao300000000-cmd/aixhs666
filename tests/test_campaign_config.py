from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_config.loader import load_campaign_config
from platform_config.models import CampaignConfig
from platform_config.validation import validate_campaign_config


def test_three_campaign_configs_load() -> None:
    education = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")
    ielts = load_campaign_config("configs/campaigns/ielts_nationwide_online.json")
    automotive = load_campaign_config("configs/campaigns/automotive_xiamen_local.json")

    assert education.campaign_id == "education_fuzhou_offline"
    assert education.service_mode == "offline"
    assert education.qualification_policy.location_policy.target_cities == ["福州"]
    assert ielts.service_mode == "online"
    assert ielts.qualification_policy.location_policy.allow_nationwide is True
    assert automotive.domain_id == "automotive"
    assert automotive.qualification_policy.location_policy.nearby_regions == ["泉州", "漳州"]


def test_missing_campaign_id_fails(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "name": "Bad campaign",
                "domain_id": "education",
                "enabled": True,
                "platforms": ["xhs"],
                "service_mode": "offline",
                "source_strategy": {"type": "manual"},
                "qualification_policy": _policy(),
                "version": "v1",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="campaign_id"):
        load_campaign_config(path)


def test_invalid_service_mode_fails(tmp_path: Path) -> None:
    data = _campaign()
    data["service_mode"] = "nearby"
    path = tmp_path / "bad-mode.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="service_mode"):
        load_campaign_config(path)


def test_config_validation_reports_location_conflicts() -> None:
    config = CampaignConfig.model_validate(
        _campaign(
            service_mode="online",
            location_policy={
                "required": True,
                "target_countries": ["中国"],
                "target_provinces": ["福建"],
                "target_cities": ["福州"],
                "nearby_regions": [],
                "allow_nationwide": True,
                "allow_overseas": False,
                "unknown_action": "needs_review",
                "conflict_action": "needs_review",
                "non_match_action": "reject",
            },
        )
    )

    result = validate_campaign_config(config)

    assert result.validation_result == "failed"
    assert "nationwide_conflicts_with_target_regions" in result.warnings
    assert "online_nationwide_requires_location" in result.warnings


def test_duplicate_regions_and_unknown_domain_are_reported() -> None:
    config = CampaignConfig.model_validate(
        _campaign(
            domain_id="unknown-domain",
            location_policy={
                "required": True,
                "target_countries": ["中国"],
                "target_provinces": ["福建", "福建"],
                "target_cities": ["福州", "福州"],
                "nearby_regions": [],
                "allow_nationwide": False,
                "allow_overseas": False,
                "unknown_action": "needs_review",
                "conflict_action": "needs_review",
                "non_match_action": "reject",
            },
        )
    )

    result = validate_campaign_config(config)

    assert result.validation_result == "failed"
    assert "unknown_domain_pack" in result.warnings
    assert "duplicate_target_provinces" in result.warnings
    assert "duplicate_target_cities" in result.warnings


def test_config_serialization_round_trips() -> None:
    config = load_campaign_config("configs/campaigns/education_fuzhou_offline.json")

    reloaded = CampaignConfig.model_validate_json(config.model_dump_json())

    assert reloaded == config


def _campaign(
    *,
    domain_id: str = "education",
    service_mode: str = "offline",
    location_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "campaign_id": "test_campaign",
        "name": "Test campaign",
        "domain_id": domain_id,
        "enabled": True,
        "platforms": ["xhs"],
        "service_mode": service_mode,
        "source_strategy": {"type": "manual"},
        "qualification_policy": _policy(location_policy=location_policy),
        "version": "v1",
    }


def _policy(*, location_policy: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "minimum_intent_score": 65,
        "maximum_signal_age_days": 90,
        "allowed_personas": ["parent"],
        "excluded_personas": ["provider"],
        "location_policy": location_policy
        or {
            "required": True,
            "target_countries": ["中国"],
            "target_provinces": ["福建"],
            "target_cities": ["福州"],
            "nearby_regions": [],
            "allow_nationwide": False,
            "allow_overseas": False,
            "unknown_action": "needs_review",
            "conflict_action": "needs_review",
            "non_match_action": "reject",
        },
        "manual_review_conditions": ["model_uncertain", "location_unknown"],
    }
