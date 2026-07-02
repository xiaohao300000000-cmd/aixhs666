from __future__ import annotations

from datetime import date, datetime, timezone

from apps.worker.content_insights import build_worker_content_insights
from intelligence.content_insights import ContentInsightInput
from intelligence.dashboard import DailyDashboardMetric, DashboardInput, build_dashboard_summary
from intelligence.phrase_discovery import PhraseCandidate


NOW = datetime(2026, 7, 2, 5, 30, tzinfo=timezone.utc)


def test_content_insights_generates_frequent_questions_and_anxieties() -> None:
    report = build_worker_content_insights(
        _inputs(),
        dashboard_summary=_dashboard(),
        phrase_candidates=(_candidate("二刷"), _candidate("压线")),
    )

    assert report.frequent_questions
    assert report.emerging_anxieties
    assert any("PET" in item.title or "二刷" in item.title for item in report.frequent_questions)
    assert any("压线" in item.title or "二刷" in item.title for item in report.emerging_anxieties)
    assert all(item.reason for item in report.frequent_questions)
    assert all(item.examples for item in report.emerging_anxieties)


def test_content_insights_generates_topics_lead_magnets_and_live_streams() -> None:
    report = build_worker_content_insights(
        _inputs(),
        dashboard_summary=_dashboard(),
        phrase_candidates=("二刷", "压线", "试听"),
    )

    assert report.content_topics[0].title.startswith("选题:")
    assert report.lead_magnet_topics[0].title.startswith("资料包:")
    assert report.live_stream_topics[0].title.startswith("直播:")
    assert "new_content=12" in report.content_topics[0].reason
    assert len({item.title for item in report.content_topics}) == len(report.content_topics)


def test_content_insights_outputs_local_demand_differences() -> None:
    report = build_worker_content_insights(_inputs(), phrase_candidates=("二刷", "压线", "试听"))

    by_region = {item.region: item for item in report.local_demand_differences}

    assert "福州" in by_region
    assert "厦门" in by_region
    assert by_region["福州"].top_terms
    assert by_region["福州"].reason


def test_content_insights_is_stable_and_deduplicates_repeated_terms() -> None:
    report = build_worker_content_insights(
        [
            ContentInsightInput(
                text="福州 PET 二刷 二刷 压线，求推荐机构",
                occurred_at=NOW,
                region="福州",
                exam="PET",
                source_score=0.8,
                candidate_phrases=("二刷", "二刷", "压线"),
            ),
            ContentInsightInput(
                text="福州 PET 二刷压线，价格多少？",
                occurred_at=NOW,
                region="福州",
                exam="PET",
                source_score=0.8,
                candidate_phrases=("二刷", "压线"),
            ),
        ],
        phrase_candidates=("二刷", "二刷", "压线"),
    )

    titles = [item.title for item in report.content_topics]
    assert titles == sorted(titles, key=lambda title: next(item.score for item in report.content_topics if item.title == title), reverse=True)
    assert len(titles) == len(set(titles))


def _inputs() -> list[ContentInsightInput]:
    return [
        ContentInsightInput(
            text="福州五年级 PET 二刷压线，求推荐机构，价格多少？",
            occurred_at=NOW,
            region="福州",
            exam="PET",
            source_score=0.9,
            candidate_phrases=("二刷", "压线"),
        ),
        ContentInsightInput(
            text="福州 PET 没过准备二刷，有没有试听课？",
            occurred_at=NOW,
            region="福州",
            exam="PET",
            source_score=0.8,
            candidate_phrases=("二刷", "试听"),
        ),
        ContentInsightInput(
            text="厦门分班考来不及，孩子英语跟不上怎么办？",
            occurred_at=NOW,
            region="厦门",
            exam="分班考",
            source_score=0.7,
            candidate_phrases=("分班考", "跟不上"),
        ),
        ContentInsightInput(
            text="厦门英孚英语不满意想退费，有没有避坑建议？",
            occurred_at=NOW,
            region="厦门",
            institution="英孚英语",
            source_score=0.75,
            candidate_phrases=("退费", "避坑"),
        ),
    ]


def _candidate(phrase: str) -> PhraseCandidate:
    return PhraseCandidate(
        phrase=phrase,
        source_text_count=2,
        novelty_score=0.7,
        query_potential_score=0.8,
        representative_examples=("example",),
    )


def _dashboard():
    return build_dashboard_summary(
        DashboardInput(
            daily_metrics=(
                DailyDashboardMetric(
                    metric_date=date(2026, 7, 2),
                    new_content_count=12,
                    new_comment_count=38,
                    new_profile_count=6,
                    observed_content_count=15,
                    duplicate_content_count=2,
                ),
            ),
            generated_at=NOW,
        )
    )
