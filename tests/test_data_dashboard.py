from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.worker.data_dashboard import build_worker_dashboard_summary
from intelligence.dashboard import (
    DailyDashboardMetric,
    DashboardInput,
    FailedTaskMetric,
    FieldCompletenessMetric,
    PhraseReviewMetric,
    QueryOutputMetric,
)
from intelligence.scoring import QuerySourceScore, ScoringTargetType


NOW = datetime(2026, 7, 2, 4, 30, tzinfo=timezone.utc)


def test_dashboard_summary_calculates_core_rates_and_totals() -> None:
    summary = build_worker_dashboard_summary(_dashboard_input())

    assert summary.date_from == date(2026, 7, 1)
    assert summary.date_to == date(2026, 7, 2)
    assert summary.totals.new_content_count == 12
    assert summary.totals.new_comment_count == 39
    assert summary.totals.new_profile_count == 7
    assert summary.duplicate_rate == pytest.approx(3 / 18)
    assert summary.failure_rate == pytest.approx(3 / 12)
    assert summary.phrase_review.total_candidate_count == 14
    assert summary.overall_field_completeness_rate == pytest.approx(35 / 40)


def test_dashboard_ranks_queries_sources_failed_tasks_and_field_gaps() -> None:
    summary = build_worker_dashboard_summary(_dashboard_input())

    assert [item.query_id for item in summary.query_output_rank] == ["q2", "q1"]
    assert summary.query_output_rank[0].failure_rate == pytest.approx(1 / 4)
    assert [item.target_id for item in summary.source_score_rank] == ["source-2", "source-1"]
    assert [item.task_type for item in summary.failed_tasks] == ["comments", "search"]
    assert [(item.entity_type, item.field_name) for item in summary.field_completeness] == [
        ("contents", "body_text"),
        ("contents", "title"),
    ]


def test_dashboard_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="duplicate_content_count"):
        build_worker_dashboard_summary(
            DashboardInput(
                daily_metrics=(
                    DailyDashboardMetric(
                        metric_date=date(2026, 7, 2),
                        observed_content_count=1,
                        duplicate_content_count=2,
                    ),
                )
            )
        )

    with pytest.raises(ValueError, match="present_count"):
        build_worker_dashboard_summary(
            DashboardInput(
                field_completeness=(
                    FieldCompletenessMetric(
                        entity_type="contents",
                        field_name="title",
                        present_count=2,
                        total_count=1,
                    ),
                )
            )
        )


def test_dashboard_api_returns_local_summary_without_database() -> None:
    client = TestClient(create_app())

    response = client.post("/dashboard/summary", json=_dashboard_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["generated_at"] == "2026-07-02T04:30:00Z"
    assert body["totals"]["new_content_count"] == 12
    assert body["duplicate_rate"] == pytest.approx(3 / 18)
    assert body["query_output_rank"][0]["query_id"] == "q2"
    assert body["source_score_rank"][0]["target_id"] == "source-2"
    assert body["phrase_review"]["converted_to_query_count"] == 2
    assert body["field_completeness"][0]["field_name"] == "body_text"


def _dashboard_input() -> DashboardInput:
    return DashboardInput(
        generated_at=NOW,
        daily_metrics=(
            DailyDashboardMetric(
                metric_date=date(2026, 7, 1),
                new_content_count=5,
                new_comment_count=17,
                new_profile_count=3,
                observed_content_count=8,
                duplicate_content_count=1,
            ),
            DailyDashboardMetric(
                metric_date=date(2026, 7, 2),
                new_content_count=7,
                new_comment_count=22,
                new_profile_count=4,
                observed_content_count=10,
                duplicate_content_count=2,
            ),
        ),
        query_outputs=(
            QueryOutputMetric(
                query_id="q1",
                query_text="福州 PET 求推荐",
                new_content_count=4,
                discovery_count=7,
                task_count=8,
                failed_task_count=2,
            ),
            QueryOutputMetric(
                query_id="q2",
                query_text="五年级 PET 二刷",
                new_content_count=8,
                discovery_count=9,
                task_count=4,
                failed_task_count=1,
            ),
        ),
        source_scores=(
            _source_score("source-1", 0.62),
            _source_score("source-2", 0.81),
        ),
        phrase_reviews=(
            PhraseReviewMetric(
                metric_date=date(2026, 7, 2),
                pending_count=3,
                approved_count=4,
                rejected_count=5,
                converted_to_query_count=2,
            ),
        ),
        failed_tasks=(
            FailedTaskMetric(task_type="search", platform="xhs", failed_count=2, last_error="timeout"),
            FailedTaskMetric(task_type="comments", platform="xhs", failed_count=5, last_error="blocked"),
        ),
        field_completeness=(
            FieldCompletenessMetric(
                entity_type="contents",
                field_name="title",
                present_count=18,
                total_count=18,
            ),
            FieldCompletenessMetric(
                entity_type="contents",
                field_name="body_text",
                present_count=17,
                total_count=22,
            ),
        ),
    )


def _source_score(target_id: str, score: float) -> QuerySourceScore:
    return QuerySourceScore(
        target_type=ScoringTargetType.SOURCE,
        target_id=target_id,
        label=target_id,
        new_content_rate=score,
        new_user_rate=score,
        new_expression_rate=score,
        duplicate_rate=0.1,
        failure_rate=0.0,
        task_value_score=score,
        reason="test score",
    )


def _dashboard_payload() -> dict[str, Any]:
    return {
        "generated_at": "2026-07-02T04:30:00Z",
        "daily_metrics": [
            {
                "metric_date": "2026-07-01",
                "new_content_count": 5,
                "new_comment_count": 17,
                "new_profile_count": 3,
                "observed_content_count": 8,
                "duplicate_content_count": 1,
            },
            {
                "metric_date": "2026-07-02",
                "new_content_count": 7,
                "new_comment_count": 22,
                "new_profile_count": 4,
                "observed_content_count": 10,
                "duplicate_content_count": 2,
            },
        ],
        "query_outputs": [
            {
                "query_id": "q1",
                "query_text": "福州 PET 求推荐",
                "new_content_count": 4,
                "discovery_count": 7,
                "task_count": 8,
                "failed_task_count": 2,
            },
            {
                "query_id": "q2",
                "query_text": "五年级 PET 二刷",
                "new_content_count": 8,
                "discovery_count": 9,
                "task_count": 4,
                "failed_task_count": 1,
            },
        ],
        "source_scores": [
            asdict(_source_score("source-1", 0.62)),
            asdict(_source_score("source-2", 0.81)),
        ],
        "phrase_reviews": [
            {
                "metric_date": "2026-07-02",
                "pending_count": 3,
                "approved_count": 4,
                "rejected_count": 5,
                "converted_to_query_count": 2,
            }
        ],
        "failed_tasks": [
            {"task_type": "search", "platform": "xhs", "failed_count": 2, "last_error": "timeout"},
            {"task_type": "comments", "platform": "xhs", "failed_count": 5, "last_error": "blocked"},
        ],
        "field_completeness": [
            {
                "entity_type": "contents",
                "field_name": "title",
                "present_count": 18,
                "total_count": 18,
            },
            {
                "entity_type": "contents",
                "field_name": "body_text",
                "present_count": 17,
                "total_count": 22,
            },
        ],
    }
