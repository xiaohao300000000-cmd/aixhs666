from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from intelligence.dashboard import (
    DailyDashboardMetric,
    DashboardInput,
    FailedTaskMetric,
    FieldCompletenessMetric,
    PhraseReviewMetric,
    QueryOutputMetric,
    build_dashboard_summary,
    dashboard_summary_to_dict,
)
from scheduler import TaskStatus
from storage.models import CollectionEvent, CollectionTask, Comment, Content, DiscoveryRelation, PublicProfile
from storage.models import Query as StoredQuery


PHRASE_REVIEW_EVENT_TYPE = "feishu_phrase_review_callback"


@dataclass(frozen=True, slots=True)
class DatabaseRealtimeMetrics:
    high_value_signal_count: int
    pending_phrase_count: int
    latest_successful_collection_at: datetime | None
    latest_failure_reason: str | None
    partial_task_count: int
    retry_task_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "high_value_signal_count": self.high_value_signal_count,
            "pending_phrase_count": self.pending_phrase_count,
            "latest_successful_collection_at": self.latest_successful_collection_at,
            "latest_failure_reason": self.latest_failure_reason,
            "partial_task_count": self.partial_task_count,
            "retry_task_count": self.retry_task_count,
        }


def build_database_dashboard_response(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    generated_at = _normalize_datetime(now or datetime.now(UTC))
    day_start = datetime.combine(generated_at.date(), time.min, tzinfo=generated_at.tzinfo)

    dashboard_input = DashboardInput(
        generated_at=generated_at,
        daily_metrics=(_build_today_metric(session, generated_at, day_start),),
        query_outputs=tuple(_build_query_outputs(session, day_start)),
        phrase_reviews=(_build_phrase_review_metric(session, generated_at),),
        failed_tasks=tuple(_build_failed_tasks(session)),
        field_completeness=tuple(_build_field_completeness(session)),
    )
    response = dashboard_summary_to_dict(build_dashboard_summary(dashboard_input))
    response["database_metrics"] = _build_realtime_metrics(session).as_dict()
    return response


def _build_today_metric(session: Session, now: datetime, day_start: datetime) -> DailyDashboardMetric:
    observed_discoveries = _scalar_count(
        session,
        select(func.count(DiscoveryRelation.id)).where(DiscoveryRelation.discovered_at >= day_start),
    )
    distinct_discovered_content = _scalar_count(
        session,
        select(func.count(distinct(DiscoveryRelation.content_id))).where(DiscoveryRelation.discovered_at >= day_start),
    )
    new_content_count = _scalar_count(
        session,
        select(func.count(Content.id)).where(Content.first_seen_at >= day_start),
    )
    observed_content_count = observed_discoveries or new_content_count

    return DailyDashboardMetric(
        metric_date=now.date(),
        new_content_count=new_content_count,
        new_comment_count=_scalar_count(
            session,
            select(func.count(Comment.id)).where(Comment.first_seen_at >= day_start),
        ),
        new_profile_count=_scalar_count(
            session,
            select(func.count(PublicProfile.id)).where(PublicProfile.first_seen_at >= day_start),
        ),
        observed_content_count=observed_content_count,
        duplicate_content_count=max(observed_discoveries - distinct_discovered_content, 0),
    )


def _build_query_outputs(session: Session, day_start: datetime) -> list[QueryOutputMetric]:
    rows = session.execute(select(StoredQuery).order_by(StoredQuery.id.asc())).scalars().all()
    metrics: list[QueryOutputMetric] = []
    for query in rows:
        metrics.append(
            QueryOutputMetric(
                query_id=str(query.id),
                query_text=query.query_text,
                new_content_count=_scalar_count(
                    session,
                    select(func.count(distinct(Content.id)))
                    .select_from(DiscoveryRelation)
                    .join(Content, Content.id == DiscoveryRelation.content_id)
                    .where(DiscoveryRelation.query_id == query.id)
                    .where(Content.first_seen_at >= day_start),
                ),
                discovery_count=_scalar_count(
                    session,
                    select(func.count(DiscoveryRelation.id)).where(DiscoveryRelation.query_id == query.id),
                ),
                task_count=_scalar_count(
                    session,
                    select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query.id),
                ),
                failed_task_count=_scalar_count(
                    session,
                    select(func.count(CollectionTask.id))
                    .where(CollectionTask.query_id == query.id)
                    .where(CollectionTask.status == TaskStatus.FAILED.value),
                ),
            )
        )
    return metrics


