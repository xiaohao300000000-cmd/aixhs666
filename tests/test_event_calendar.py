from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.worker.event_calendar import build_event_calendar_priority_suggestions
from intelligence.event_calendar import (
    EducationEvent,
    EventStatus,
    EventType,
    QueryInput,
    generate_event_priority_suggestions,
    get_event_status,
)


NOW = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)


def test_event_status_uses_warmup_active_cooldown_and_expired_windows() -> None:
    event = _event(starts_at=NOW + timedelta(days=3), ends_at=NOW + timedelta(days=4))

    assert get_event_status(event, now=NOW) == EventStatus.UPCOMING
    assert get_event_status(event, now=NOW + timedelta(days=3, hours=1)) == EventStatus.ACTIVE
    assert get_event_status(event, now=NOW + timedelta(days=5)) == EventStatus.COOLDOWN
    assert get_event_status(event, now=NOW + timedelta(days=8)) == EventStatus.EXPIRED


def test_priority_suggestions_include_boost_reason_and_validity() -> None:
    event = _event(starts_at=NOW + timedelta(days=1), ends_at=NOW + timedelta(days=2))
    query = QueryInput(query_id="q-pet-fuzhou", query_text="福州 PET 报名 求推荐", region="福州")

    suggestions = generate_event_priority_suggestions(events=(event,), queries=(query,), now=NOW)

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.query_id == "q-pet-fuzhou"
    assert suggestion.event_name == "福州 PET 报名"
    assert suggestion.event_type == EventType.REGISTRATION
    assert suggestion.event_status == EventStatus.UPCOMING
    assert suggestion.boost > 0
    assert suggestion.valid_until == event.starts_at
    assert "status=upcoming" in suggestion.reason
    assert "matched_terms=PET,报名" in suggestion.reason


def test_active_event_boost_is_higher_than_cooldown_event_boost() -> None:
    active = _event(
        name="福州 PET 考试",
        event_type=EventType.EXAM,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
    )
    cooldown = _event(
        name="福州 PET 出成绩",
        event_type=EventType.RESULT_RELEASE,
        starts_at=NOW - timedelta(days=3),
        ends_at=NOW - timedelta(days=2),
    )
    query = QueryInput(query_id="q-pet", query_text="福州 PET 二刷 压线", region="福州")

    suggestions = generate_event_priority_suggestions(events=(cooldown, active), queries=(query,), now=NOW)

    assert [suggestion.event_status for suggestion in suggestions] == [
        EventStatus.ACTIVE,
        EventStatus.COOLDOWN,
    ]
    assert suggestions[0].boost > suggestions[1].boost


def test_expired_events_do_not_generate_priority_suggestions() -> None:
    expired = _event(starts_at=NOW - timedelta(days=10), ends_at=NOW - timedelta(days=9))
    query = QueryInput(query_id="q-pet", query_text="福州 PET 报名", region="福州")

    assert generate_event_priority_suggestions(events=(expired,), queries=(query,), now=NOW) == []


def test_worker_entry_accepts_events_and_queries_without_external_io() -> None:
    event = _event(starts_at=NOW - timedelta(hours=1), ends_at=NOW + timedelta(hours=1))
    queries = [
        QueryInput(query_id="q-match", query_text="福州 PET 报名", region="福州"),
        QueryInput(query_id="q-other", query_text="北京 KET 报名", region="北京"),
    ]

    suggestions = build_event_calendar_priority_suggestions(events=(event,), queries=queries, now=NOW)

    assert [suggestion.query_id for suggestion in suggestions] == ["q-match"]
    assert suggestions[0].event_status == EventStatus.ACTIVE


def test_national_events_match_queries_by_region_or_terms() -> None:
    event = _event(region="全国", starts_at=NOW - timedelta(hours=1), ends_at=NOW + timedelta(hours=1))
    query = QueryInput(query_id="q-any-region", query_text="厦门 PET 什么时候报名", region="厦门")

    suggestions = generate_event_priority_suggestions(events=(event,), queries=(query,), now=NOW)

    assert len(suggestions) == 1
    assert suggestions[0].boost > 0


def test_invalid_event_and_query_inputs_raise_clear_errors() -> None:
    with pytest.raises(ValueError, match="ends_at"):
        get_event_status(_event(starts_at=NOW, ends_at=NOW - timedelta(hours=1)), now=NOW)

    with pytest.raises(ValueError, match="query_id"):
        generate_event_priority_suggestions(
            events=(_event(starts_at=NOW, ends_at=NOW + timedelta(hours=1)),),
            queries=(QueryInput(query_id="", query_text="福州 PET"),),
            now=NOW,
        )


def _event(
    *,
    name: str = "福州 PET 报名",
    event_type: EventType = EventType.REGISTRATION,
    region: str = "福州",
    starts_at: datetime,
    ends_at: datetime,
) -> EducationEvent:
    return EducationEvent(
        name=name,
        event_type=event_type,
        region=region,
        starts_at=starts_at,
        ends_at=ends_at,
        warmup_window=timedelta(days=7),
        cooldown_window=timedelta(days=3),
        query_terms=("PET", "报名", "二刷", "压线"),
    )
