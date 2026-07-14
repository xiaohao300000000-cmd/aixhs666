from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.skill_registry import (
    ScreenHistoricalLeadsParameters,
    get_skill_definition,
    list_campaign_options,
    list_skill_definitions,
)


def test_registry_exposes_only_historical_lead_screening() -> None:
    definitions = list_skill_definitions()

    assert [item.key for item in definitions] == ["screen_historical_leads"]
    assert definitions[0].name == "历史线索智能筛选"
    assert definitions[0].version == 1
    assert definitions[0].stages == ("prepare", "screen", "sync_feishu", "summarize")
    assert get_skill_definition("screen_historical_leads") is definitions[0]


def test_skill_parameters_validate_defaults_and_limits() -> None:
    campaign = list_campaign_options()[0]
    parameters = ScreenHistoricalLeadsParameters(campaign_id=campaign.campaign_id)

    assert parameters.data_range == "all"
    assert parameters.source_types == "content_and_comment"
    assert parameters.limit == 50

    for invalid_limit in (0, 501):
        with pytest.raises(ValidationError):
            ScreenHistoricalLeadsParameters(campaign_id=campaign.campaign_id, limit=invalid_limit)


def test_skill_parameters_reject_unknown_campaign_and_enums() -> None:
    with pytest.raises(ValueError, match="unknown campaign"):
        ScreenHistoricalLeadsParameters(campaign_id="missing")
    with pytest.raises(ValidationError):
        ScreenHistoricalLeadsParameters(campaign_id=list_campaign_options()[0].campaign_id, data_range="yesterday")