def _build_failed_tasks(session: Session) -> list[FailedTaskMetric]:
    failed_tasks = session.scalars(
        select(CollectionTask)
        .where(CollectionTask.status == TaskStatus.FAILED.value)
        .order_by(CollectionTask.task_type.asc(), CollectionTask.platform.asc(), CollectionTask.id.asc())
    ).all()
    grouped: dict[tuple[str, str], FailedTaskMetric] = {}
    counts: dict[tuple[str, str], int] = {}
    for task in failed_tasks:
        key = (task.task_type, task.platform)
        counts[key] = counts.get(key, 0) + 1
        grouped[key] = FailedTaskMetric(
            task_type=task.task_type,
            platform=task.platform,
            failed_count=counts[key],
            last_error=task.last_error or grouped.get(key, FailedTaskMetric(task.task_type, task.platform, 0)).last_error,
        )
    return list(grouped.values())


def _build_phrase_review_metric(session: Session, now: datetime) -> PhraseReviewMetric:
    review_events = session.scalars(
        select(CollectionEvent).where(CollectionEvent.event_type == PHRASE_REVIEW_EVENT_TYPE)
    ).all()
    status_counts = {"approved": 0, "rejected": 0, "converted_to_query": 0}
    for event in review_events:
        event_data = event.event_data or {}
        status = event_data.get("review_status")
        if status in status_counts:
            status_counts[status] += 1
    return PhraseReviewMetric(
        metric_date=now.date(),
        pending_count=_pending_phrase_count(session),
        approved_count=status_counts["approved"],
        rejected_count=status_counts["rejected"],
        converted_to_query_count=status_counts["converted_to_query"],
    )


def _build_field_completeness(session: Session) -> list[FieldCompletenessMetric]:
    metrics: list[FieldCompletenessMetric] = []
    metrics.extend(
        _field_metrics(
            session,
            entity_type="contents",
            model=Content,
            fields=("title", "body_text", "url", "published_at", "author_profile_id"),
        )
    )
    metrics.extend(
        _field_metrics(
            session,
            entity_type="comments",
            model=Comment,
            fields=("body_text", "published_at", "author_profile_id"),
        )
    )
    metrics.extend(
        _field_metrics(
            session,
            entity_type="public_profiles",
            model=PublicProfile,
            fields=("display_name", "profile_url", "bio", "region_text"),
        )
    )
    return metrics


def _field_metrics(session: Session, *, entity_type: str, model: type, fields: tuple[str, ...]) -> list[FieldCompletenessMetric]:
    total_count = _scalar_count(session, select(func.count(model.id)))
    metrics: list[FieldCompletenessMetric] = []
    for field_name in fields:
        column = getattr(model, field_name)
        statement = select(func.count(model.id)).where(column.is_not(None))
        if field_name.endswith("_text") or field_name in {"title", "url", "display_name", "profile_url", "bio", "region_text"}:
            statement = statement.where(column != "")
        metrics.append(
            FieldCompletenessMetric(
                entity_type=entity_type,
                field_name=field_name,
                present_count=_scalar_count(session, statement),
                total_count=total_count,
            )
        )
    return metrics


def _build_realtime_metrics(session: Session) -> DatabaseRealtimeMetrics:
    latest_success = session.scalar(
        select(CollectionTask.finished_at)
        .where(CollectionTask.status == TaskStatus.COMPLETED.value)
        .where(CollectionTask.finished_at.is_not(None))
        .order_by(CollectionTask.finished_at.desc(), CollectionTask.id.desc())
        .limit(1)
    )
    latest_failure = session.scalar(
        select(CollectionTask.last_error)
        .where(CollectionTask.status.in_((TaskStatus.FAILED.value, TaskStatus.RETRY.value, TaskStatus.PARTIAL.value)))
        .where(CollectionTask.last_error.is_not(None))
        .order_by(
            func.coalesce(
                CollectionTask.finished_at,
                CollectionTask.started_at,
                CollectionTask.scheduled_at,
                CollectionTask.created_at,
            ).desc(),
            CollectionTask.id.desc(),
        )
        .limit(1)
    )
    return DatabaseRealtimeMetrics(
        high_value_signal_count=_scalar_count(
            session,
            select(func.count(CollectionEvent.id)).where(CollectionEvent.event_type.like("%signal%")),
        ),
        pending_phrase_count=_pending_phrase_count(session),
        latest_successful_collection_at=_normalize_datetime(latest_success) if latest_success is not None else None,
        latest_failure_reason=latest_failure,
        partial_task_count=_scalar_count(
            session,
            select(func.count(CollectionTask.id)).where(CollectionTask.status == TaskStatus.PARTIAL.value),
        ),
        retry_task_count=_scalar_count(
            session,
            select(func.count(CollectionTask.id)).where(CollectionTask.status == TaskStatus.RETRY.value),
        ),
    )


def _pending_phrase_count(session: Session) -> int:
    return _scalar_count(
        session,
        select(func.count(CollectionEvent.id)).where(CollectionEvent.event_type.in_(("phrase_candidate_pending", "phrase_review_pending"))),
    )


def _scalar_count(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
