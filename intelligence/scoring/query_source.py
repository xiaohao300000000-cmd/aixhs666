from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class ScoringTargetType(StrEnum):
    QUERY = "query"
    SOURCE = "source"


@dataclass(frozen=True, slots=True)
class QuerySourceStats:
    target_type: ScoringTargetType
    target_id: str
    label: str
    observed_content_count: int = 0
    new_content_count: int = 0
    duplicate_content_count: int = 0
    observed_user_count: int = 0
    new_user_count: int = 0
    observed_expression_count: int = 0
    new_expression_count: int = 0
    task_count: int = 0
    failed_task_count: int = 0
    coverage_gap_value: float = 0.0
    context_completion_value: float = 0.0
    collection_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class QuerySourceScore:
    target_type: ScoringTargetType
    target_id: str
    label: str
    new_content_rate: float
    new_user_rate: float
    new_expression_rate: float
    duplicate_rate: float
    failure_rate: float
    task_value_score: float
    reason: str


def score_query_source(stats: QuerySourceStats) -> QuerySourceScore:
    _validate_stats(stats)

    new_content_rate = _rate(stats.new_content_count, stats.observed_content_count)
    new_user_rate = _rate(stats.new_user_count, stats.observed_user_count)
    new_expression_rate = _rate(stats.new_expression_count, stats.observed_expression_count)
    duplicate_rate = _rate(stats.duplicate_content_count, stats.observed_content_count)
    failure_rate = _rate(stats.failed_task_count, stats.task_count)
    coverage_gap_value = _clamp_rate(stats.coverage_gap_value)
    context_completion_value = _clamp_rate(stats.context_completion_value)
    collection_cost = _clamp_rate(stats.collection_cost)

    value = (
        0.30 * new_content_rate
        + 0.20 * new_user_rate
        + 0.20 * new_expression_rate
        + 0.15 * coverage_gap_value
        + 0.15 * context_completion_value
        - 0.20 * duplicate_rate
        - 0.15 * collection_cost
        - 0.15 * failure_rate
    )
    task_value_score = round(_clamp_rate(value), 6)

    return QuerySourceScore(
        target_type=stats.target_type,
        target_id=stats.target_id,
        label=stats.label,
        new_content_rate=new_content_rate,
        new_user_rate=new_user_rate,
        new_expression_rate=new_expression_rate,
        duplicate_rate=duplicate_rate,
        failure_rate=failure_rate,
        task_value_score=task_value_score,
        reason=_build_reason(
            new_content_rate=new_content_rate,
            new_user_rate=new_user_rate,
            new_expression_rate=new_expression_rate,
            duplicate_rate=duplicate_rate,
            failure_rate=failure_rate,
            coverage_gap_value=coverage_gap_value,
            context_completion_value=context_completion_value,
            collection_cost=collection_cost,
            task_value_score=task_value_score,
        ),
    )


def rank_query_sources(stats_items: Iterable[QuerySourceStats]) -> list[QuerySourceScore]:
    scores = [score_query_source(stats) for stats in stats_items]
    return sorted(
        scores,
        key=lambda score: (
            -score.task_value_score,
            score.failure_rate,
            score.duplicate_rate,
            score.target_type.value,
            score.target_id,
        ),
    )


def _validate_stats(stats: QuerySourceStats) -> None:
    if not stats.target_id:
        raise ValueError("target_id is required")
    if not stats.label:
        raise ValueError("label is required")

    count_fields = (
        "observed_content_count",
        "new_content_count",
        "duplicate_content_count",
        "observed_user_count",
        "new_user_count",
        "observed_expression_count",
        "new_expression_count",
        "task_count",
        "failed_task_count",
    )
    for field_name in count_fields:
        if int(getattr(stats, field_name)) < 0:
            raise ValueError(f"{field_name} cannot be negative")

    if stats.new_content_count > stats.observed_content_count:
        raise ValueError("new_content_count cannot exceed observed_content_count")
    if stats.duplicate_content_count > stats.observed_content_count:
        raise ValueError("duplicate_content_count cannot exceed observed_content_count")
    if stats.new_user_count > stats.observed_user_count:
        raise ValueError("new_user_count cannot exceed observed_user_count")
    if stats.new_expression_count > stats.observed_expression_count:
        raise ValueError("new_expression_count cannot exceed observed_expression_count")
    if stats.failed_task_count > stats.task_count:
        raise ValueError("failed_task_count cannot exceed task_count")


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return _clamp_rate(numerator / denominator)


def _clamp_rate(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _build_reason(
    *,
    new_content_rate: float,
    new_user_rate: float,
    new_expression_rate: float,
    duplicate_rate: float,
    failure_rate: float,
    coverage_gap_value: float,
    context_completion_value: float,
    collection_cost: float,
    task_value_score: float,
) -> str:
    return (
        "task_value_score="
        f"{task_value_score:.3f}; "
        "formula=0.30*new_content_rate + 0.20*new_user_rate + "
        "0.20*new_expression_rate + 0.15*coverage_gap_value + "
        "0.15*context_completion_value - 0.20*duplicate_rate - "
        "0.15*collection_cost - 0.15*failure_rate; "
        f"rates=new_content:{new_content_rate:.3f}, "
        f"new_user:{new_user_rate:.3f}, "
        f"new_expression:{new_expression_rate:.3f}, "
        f"duplicate:{duplicate_rate:.3f}, "
        f"failure:{failure_rate:.3f}; "
        f"values=coverage_gap:{coverage_gap_value:.3f}, "
        f"context_completion:{context_completion_value:.3f}, "
        f"collection_cost:{collection_cost:.3f}"
    )
