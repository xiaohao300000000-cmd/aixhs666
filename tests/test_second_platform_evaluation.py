from __future__ import annotations

import pytest

from apps.worker.platform_evaluation import build_worker_second_platform_evaluation
from intelligence.platform_evaluation import EvaluationCost, PlatformCandidate, evaluate_platforms, generate_access_plan


def test_second_platform_evaluation_scores_all_required_platforms() -> None:
    report = build_worker_second_platform_evaluation()

    names = [candidate.name for candidate in report.candidates]
    ranked_names = [evaluation.platform_name for evaluation in report.evaluations]

    assert names == ["知乎", "搜索引擎", "抖音", "B站", "微博"]
    assert set(ranked_names) == set(names)
    assert [evaluation.priority for evaluation in report.evaluations] == [1, 2, 3, 4, 5]
    assert [evaluation.total_score for evaluation in report.evaluations] == sorted(
        [evaluation.total_score for evaluation in report.evaluations],
        reverse=True,
    )


def test_second_platform_recommendation_is_explainable_and_includes_costs() -> None:
    report = build_worker_second_platform_evaluation()
    recommendation = report.evaluations[0]

    assert report.recommended_platform == "知乎"
    assert report.recommendation_reason == recommendation.reason
    assert recommendation.strengths
    assert recommendation.risks
    assert recommendation.estimated_cost.engineering_days_min > 0
    assert "data_density=" in recommendation.reason
    assert "collection_complexity=" in recommendation.reason


def test_second_platform_access_plan_contains_validation_steps_and_metrics() -> None:
    report = build_worker_second_platform_evaluation()
    plan = report.access_plan

    assert plan.platform_name == report.recommended_platform
    assert len(plan.minimum_validation_steps) >= 4
    assert any("L0" in step for step in plan.minimum_validation_steps)
    assert "engineering days" in plan.estimated_workload
    assert any("duplicate rate" in metric for metric in plan.acceptance_metrics)
    assert any("context" in metric for metric in plan.acceptance_metrics)


def test_custom_candidates_keep_stable_tie_breaking() -> None:
    cost = EvaluationCost(
        engineering_days_min=5,
        engineering_days_max=7,
        monthly_operating_cost_cny=500,
        browser_minutes_per_1000_items=70,
    )
    report = evaluate_platforms(
        (
            PlatformCandidate("Beta", 0.7, 0.7, 0.7, 0.5, 0.7, cost),
            PlatformCandidate("Alpha", 0.7, 0.7, 0.7, 0.5, 0.7, cost),
        )
    )

    assert [evaluation.platform_name for evaluation in report.evaluations] == ["Alpha", "Beta"]


def test_invalid_candidate_metrics_are_rejected() -> None:
    invalid = PlatformCandidate(
        name="无效平台",
        data_density=1.2,
        public_accessibility=0.5,
        context_completeness=0.5,
        collection_complexity=0.5,
        content_insight_value=0.5,
        estimated_cost=EvaluationCost(
            engineering_days_min=1,
            engineering_days_max=2,
            monthly_operating_cost_cny=0,
            browser_minutes_per_1000_items=0,
        ),
    )

    with pytest.raises(ValueError, match="data_density"):
        evaluate_platforms((invalid,))


def test_access_plan_can_be_generated_for_any_evaluation() -> None:
    report = build_worker_second_platform_evaluation()
    plan = generate_access_plan(report.evaluations[-1])

    assert plan.platform_name == report.evaluations[-1].platform_name
    assert plan.acceptance_metrics
