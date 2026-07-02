from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from intelligence.scoring import QuerySourceScore


@dataclass(frozen=True, slots=True)
class DailyDashboardMetric:
    metric_date: date
    new_content_count: int = 0
    new_comment_count: int = 0
    new_profile_count: int = 0
    observed_content_count: int = 0
    duplicate_content_count: int = 0


@dataclass(frozen=True, slots=True)
class QueryOutputMetric:
    query_id: str
    query_text: str
    new_content_count: int = 0
    discovery_count: int = 0
    task_count: int = 0
    failed_task_count: int = 0


@dataclass(frozen=True, slots=True)
class PhraseReviewMetric:
    metric_date: date
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    converted_to_query_count: int = 0


@dataclass(frozen=True, slots=True)
class FailedTaskMetric:
    task_type: str
    platform: str
    failed_count: int
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class FieldCompletenessMetric:
    entity_type: str
    field_name: str
    present_count: int
    total_count: int


@dataclass(frozen=True, slots=True)
class DashboardInput:
    daily_metrics: tuple[DailyDashboardMetric, ...] = ()
    query_outputs: tuple[QueryOutputMetric, ...] = ()
    source_scores: tuple[QuerySourceScore, ...] = ()
    phrase_reviews: tuple[PhraseReviewMetric, ...] = ()
    failed_tasks: tuple[FailedTaskMetric, ...] = ()
    field_completeness: tuple[FieldCompletenessMetric, ...] = ()
    generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DashboardTotals:
    new_content_count: int
    new_comment_count: int
    new_profile_count: int
    observed_content_count: int
    duplicate_content_count: int
    task_count: int
    failed_task_count: int


@dataclass(frozen=True, slots=True)
class QueryOutputSummary:
    query_id: str
    query_text: str
    new_content_count: int
    discovery_count: int
    task_count: int
    failed_task_count: int
    failure_rate: float


@dataclass(frozen=True, slots=True)
class PhraseReviewSummary:
    pending_count: int
    approved_count: int
    rejected_count: int
    converted_to_query_count: int
    total_candidate_count: int


@dataclass(frozen=True, slots=True)
class FieldCompletenessSummary:
    entity_type: str
    field_name: str
    present_count: int
    total_count: int
    completeness_rate: float


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    generated_at: datetime
    date_from: date | None
    date_to: date | None
    totals: DashboardTotals
    duplicate_rate: float
    failure_rate: float
    daily_new: tuple[DailyDashboardMetric, ...]
    query_output_rank: tuple[QueryOutputSummary, ...]
    source_score_rank: tuple[QuerySourceScore, ...]
    phrase_review: PhraseReviewSummary
    failed_tasks: tuple[FailedTaskMetric, ...]
    field_completeness: tuple[FieldCompletenessSummary, ...]
    overall_field_completeness_rate: float


def build_dashboard_summary(
    dashboard_input: DashboardInput,
    *,
    query_limit: int = 10,
    source_limit: int = 10,
    failed_task_limit: int = 10,
) -> DashboardSummary:
    _validate_input(dashboard_input)

    generated_at = dashboard_input.generated_at or datetime.now(timezone.utc)
    daily_new = tuple(sorted(dashboard_input.daily_metrics, key=lambda item: item.metric_date))
    query_output_rank = _rank_query_outputs(dashboard_input.query_outputs, limit=query_limit)
    source_score_rank = tuple(
        sorted(
            dashboard_input.source_scores,
            key=lambda score: (
                -score.task_value_score,
                score.failure_rate,
                score.duplicate_rate,
                score.target_type.value,
                score.target_id,
            ),
        )[:source_limit]
    )
    failed_tasks = tuple(
        sorted(
            dashboard_input.failed_tasks,
            key=lambda item: (-item.failed_count, item.platform, item.task_type),
        )[:failed_task_limit]
    )
    field_completeness = _summarize_field_completeness(dashboard_input.field_completeness)

    totals = _build_totals(
        daily_metrics=dashboard_input.daily_metrics,
        query_outputs=dashboard_input.query_outputs,
    )
    phrase_review = _summarize_phrase_reviews(dashboard_input.phrase_reviews)

    return DashboardSummary(
        generated_at=generated_at,
        date_from=daily_new[0].metric_date if daily_new else None,
        date_to=daily_new[-1].metric_date if daily_new else None,
        totals=totals,
        duplicate_rate=_rate(totals.duplicate_content_count, totals.observed_content_count),
        failure_rate=_rate(totals.failed_task_count, totals.task_count),
        daily_new=daily_new,
        query_output_rank=query_output_rank,
        source_score_rank=source_score_rank,
        phrase_review=phrase_review,
        failed_tasks=failed_tasks,
        field_completeness=field_completeness,
        overall_field_completeness_rate=_rate(
            sum(item.present_count for item in field_completeness),
            sum(item.total_count for item in field_completeness),
        ),
    )


