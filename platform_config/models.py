from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ServiceMode(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    HYBRID = "hybrid"


class PolicyAction(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"
    LOWER_PRIORITY = "lower_priority"


class LocationEvidenceSource(StrEnum):
    IP_REGION = "ip_region"
    PROFILE_LOCATION = "profile_location"
    CONTENT_TEXT = "content_text"
    COMMENT_TEXT = "comment_text"
    POST_LOCATION = "post_location"
    SCHOOL_OR_LANDMARK = "school_or_landmark"


class LocationMatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    NOT_REQUIRED = "not_required"


class QualificationDecision(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class LocationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    target_countries: list[str] = Field(default_factory=list)
    target_provinces: list[str] = Field(default_factory=list)
    target_cities: list[str] = Field(default_factory=list)
    nearby_regions: list[str] = Field(default_factory=list)
    allow_nationwide: bool = False
    allow_overseas: bool = False
    unknown_action: PolicyAction
    conflict_action: PolicyAction
    non_match_action: PolicyAction


class QualificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_intent_score: int = Field(ge=0, le=100)
    maximum_signal_age_days: int = Field(ge=0)
    allowed_personas: list[str] = Field(default_factory=list)
    excluded_personas: list[str] = Field(default_factory=list)
    location_policy: LocationPolicy
    manual_review_conditions: list[str] = Field(default_factory=list)


class CampaignConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    enabled: bool
    platforms: list[str] = Field(min_length=1)
    service_mode: ServiceMode
    source_strategy: dict[str, Any]
    qualification_policy: QualificationPolicy
    version: str = Field(min_length=1)


class LocationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: LocationEvidenceSource
    raw_value: str
    normalized_country: str | None = None
    normalized_province: str | None = None
    normalized_city: str | None = None
    normalized_district: str | None = None
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    evidence_text: str


class LocationQualificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolved_location: dict[str, str | None] = Field(default_factory=dict)
    match_status: LocationMatchStatus
    reason: str
    confidence: float
    evidence: list[LocationEvidence] = Field(default_factory=list)


class QualificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: QualificationDecision
    reason_codes: list[str]
    human_readable_reason: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    policy_version: str
    location: LocationQualificationResult
