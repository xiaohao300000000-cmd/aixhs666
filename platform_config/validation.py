from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from platform_config.models import CampaignConfig, ServiceMode


KNOWN_DOMAIN_PACKS = {"education", "ielts", "automotive"}


class CampaignValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    domain_id: str
    service_mode: str
    platforms: list[str]
    location_scope: str
    minimum_intent_score: int
    manual_review_conditions: list[str]
    validation_result: str
    warnings: list[str] = Field(default_factory=list)


def validate_campaign_config(config: CampaignConfig) -> CampaignValidationResult:
    warnings: list[str] = []
    policy = config.qualification_policy
    location = policy.location_policy

    if config.domain_id not in KNOWN_DOMAIN_PACKS:
        warnings.append("unknown_domain_pack")
    if _has_duplicates(location.target_provinces):
        warnings.append("duplicate_target_provinces")
    if _has_duplicates(location.target_cities):
        warnings.append("duplicate_target_cities")
    if _has_duplicates(location.nearby_regions):
        warnings.append("duplicate_nearby_regions")
    has_target_regions = bool(location.target_countries or location.target_provinces or location.target_cities)
    if location.allow_nationwide and has_target_regions:
        warnings.append("nationwide_conflicts_with_target_regions")
    if config.service_mode == ServiceMode.OFFLINE and not has_target_regions and not location.allow_nationwide:
        warnings.append("offline_location_not_configured")
    if config.service_mode == ServiceMode.ONLINE and location.allow_nationwide and location.required:
        warnings.append("online_nationwide_requires_location")

    return CampaignValidationResult(
        campaign_id=config.campaign_id,
        domain_id=config.domain_id,
        service_mode=config.service_mode.value,
        platforms=list(config.platforms),
        location_scope=_location_scope(config),
        minimum_intent_score=policy.minimum_intent_score,
        manual_review_conditions=list(policy.manual_review_conditions),
        validation_result="failed" if warnings else "passed",
        warnings=warnings,
    )


def _location_scope(config: CampaignConfig) -> str:
    location = config.qualification_policy.location_policy
    if location.allow_nationwide:
        return "nationwide"
    if location.target_cities:
        return "city:" + ",".join(location.target_cities)
    if location.target_provinces:
        return "province:" + ",".join(location.target_provinces)
    if location.target_countries:
        return "country:" + ",".join(location.target_countries)
    return "unspecified"


def _has_duplicates(values: list[str]) -> bool:
    return len(values) != len({value.casefold() for value in values})