def dashboard_summary_to_dict(summary: DashboardSummary) -> dict[str, object]:
    return asdict(summary)


def _build_totals(
    *,
    daily_metrics: Iterable[DailyDashboardMetric],
    query_outputs: Iterable[QueryOutputMetric],
) -> DashboardTotals:
    daily_items = tuple(daily_metrics)
    query_items = tuple(query_outputs)
    return DashboardTotals(
        new_content_count=sum(item.new_content_count for item in daily_items),
        new_comment_count=sum(item.new_comment_count for item in daily_items),
        new_profile_count=sum(item.new_profile_count for item in daily_items),
        observed_content_count=sum(item.observed_content_count for item in daily_items),
        duplicate_content_count=sum(item.duplicate_content_count for item in daily_items),
        task_count=sum(item.task_count for item in query_items),
        failed_task_count=sum(item.failed_task_count for item in query_items),
    )


def _rank_query_outputs(
    query_outputs: Iterable[QueryOutputMetric],
    *,
    limit: int,
) -> tuple[QueryOutputSummary, ...]:
    summaries = [
        QueryOutputSummary(
            query_id=item.query_id,
            query_text=item.query_text,
            new_content_count=item.new_content_count,
            discovery_count=item.discovery_count,
            task_count=item.task_count,
            failed_task_count=item.failed_task_count,
            failure_rate=_rate(item.failed_task_count, item.task_count),
        )
        for item in query_outputs
    ]
    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                -item.new_content_count,
                -item.discovery_count,
                item.failure_rate,
                item.query_id,
            ),
        )[:limit]
    )


def _summarize_phrase_reviews(phrase_reviews: Iterable[PhraseReviewMetric]) -> PhraseReviewSummary:
    items = tuple(phrase_reviews)
    pending_count = sum(item.pending_count for item in items)
    approved_count = sum(item.approved_count for item in items)
    rejected_count = sum(item.rejected_count for item in items)
    converted_to_query_count = sum(item.converted_to_query_count for item in items)
    return PhraseReviewSummary(
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        converted_to_query_count=converted_to_query_count,
        total_candidate_count=pending_count + approved_count + rejected_count + converted_to_query_count,
    )


def _summarize_field_completeness(
    metrics: Iterable[FieldCompletenessMetric],
) -> tuple[FieldCompletenessSummary, ...]:
    summaries = [
        FieldCompletenessSummary(
            entity_type=item.entity_type,
            field_name=item.field_name,
            present_count=item.present_count,
            total_count=item.total_count,
            completeness_rate=_rate(item.present_count, item.total_count),
        )
        for item in metrics
    ]
    return tuple(
        sorted(
            summaries,
            key=lambda item: (item.completeness_rate, item.entity_type, item.field_name),
        )
    )


def _validate_input(dashboard_input: DashboardInput) -> None:
    for item in dashboard_input.daily_metrics:
        _validate_counts(
            item,
            (
                "new_content_count",
                "new_comment_count",
                "new_profile_count",
                "observed_content_count",
                "duplicate_content_count",
            ),
        )
        if item.duplicate_content_count > item.observed_content_count:
            raise ValueError("duplicate_content_count cannot exceed observed_content_count")

    for item in dashboard_input.query_outputs:
        if not item.query_id:
            raise ValueError("query_id is required")
        if not item.query_text:
            raise ValueError("query_text is required")
        _validate_counts(
            item,
            ("new_content_count", "discovery_count", "task_count", "failed_task_count"),
        )
        if item.failed_task_count > item.task_count:
            raise ValueError("failed_task_count cannot exceed task_count")

    for item in dashboard_input.phrase_reviews:
        _validate_counts(
            item,
            ("pending_count", "approved_count", "rejected_count", "converted_to_query_count"),
        )

    for item in dashboard_input.failed_tasks:
        if not item.task_type:
            raise ValueError("task_type is required")
        if not item.platform:
            raise ValueError("platform is required")
        _validate_counts(item, ("failed_count",))

    for item in dashboard_input.field_completeness:
        if not item.entity_type:
            raise ValueError("entity_type is required")
        if not item.field_name:
            raise ValueError("field_name is required")
        _validate_counts(item, ("present_count", "total_count"))
        if item.present_count > item.total_count:
            raise ValueError("present_count cannot exceed total_count")


def _validate_counts(item: object, field_names: tuple[str, ...]) -> None:
    for field_name in field_names:
        if int(getattr(item, field_name)) < 0:
            raise ValueError(f"{field_name} cannot be negative")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return min(1.0, max(0.0, numerator / denominator))
