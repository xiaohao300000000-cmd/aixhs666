from __future__ import annotations

from datetime import datetime
from typing import Iterable

from intelligence.event_calendar import (
    EducationEvent,
    EventPrioritySuggestion,
    QueryInput,
    generate_event_priority_suggestions,
)


def build_event_calendar_priority_suggestions(
    *,
    events: Iterable[EducationEvent],
    queries: Iterable[QueryInput],
    now: datetime | None = None,
) -> list[EventPrioritySuggestion]:
    return generate_event_priority_suggestions(events=events, queries=queries, now=now)
