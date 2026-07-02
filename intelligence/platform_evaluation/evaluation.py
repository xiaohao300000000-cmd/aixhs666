from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class EvaluationCost:
    engineering_days_min: int
    engineering_days_max: int
    monthly_operating_cost_cny: int
    browser_minutes_per_1000_items: int


@dataclass(frozen=True, slots=True)
class PlatformCandidate:
    name: str
    data_density: float
    public_accessibility: float
    context_completeness: float
    collection_complexity: float
    content_insight_value: float
    estimated_cost: EvaluationCost


@dataclass(frozen=True, slots=True)
class PlatformEvaluation:
    platform_name: str
    total_score: float
    priority: int
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    estimated_cost: EvaluationCost
    reason: str


@dataclass(frozen=True, slots=True)
class AccessPlan:
    platform_name: str
    minimum_validation_steps: tuple[str, ...]
    estimated_workload: str
    acceptance_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlatformEvaluationReport:
    candidates: tuple[PlatformCandidate, ...]
    evaluations: tuple[PlatformEvaluation, ...]
    recommended_platform: str
    recommendation_reason: str
    access_plan: AccessPlan


_WEIGHTS = {
    "data_density": 0.24,
    "public_accessibility": 0.18,
    "context_completeness": 0.18,
    "collection_complexity": 0.16,
    "content_insight_value": 0.18,
    "cost": 0.06,
}


def evaluate_platforms(candidates: Iterable[PlatformCandidate] | None = None) -> PlatformEvaluationReport:
    platform_candidates = tuple(candidates) if candidates is not None else default_platform_candidates()
    if not platform_candidates:
        raise ValueError("at least one platform candidate is required")

    evaluations = tuple(
        sorted(
            (_evaluate_candidate(candidate) for candidate in platform_candidates),
            key=lambda item: (-item.total_score, item.estimated_cost.engineering_days_min, item.platform_name),
        )
    )
    prioritized = tuple(
        PlatformEvaluation(
            platform_name=evaluation.platform_name,
            total_score=evaluation.total_score,
            priority=index + 1,
            strengths=evaluation.strengths,
            risks=evaluation.risks,
            estimated_cost=evaluation.estimated_cost,
            reason=evaluation.reason,
        )
        for index, evaluation in enumerate(evaluations)
    )
    recommendation = recommend_second_platform(prioritized)
    return PlatformEvaluationReport(
        candidates=platform_candidates,
        evaluations=prioritized,
        recommended_platform=recommendation.platform_name,
        recommendation_reason=recommendation.reason,
        access_plan=generate_access_plan(recommendation),
    )


def recommend_second_platform(evaluations: Iterable[PlatformEvaluation]) -> PlatformEvaluation:
    ranked = tuple(
        sorted(
            evaluations,
            key=lambda item: (-item.total_score, item.estimated_cost.engineering_days_min, item.platform_name),
        )
    )
    if not ranked:
        raise ValueError("at least one platform evaluation is required")
    return ranked[0]


def generate_access_plan(evaluation: PlatformEvaluation) -> AccessPlan:
    return AccessPlan(
        platform_name=evaluation.platform_name,
        minimum_validation_steps=_validation_steps(evaluation.platform_name),
        estimated_workload=(
            f"{evaluation.estimated_cost.engineering_days_min}-"
            f"{evaluation.estimated_cost.engineering_days_max} engineering days; "
            f"~{evaluation.estimated_cost.monthly_operating_cost_cny} CNY/month operating cost"
        ),
        acceptance_metrics=(
            "single seeded run can collect at least 100 public items with source links",
            "duplicate rate is below 25% on a repeated validation run",
            "at least 60% of collected items retain enough context for content insight generation",
            "no private, login-bypassed, or captcha-solving path is required",
        ),
    )


def default_platform_candidates() -> tuple[PlatformCandidate, ...]:
    return (
        PlatformCandidate(
            name="知乎",
            data_density=0.72,
            public_accessibility=0.78,
            context_completeness=0.86,
            collection_complexity=0.45,
            content_insight_value=0.88,
            estimated_cost=EvaluationCost(
                engineering_days_min=5,
                engineering_days_max=8,
                monthly_operating_cost_cny=500,
                browser_minutes_per_1000_items=80,
            ),
        ),
        PlatformCandidate(
            name="搜索引擎",
            data_density=0.66,
            public_accessibility=0.9,
            context_completeness=0.58,
            collection_complexity=0.38,
            content_insight_value=0.7,
            estimated_cost=EvaluationCost(
                engineering_days_min=4,
                engineering_days_max=7,
                monthly_operating_cost_cny=700,
                browser_minutes_per_1000_items=55,
            ),
        ),
        PlatformCandidate(
            name="抖音",
            data_density=0.82,
            public_accessibility=0.48,
            context_completeness=0.54,
            collection_complexity=0.82,
            content_insight_value=0.76,
            estimated_cost=EvaluationCost(
                engineering_days_min=9,
                engineering_days_max=14,
                monthly_operating_cost_cny=1800,
                browser_minutes_per_1000_items=180,
            ),
        ),
        PlatformCandidate(
            name="B站",
            data_density=0.58,
            public_accessibility=0.72,
            context_completeness=0.8,
            collection_complexity=0.58,
            content_insight_value=0.74,
            estimated_cost=EvaluationCost(
                engineering_days_min=7,
                engineering_days_max=11,
                monthly_operating_cost_cny=900,
                browser_minutes_per_1000_items=110,
            ),
        ),
        PlatformCandidate(
            name="微博",
            data_density=0.62,
            public_accessibility=0.55,
            context_completeness=0.46,
            collection_complexity=0.7,
            content_insight_value=0.52,
            estimated_cost=EvaluationCost(
                engineering_days_min=8,
                engineering_days_max=12,
                monthly_operating_cost_cny=1200,
                browser_minutes_per_1000_items=140,
            ),
        ),
    )


