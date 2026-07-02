from __future__ import annotations

from collections.abc import Iterable

from intelligence.content_insights import ContentInsightInput, ContentInsightReport, generate_content_insights
from intelligence.dashboard import DashboardSummary
from intelligence.phrase_discovery import PhraseCandidate


def build_worker_content_insights(
    items: Iterable[ContentInsightInput],
    *,
    dashboard_summary: DashboardSummary | None = None,
    phrase_candidates: Iterable[PhraseCandidate | str] = (),
) -> ContentInsightReport:
    return generate_content_insights(
        items,
        dashboard_summary=dashboard_summary,
        phrase_candidates=phrase_candidates,
    )
