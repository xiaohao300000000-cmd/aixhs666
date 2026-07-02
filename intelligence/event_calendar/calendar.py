from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable


class EventType(StrEnum):
    EXAM = "exam"
    REGISTRATION = "registration"
    RESULT_RELEASE = "result_release"
    SUMMER_VACATION = "summer_vacation"
    WINTER_VACATION = "winter_vacation"
    SCHOOL_START = "school_start"
    MIDTERM = "midterm"
    FINAL = "final"
    PLACEMENT_TEST = "placement_test"
    OTHER = "other"


class EventStatus(StrEnum):
    UPCOMING = "upcoming"
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class EducationEvent:
    name: str
    event_type: EventType
    region: str
    starts_at: datetime
    ends_at: datetime
    warmup_window: timedelta
    cooldown_window: timedelta
    query_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QueryInput:
    query_id: str
    query_text: str
    region: str | None = None


@dataclass(frozen=True, slots=True)
class EventPrioritySuggestion:
    query_id: str
    query_text: str
    event_name: str
    event_type: EventType
    event_status: EventStatus
    boost: float
    reason: str
    valid_until: datetime


STATUS_BOOSTS: dict[EventStatus, float] = {
    EventStatus.ACTIVE: 0.35,
    EventStatus.UPCOMING: 0.25,
    EventStatus.COOLDOWN: 0.12,
    EventStatus.EXPIRED: 0.0,
}


def get_event_status(event: EducationEvent, *, now: datetime | None = None) -> EventStatus:
    _validate_event(event)
    current_time = _as_aware(now or datetime.now(timezone.utc))
    starts_at = _as_aware(event.starts_at)
    ends_at = _as_aware(event.ends_at)

    if starts_at <= current_time <= ends_at:
        return EventStatus.ACTIVE
    if starts_at - event.warmup_window <= current_time < starts_at:
        return EventStatus.UPCOMING
    if ends_at < current_time <= ends_at + event.cooldown_window:
        return EventStatus.COOLDOWN
    return EventStatus.EXPIRED


def generate_event_priority_suggestions(
    *,
    events: Iterable[EducationEvent],
    queries: Iterable[QueryInput],
    now: datetime | None = None,
) -> list[EventPrioritySuggestion]:
    current_time = _as_aware(now or datetime.now(timezone.utc))
    event_list = list(events)
    query_list = list(queries)
    suggestions: list[EventPrioritySuggestion] = []

    for event in event_list:
        _validate_event(event)
        status = get_event_status(event, now=current_time)
        if status == EventStatus.EXPIRED:
            continue
        for query in query_list:
            _validate_query(query)
            if not _matches_event_query(event, query):
                continue
            boost = _calculate_boost(event=event, query=query, status=status, now=current_time)
            suggestions.append(
                EventPrioritySuggestion(
                    query_id=query.query_id,
                    query_text=query.query_text,
                    event_name=event.name,
                    event_type=event.event_type,
                    event_status=status,
                    boost=boost,
                    reason=_build_reason(event=event, query=query, status=status, boost=boost),
                    valid_until=_valid_until(event=event, status=status),
                )
            )

    return sorted(
        suggestions,
        key=lambda suggestion: (
            -suggestion.boost,
            suggestion.valid_until,
            suggestion.query_id,
            suggestion.event_name,
        ),
    )


def _calculate_boost(
    *,
    event: EducationEvent,
    query: QueryInput,
    status: EventStatus,
    now: datetime,
) -> float:
    base_boost = STATUS_BOOSTS[status]
    region_bonus = 0.08 if _region_matches(event.region, query.region) else 0.0
    term_bonus = min(0.12, 0.04 * _matched_term_count(event.query_terms, query.query_text))
    urgency_bonus = _urgency_bonus(event=event, status=status, now=now)
    return round(min(1.0, base_boost + region_bonus + term_bonus + urgency_bonus), 6)


def _urgency_bonus(*, event: EducationEvent, status: EventStatus, now: datetime) -> float:
    if status == EventStatus.UPCOMING and event.warmup_window.total_seconds() > 0:
        elapsed = now - (_as_aware(event.starts_at) - event.warmup_window)
        progress = elapsed.total_seconds() / event.warmup_window.total_seconds()
        return 0.05 * _clamp(progress)
    if status == EventStatus.ACTIVE:
        return 0.06
    return 0.0


def _matches_event_query(event: EducationEvent, query: QueryInput) -> bool:
    query_text = query.query_text.casefold()
    if not any(term.casefold() in query_text for term in event.query_terms):
        return False
    if event.region == "全国" or query.region is None:
        return True
    return _region_matches(event.region, query.region)


def _matched_term_count(query_terms: Iterable[str], query_text: str) -> int:
    normalized_query = query_text.casefold()
    return sum(1 for term in query_terms if term.casefold() in normalized_query)


def _valid_until(event: EducationEvent, status: EventStatus) -> datetime:
    if status == EventStatus.UPCOMING:
        return _as_aware(event.starts_at)
    if status == EventStatus.ACTIVE:
        return _as_aware(event.ends_at)
    if status == EventStatus.COOLDOWN:
        return _as_aware(event.ends_at) + event.cooldown_window
    return _as_aware(event.ends_at)


def _build_reason(
    *,
    event: EducationEvent,
    query: QueryInput,
    status: EventStatus,
    boost: float,
) -> str:
    matched_terms = tuple(term for term in event.query_terms if term.casefold() in query.query_text.casefold())
    region_text = query.region or "unknown"
    return (
        f"event={event.name}; type={event.event_type.value}; status={status.value}; "
        f"query_region={region_text}; event_region={event.region}; "
        f"matched_terms={','.join(matched_terms) if matched_terms else 'none'}; "
        f"boost={boost:.3f}"
    )


def _validate_event(event: EducationEvent) -> None:
    if not event.name:
        raise ValueError("event name is required")
    if not event.region:
        raise ValueError("event region is required")
    if _as_aware(event.ends_at) < _as_aware(event.starts_at):
        raise ValueError("event ends_at cannot be before starts_at")
    if event.warmup_window < timedelta(0):
        raise ValueError("event warmup_window cannot be negative")
    if event.cooldown_window < timedelta(0):
        raise ValueError("event cooldown_window cannot be negative")
    if not event.query_terms:
        raise ValueError("event query_terms are required")
    if any(not term for term in event.query_terms):
        raise ValueError("event query_terms cannot contain empty values")


def _validate_query(query: QueryInput) -> None:
    if not query.query_id:
        raise ValueError("query_id is required")
    if not query.query_text:
        raise ValueError("query_text is required")


def _region_matches(event_region: str, query_region: str | None) -> bool:
    if event_region == "全国":
        return True
    return bool(query_region) and event_region.casefold() == query_region.casefold()


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
