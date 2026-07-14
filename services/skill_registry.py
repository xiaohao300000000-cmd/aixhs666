from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from platform_config.loader import load_campaign_config
from platform_config.models import CampaignConfig


DataRange = Literal["all", "last_30_days", "last_90_days"]
SourceTypes = Literal["content_and_comment", "content_only", "comment_only"]


@dataclass(frozen=True, slots=True)
class CampaignOption:
    campaign_id: str
    name: str
    path: str
    service_mode: str
    location_summary: str


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    key: str
    name: str
    version: int
    description: str
    stages: tuple[str, ...]


class ScreenHistoricalLeadsParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_range: DataRange = "all"
    source_types: SourceTypes = "content_and_comment"
    limit: int = Field(default=50, ge=1, le=500)
    campaign_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_campaign(self) -> "ScreenHistoricalLeadsParameters":
        if self.campaign_id not in _campaigns_by_id():
            raise ValueError(f"unknown campaign: {self.campaign_id}")
        return self


_SCREEN_HISTORICAL_LEADS = SkillDefinition(
    key="screen_historical_leads",
    name="历史线索智能筛选",
    version=1,
    description="使用本地历史数据、DeepSeek 和 Campaign 规则筛选潜在客户并同步飞书审核表。",
    stages=("prepare", "screen", "sync_feishu", "summarize"),
)


def list_skill_definitions() -> list[SkillDefinition]:
    return [_SCREEN_HISTORICAL_LEADS]


def get_skill_definition(skill_key: str) -> SkillDefinition:
    if skill_key != _SCREEN_HISTORICAL_LEADS.key:
        raise ValueError(f"unknown skill: {skill_key}")
    return _SCREEN_HISTORICAL_LEADS


def list_campaign_options() -> list[CampaignOption]:
    options: list[CampaignOption] = []
    for campaign_id, (path, campaign) in sorted(_campaigns_by_id().items()):
        location = campaign.qualification_policy.location_policy
        targets = location.target_cities or location.target_provinces or location.target_countries
        summary = "全国/不限地区" if not location.required else "、".join(targets) or "需要地区匹配"
        options.append(
            CampaignOption(
                campaign_id=campaign_id,
                name=campaign.name,
                path=str(path),
                service_mode=campaign.service_mode.value,
                location_summary=summary,
            )
        )
    return options


def load_registered_campaign(campaign_id: str) -> CampaignConfig:
    try:
        return _campaigns_by_id()[campaign_id][1]
    except KeyError as exc:
        raise ValueError(f"unknown campaign: {campaign_id}") from exc


def _campaigns_by_id() -> dict[str, tuple[Path, CampaignConfig]]:
    root = Path(__file__).parents[1] / "configs" / "campaigns"
    campaigns: dict[str, tuple[Path, CampaignConfig]] = {}
    for path in sorted(root.glob("*.json")):
        campaign = load_campaign_config(path)
        if campaign.enabled:
            campaigns[campaign.campaign_id] = (path, campaign)
    return campaigns
