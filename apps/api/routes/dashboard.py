from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.dashboard_metrics import build_database_dashboard_response
from intelligence.dashboard import (
    DailyDashboardMetric,
    DashboardInput,
    FailedTaskMetric,
    FieldCompletenessMetric,
    PhraseReviewMetric,
    QueryOutputMetric,
    build_dashboard_summary,
    dashboard_summary_to_dict,
)
from intelligence.scoring import QuerySourceScore
from storage.database import get_session

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
SessionDep = Annotated[Session, Depends(get_session)]


class DailyDashboardMetricPayload(BaseModel):
    metric_date: date
    new_content_count: int = Field(default=0, ge=0)
    new_comment_count: int = Field(default=0, ge=0)
    new_profile_count: int = Field(default=0, ge=0)
    observed_content_count: int = Field(default=0, ge=0)
    duplicate_content_count: int = Field(default=0, ge=0)


class QueryOutputMetricPayload(BaseModel):
    query_id: str
    query_text: str
    new_content_count: int = Field(default=0, ge=0)
    discovery_count: int = Field(default=0, ge=0)
    task_count: int = Field(default=0, ge=0)
    failed_task_count: int = Field(default=0, ge=0)


class PhraseReviewMetricPayload(BaseModel):
    metric_date: date
    pending_count: int = Field(default=0, ge=0)
    approved_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    converted_to_query_count: int = Field(default=0, ge=0)


class FailedTaskMetricPayload(BaseModel):
    task_type: str
    platform: str
    failed_count: int = Field(ge=0)
    last_error: str | None = None


class FieldCompletenessMetricPayload(BaseModel):
    entity_type: str
    field_name: str
    present_count: int = Field(ge=0)
    total_count: int = Field(ge=0)


class DashboardSummaryPayload(BaseModel):
    daily_metrics: list[DailyDashboardMetricPayload] = Field(default_factory=list)
    query_outputs: list[QueryOutputMetricPayload] = Field(default_factory=list)
    source_scores: list[QuerySourceScore] = Field(default_factory=list)
    phrase_reviews: list[PhraseReviewMetricPayload] = Field(default_factory=list)
    failed_tasks: list[FailedTaskMetricPayload] = Field(default_factory=list)
    field_completeness: list[FieldCompletenessMetricPayload] = Field(default_factory=list)
    generated_at: datetime | None = None


@router.post("/summary")
def summarize_dashboard(payload: DashboardSummaryPayload) -> dict[str, Any]:
    dashboard_input = DashboardInput(
        daily_metrics=tuple(DailyDashboardMetric(**item.model_dump()) for item in payload.daily_metrics),
        query_outputs=tuple(QueryOutputMetric(**item.model_dump()) for item in payload.query_outputs),
        source_scores=tuple(payload.source_scores),
        phrase_reviews=tuple(PhraseReviewMetric(**item.model_dump()) for item in payload.phrase_reviews),
        failed_tasks=tuple(FailedTaskMetric(**item.model_dump()) for item in payload.failed_tasks),
        field_completeness=tuple(
            FieldCompletenessMetric(**item.model_dump()) for item in payload.field_completeness
        ),
        generated_at=payload.generated_at,
    )
    return dashboard_summary_to_dict(build_dashboard_summary(dashboard_input))


@router.get("/summary")
def get_dashboard_summary(session: SessionDep) -> dict[str, Any]:
    return build_database_dashboard_response(session)
