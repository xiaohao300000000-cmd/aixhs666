from __future__ import annotations

from collections.abc import Iterable

from intelligence.platform_evaluation import PlatformCandidate, PlatformEvaluationReport, evaluate_platforms


def build_worker_second_platform_evaluation(
    candidates: Iterable[PlatformCandidate] | None = None,
) -> PlatformEvaluationReport:
    return evaluate_platforms(candidates)
