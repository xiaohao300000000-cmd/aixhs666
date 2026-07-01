from __future__ import annotations

import pytest

from intelligence.scoring import QuerySourceStats, rank_query_sources, score_query_source
from intelligence.scoring.query_source import ScoringTargetType


def test_score_calculates_rates_and_explainable_task_value() -> None:
    score = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.QUERY,
            target_id="query-pet-fuzhou",
            label="福州 PET 求推荐",
            observed_content_count=10,
            new_content_count=6,
            duplicate_content_count=2,
            observed_user_count=8,
            new_user_count=4,
            observed_expression_count=5,
            new_expression_count=2,
            task_count=10,
            failed_task_count=1,
            coverage_gap_value=0.5,
            context_completion_value=0.4,
            collection_cost=0.2,
        )
    )

    assert score.new_content_rate == pytest.approx(0.6)
    assert score.new_user_rate == pytest.approx(0.5)
    assert score.new_expression_rate == pytest.approx(0.4)
    assert score.duplicate_rate == pytest.approx(0.2)
    assert score.failure_rate == pytest.approx(0.1)
    assert score.task_value_score == pytest.approx(0.41)
    assert "0.30*new_content_rate" in score.reason
    assert "duplicate:0.200" in score.reason
    assert "failure:0.100" in score.reason


def test_high_duplicate_and_failure_rates_reduce_score() -> None:
    productive = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.SOURCE,
            target_id="content-note-1",
            label="高价值帖子",
            observed_content_count=20,
            new_content_count=16,
            duplicate_content_count=1,
            observed_user_count=20,
            new_user_count=14,
            observed_expression_count=10,
            new_expression_count=7,
            task_count=10,
            failed_task_count=0,
            coverage_gap_value=0.7,
            context_completion_value=0.6,
            collection_cost=0.2,
        )
    )
    noisy = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.SOURCE,
            target_id="content-note-2",
            label="重复且失败来源",
            observed_content_count=20,
            new_content_count=16,
            duplicate_content_count=12,
            observed_user_count=20,
            new_user_count=14,
            observed_expression_count=10,
            new_expression_count=7,
            task_count=10,
            failed_task_count=6,
            coverage_gap_value=0.7,
            context_completion_value=0.6,
            collection_cost=0.2,
        )
    )

    assert productive.task_value_score > noisy.task_value_score
    assert noisy.duplicate_rate == pytest.approx(0.6)
    assert noisy.failure_rate == pytest.approx(0.6)


def test_high_new_content_user_and_expression_rates_raise_score() -> None:
    weak = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.QUERY,
            target_id="query-low",
            label="低产查询",
            observed_content_count=20,
            new_content_count=2,
            observed_user_count=20,
            new_user_count=2,
            observed_expression_count=10,
            new_expression_count=1,
            task_count=5,
            failed_task_count=0,
        )
    )
    strong = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.QUERY,
            target_id="query-high",
            label="高产查询",
            observed_content_count=20,
            new_content_count=18,
            observed_user_count=20,
            new_user_count=16,
            observed_expression_count=10,
            new_expression_count=8,
            task_count=5,
            failed_task_count=0,
        )
    )

    assert strong.task_value_score > weak.task_value_score
    assert strong.new_content_rate == pytest.approx(0.9)
    assert strong.new_user_rate == pytest.approx(0.8)
    assert strong.new_expression_rate == pytest.approx(0.8)


def test_rank_query_sources_orders_by_value_with_penalty_tiebreakers() -> None:
    low = QuerySourceStats(
        target_type=ScoringTargetType.QUERY,
        target_id="low",
        label="低价值",
        observed_content_count=10,
        new_content_count=1,
        observed_user_count=10,
        new_user_count=1,
        observed_expression_count=10,
        new_expression_count=1,
    )
    best = QuerySourceStats(
        target_type=ScoringTargetType.SOURCE,
        target_id="best",
        label="最佳来源",
        observed_content_count=10,
        new_content_count=9,
        observed_user_count=10,
        new_user_count=8,
        observed_expression_count=10,
        new_expression_count=7,
        task_count=10,
        failed_task_count=0,
        coverage_gap_value=0.5,
    )
    tied_but_failed = QuerySourceStats(
        target_type=ScoringTargetType.SOURCE,
        target_id="failed",
        label="同分但失败率更高",
        observed_content_count=10,
        new_content_count=9,
        observed_user_count=10,
        new_user_count=8,
        observed_expression_count=10,
        new_expression_count=7,
        task_count=10,
        failed_task_count=5,
        coverage_gap_value=1.0,
    )

    ranked = rank_query_sources((low, tied_but_failed, best))

    assert [score.target_id for score in ranked] == ["best", "failed", "low"]


def test_empty_denominators_score_as_zero_rates() -> None:
    score = score_query_source(
        QuerySourceStats(
            target_type=ScoringTargetType.QUERY,
            target_id="empty",
            label="无采样",
        )
    )

    assert score.new_content_rate == 0.0
    assert score.new_user_rate == 0.0
    assert score.new_expression_rate == 0.0
    assert score.duplicate_rate == 0.0
    assert score.failure_rate == 0.0
    assert score.task_value_score == 0.0


def test_invalid_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="new_content_count"):
        score_query_source(
            QuerySourceStats(
                target_type=ScoringTargetType.QUERY,
                target_id="invalid",
                label="非法统计",
                observed_content_count=1,
                new_content_count=2,
            )
        )