def _evaluate_candidate(candidate: PlatformCandidate) -> PlatformEvaluation:
    _validate_candidate(candidate)
    cost_score = _cost_score(candidate.estimated_cost)
    total_score = round(
        candidate.data_density * _WEIGHTS["data_density"]
        + candidate.public_accessibility * _WEIGHTS["public_accessibility"]
        + candidate.context_completeness * _WEIGHTS["context_completeness"]
        + (1.0 - candidate.collection_complexity) * _WEIGHTS["collection_complexity"]
        + candidate.content_insight_value * _WEIGHTS["content_insight_value"]
        + cost_score * _WEIGHTS["cost"],
        6,
    )
    return PlatformEvaluation(
        platform_name=candidate.name,
        total_score=total_score,
        priority=0,
        strengths=_strengths(candidate),
        risks=_risks(candidate),
        estimated_cost=candidate.estimated_cost,
        reason=(
            f"score={total_score}; data_density={candidate.data_density:.2f}; "
            f"public_accessibility={candidate.public_accessibility:.2f}; "
            f"context_completeness={candidate.context_completeness:.2f}; "
            f"collection_complexity={candidate.collection_complexity:.2f}; "
            f"content_insight_value={candidate.content_insight_value:.2f}; cost_score={cost_score:.2f}"
        ),
    )


def _strengths(candidate: PlatformCandidate) -> tuple[str, ...]:
    strengths: list[str] = []
    if candidate.data_density >= 0.7:
        strengths.append("教育需求内容密度较高")
    if candidate.public_accessibility >= 0.75:
        strengths.append("公开可访问性较好")
    if candidate.context_completeness >= 0.75:
        strengths.append("问答或评论上下文较完整")
    if candidate.content_insight_value >= 0.75:
        strengths.append("适合沉淀内容选题和需求洞察")
    if candidate.collection_complexity <= 0.45:
        strengths.append("采集实现复杂度较低")
    return tuple(strengths or ("综合指标均衡",))


def _risks(candidate: PlatformCandidate) -> tuple[str, ...]:
    risks: list[str] = []
    if candidate.public_accessibility < 0.6:
        risks.append("公开访问稳定性偏弱，需要先验证登录态和限流")
    if candidate.context_completeness < 0.6:
        risks.append("上下文可能碎片化，影响需求事件链和内容洞察")
    if candidate.collection_complexity > 0.65:
        risks.append("采集复杂度高，MVP 成本和失败率风险较高")
    if candidate.estimated_cost.monthly_operating_cost_cny > 1000:
        risks.append("预估运行成本较高")
    return tuple(risks or ("无明显高风险项",))


def _validation_steps(platform_name: str) -> tuple[str, ...]:
    return (
        f"整理 {platform_name} 的 20 个教育种子查询或种子来源",
        "用公开页面完成 L0 搜索或列表样本采集原型",
        "抽样补全正文、评论或问答上下文，记录缺失字段",
        "复跑同一批样本，统计新增率、重复率、失败率和上下文完整率",
        "用 T20 看板指标和 T21 内容洞察样例判断是否继续接入",
    )


def _cost_score(cost: EvaluationCost) -> float:
    engineering_score = 1.0 - min(1.0, max(0, cost.engineering_days_min - 4) / 10)
    monthly_score = 1.0 - min(1.0, cost.monthly_operating_cost_cny / 2500)
    browser_score = 1.0 - min(1.0, cost.browser_minutes_per_1000_items / 220)
    return round((engineering_score * 0.45) + (monthly_score * 0.35) + (browser_score * 0.2), 6)


def _validate_candidate(candidate: PlatformCandidate) -> None:
    for field_name in (
        "data_density",
        "public_accessibility",
        "context_completeness",
        "collection_complexity",
        "content_insight_value",
    ):
        value = getattr(candidate, field_name)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{field_name} must be between 0.0 and 1.0")
    if candidate.estimated_cost.engineering_days_min <= 0:
        raise ValueError("engineering_days_min must be positive")
    if candidate.estimated_cost.engineering_days_max < candidate.estimated_cost.engineering_days_min:
        raise ValueError("engineering_days_max must be greater than or equal to engineering_days_min")
    if candidate.estimated_cost.monthly_operating_cost_cny < 0:
        raise ValueError("monthly_operating_cost_cny must not be negative")
    if candidate.estimated_cost.browser_minutes_per_1000_items < 0:
        raise ValueError("browser_minutes_per_1000_items must not be negative")
