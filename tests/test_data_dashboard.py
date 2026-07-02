from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
import storage.models  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dashboard_metrics import build_database_dashboard_response
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
from scheduler import TaskStatus, create_task
from storage.database import Base, get_session
from storage.models import CollectionEvent, Comment, Content, DiscoveryRelation, PublicProfile, Query


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


def test_database_dashboard_summary_reads_current_database_state() -> None:
    with _dashboard_session() as session:
        _seed_dashboard_database(session)

        response = build_database_dashboard_response(session, now=NOW)

    assert response["generated_at"] == NOW
    assert response["totals"]["new_content_count"] == 2
    assert response["totals"]["new_comment_count"] == 2
    assert response["totals"]["new_profile_count"] == 2
    assert response["totals"]["observed_content_count"] == 3
    assert response["totals"]["duplicate_content_count"] == 1
    assert response["duplicate_rate"] == pytest.approx(1 / 3)
    assert response["query_output_rank"][0]["query_text"] == "PET 二刷"
    assert response["query_output_rank"][0]["new_content_count"] == 2
    assert response["query_output_rank"][0]["task_count"] == 2
    assert response["query_output_rank"][0]["failed_task_count"] == 1
    assert response["failure_rate"] == pytest.approx(2 / 5)
    assert response["failed_tasks"][0]["failed_count"] == 2
    assert response["phrase_review"]["pending_count"] == 1
    assert response["phrase_review"]["approved_count"] == 1
    assert response["phrase_review"]["converted_to_query_count"] == 1
    assert response["database_metrics"]["high_value_signal_count"] == 1
    assert response["database_metrics"]["pending_phrase_count"] == 1
    assert response["database_metrics"]["latest_successful_collection_at"] == NOW - timedelta(minutes=1)
    assert response["database_metrics"]["latest_failure_reason"] == "selector changed"
    assert response["database_metrics"]["partial_task_count"] == 1
    assert response["database_metrics"]["retry_task_count"] == 1


def test_dashboard_get_endpoint_reads_database() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    with SessionLocal() as session:
        _seed_dashboard_database(session, now=datetime.now(UTC))

    def override_get_session() -> Iterator[Session]:
        with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            response = client.get("/dashboard/summary")
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["new_content_count"] >= 2
    assert body["database_metrics"]["high_value_signal_count"] == 1
    assert body["query_output_rank"][0]["query_text"] == "PET 二刷"


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


@contextmanager
def _dashboard_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_dashboard_database(session: Session, *, now: datetime = NOW) -> None:
    old_time = now - timedelta(days=2)
    q1 = Query(query_text="PET 二刷", platform="xhs", query_type="seed", status="active")
    q2 = Query(query_text="孩子英语跟不上", platform="xhs", query_type="seed", status="active")
    author_1 = PublicProfile(
        platform="xhs",
        platform_user_id="u1",
        display_name="A",
        profile_url="https://xhs.example/u1",
        first_seen_at=now,
        last_seen_at=now,
    )
    author_2 = PublicProfile(
        platform="xhs",
        platform_user_id="u2",
        display_name="B",
        first_seen_at=now,
        last_seen_at=now,
    )
    old_author = PublicProfile(
        platform="xhs",
        platform_user_id="u-old",
        display_name="Old",
        first_seen_at=old_time,
        last_seen_at=old_time,
    )
    content_1 = Content(
        platform="xhs",
        platform_content_id="n1",
        content_type="note",
        author_profile=author_1,
        title="PET 二刷复盘",
        body_text="二刷经验",
        url="https://xhs.example/n1",
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )
    content_2 = Content(
        platform="xhs",
        platform_content_id="n2",
        content_type="note",
        author_profile=author_2,
        title="英语跟不上",
        first_seen_at=now,
        last_seen_at=now,
    )
    old_content = Content(
        platform="xhs",
        platform_content_id="n-old",
        content_type="note",
        author_profile=old_author,
        title="旧内容",
        first_seen_at=old_time,
        last_seen_at=old_time,
    )
    session.add_all([q1, q2, author_1, author_2, old_author, content_1, content_2, old_content])
    session.flush()

    session.add_all(
        [
            DiscoveryRelation(query_id=q1.id, content_id=content_1.id, discovered_at=now, discovery_method="search"),
            DiscoveryRelation(query_id=q1.id, content_id=content_2.id, discovered_at=now, discovery_method="search"),
            DiscoveryRelation(query_id=q2.id, content_id=content_1.id, discovered_at=now, discovery_method="search"),
            DiscoveryRelation(query_id=q2.id, content_id=old_content.id, discovered_at=old_time, discovery_method="search"),
            Comment(
                platform="xhs",
                platform_comment_id="c1",
                content_id=content_1.id,
                author_profile_id=author_2.id,
                body_text="有帮助",
                published_at=now,
                first_seen_at=now,
                last_seen_at=now,
            ),
            Comment(
                platform="xhs",
                platform_comment_id="c2",
                content_id=content_2.id,
                body_text="求推荐",
                first_seen_at=now,
                last_seen_at=now,
            ),
            Comment(
                platform="xhs",
                platform_comment_id="c-old",
                content_id=old_content.id,
                body_text="旧评论",
                first_seen_at=old_time,
                last_seen_at=old_time,
            ),
        ]
    )
    session.flush()

    completed = create_task(session, task_type="search", platform="xhs", query_id=q1.id, now=now - timedelta(minutes=3))
    completed.status = TaskStatus.COMPLETED.value
    completed.finished_at = now - timedelta(minutes=1)
    failed_1 = create_task(session, task_type="search", platform="xhs", query_id=q1.id, now=now - timedelta(minutes=4))
    failed_1.status = TaskStatus.FAILED.value
    failed_1.finished_at = now - timedelta(minutes=2)
    failed_1.last_error = "timeout"
    failed_2 = create_task(session, task_type="search", platform="xhs", query_id=q2.id, now=now - timedelta(minutes=2))
    failed_2.status = TaskStatus.FAILED.value
    failed_2.finished_at = now - timedelta(seconds=30)
    failed_2.last_error = "selector changed"
    partial = create_task(session, task_type="comments", platform="xhs", query_id=q2.id, now=now - timedelta(minutes=5))
    partial.status = TaskStatus.PARTIAL.value
    partial.finished_at = now - timedelta(minutes=4)
    partial.last_error = "page timeout"
    retry = create_task(session, task_type="profile", platform="xhs", query_id=q2.id, now=now - timedelta(minutes=6))
    retry.status = TaskStatus.RETRY.value
    retry.last_error = "login required"
    session.add_all(
        [
            CollectionEvent(
                event_type="feishu_phrase_review_callback",
                entity_type="phrase_candidate",
                entity_id=0,
                event_data={"review_status": "approved"},
                occurred_at=now,
            ),
            CollectionEvent(
                event_type="feishu_phrase_review_callback",
                entity_type="phrase_candidate",
                entity_id=0,
                event_data={"review_status": "converted_to_query"},
                occurred_at=now,
            ),
            CollectionEvent(
                event_type="phrase_candidate_pending",
                entity_type="phrase_candidate",
                entity_id=0,
                event_data={"phrase": "PET 二刷"},
                occurred_at=now,
            ),
            CollectionEvent(
                event_type="feishu_signal_alert_callback",
                entity_type="signal_alert",
                entity_id=0,
                event_data={"alert_id": "a1"},
                occurred_at=now,
            ),
        ]
    )
    session.commit()
