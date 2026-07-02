from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable

from intelligence.demand_chain import DemandEvent, DemandEventChain, DemandEventType
from intelligence.event_calendar import EventPrioritySuggestion
from intelligence.scoring import QuerySourceScore


class FreshnessClass(StrEnum):
    REAL_TIME = "real_time"
    RECENT_DECISION = "recent_decision"
    LONG_TERM_PLANNING = "long_term_planning"
    MARKET_INTEL = "market_intel"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class SignalFreshness:
    freshness_class: FreshnessClass
    age: timedelta
    weight: float
    expires_at: datetime | None
    reason: str


@dataclass(frozen=True, slots=True)
class SignalAlert:
    alert_id: str
    public_profile_id: str
    platform: str
    signal_type: DemandEventType
    signal_strength: float
    freshness: SignalFreshness
    event_boost: float
    source_score: float
    evidence_summary: str
    source_entity_type: str
    source_entity_id: str
    source_content_id: str | None
    source_comment_id: str | None
    occurred_at: datetime
    ranking_score: float
    ranking_reason: str


_ACTION_SIGNAL_STRENGTH: dict[DemandEventType, float] = {
    DemandEventType.PRICE: 0.95,
    DemandEventType.TRIAL: 0.93,
    DemandEventType.EXAM_RETRY: 0.90,
    DemandEventType.COMPLAINT: 0.88,
    DemandEventType.COMPARISON: 0.76,
    DemandEventType.PLANNING: 0.62,
    DemandEventType.QUESTION: 0.42,
    DemandEventType.UNKNOWN: 0.18,
}

_REAL_TIME_TYPES = {
    DemandEventType.PRICE,
    DemandEventType.TRIAL,
    DemandEventType.COMPLAINT,
}

_RECENT_DECISION_TYPES = {
    DemandEventType.EXAM_RETRY,
    DemandEventType.COMPARISON,
}

_LONG_TERM_TYPES = {
    DemandEventType.PLANNING,
}

_REAL_TIME_WINDOW = timedelta(days=2)
_RECENT_DECISION_WINDOW = timedelta(days=14)
_LONG_TERM_WINDOW = timedelta(days=90)


def classify_signal_freshness(
    *,
    signal_type: DemandEventType,
    occurred_at: datetime,
    now: datetime | None = None,
) -> SignalFreshness:
    current_time = _as_aware(now or datetime.now(timezone.utc))
    event_time = _as_aware(occurred_at)
    age = max(timedelta(0), current_time - event_time)

    if signal_type in _REAL_TIME_TYPES:
        return _freshness_for_action_signal(
            signal_type=signal_type,
            age=age,
            occurred_at=event_time,
            primary_class=FreshnessClass.REAL_TIME,
            primary_window=_REAL_TIME_WINDOW,
        )

    if signal_type in _RECENT_DECISION_TYPES:
        return _freshness_for_action_signal(
            signal_type=signal_type,
            age=age,
            occurred_at=event_time,
            primary_class=FreshnessClass.RECENT_DECISION,
            primary_window=_RECENT_DECISION_WINDOW,
        )

    if signal_type in _LONG_TERM_TYPES:
        if age <= _LONG_TERM_WINDOW:
            return SignalFreshness(
                freshness_class=FreshnessClass.LONG_TERM_PLANNING,
                age=age,
                weight=0.55,
                expires_at=event_time + _LONG_TERM_WINDOW,
                reason="planning signal remains useful inside 90 days",
            )
        return _expired(age=age, occurred_at=event_time, expired_after=_LONG_TERM_WINDOW)

    return SignalFreshness(
        freshness_class=FreshnessClass.MARKET_INTEL,
        age=age,
        weight=0.28,
        expires_at=None,
        reason="low-action signal is kept as market intelligence",
    )


def build_signal_alerts(
    *,
    chains: Iterable[DemandEventChain],
    event_suggestions: Iterable[EventPrioritySuggestion] = (),
    source_scores: Iterable[QuerySourceScore] = (),
    now: datetime | None = None,
) -> list[SignalAlert]:
    current_time = _as_aware(now or datetime.now(timezone.utc))
    max_event_boost = max((suggestion.boost for suggestion in event_suggestions), default=0.0)
    source_score_by_id = {score.target_id: score.task_value_score for score in source_scores}
    alerts: list[SignalAlert] = []

    for chain in chains:
        _validate_chain(chain)
        for event in chain.events:
            freshness = classify_signal_freshness(
                signal_type=event.event_type,
                occurred_at=event.event_time,
                now=current_time,
            )
            source_score = _source_score_for_event(event, source_score_by_id)
            ranking_score = _ranking_score(
                signal_type=event.event_type,
                freshness=freshness,
                event_boost=max_event_boost,
                source_score=source_score,
            )
            alerts.append(
                SignalAlert(
                    alert_id=_alert_id(chain=chain, event=event),
                    public_profile_id=chain.public_profile_id,
                    platform=chain.platform,
                    signal_type=event.event_type,
                    signal_strength=_ACTION_SIGNAL_STRENGTH[event.event_type],
                    freshness=freshness,
                    event_boost=round(max_event_boost, 6),
                    source_score=round(source_score, 6),
                    evidence_summary=_summarize_evidence(event.evidence_text),
                    source_entity_type=event.source_entity_type,
                    source_entity_id=event.source_entity_id,
                    source_content_id=event.source_content_id,
                    source_comment_id=event.source_comment_id,
                    occurred_at=_as_aware(event.event_time),
                    ranking_score=ranking_score,
                    ranking_reason=_ranking_reason(
                        event_type=event.event_type,
                        freshness=freshness,
                        event_boost=max_event_boost,
                        source_score=source_score,
                        ranking_score=ranking_score,
                    ),
                )
            )

    return rank_signal_alerts(alerts)


def rank_signal_alerts(alerts: Iterable[SignalAlert]) -> list[SignalAlert]:
    return sorted(
        alerts,
        key=lambda alert: (
            -alert.ranking_score,
            -alert.signal_strength,
            alert.occurred_at,
            alert.alert_id,
        ),
    )


def _freshness_for_action_signal(
    *,
    signal_type: DemandEventType,
    age: timedelta,
    occurred_at: datetime,
    primary_class: FreshnessClass,
    primary_window: timedelta,
) -> SignalFreshness:
    if age <= primary_window:
        return SignalFreshness(
            freshness_class=primary_class,
            age=age,
            weight=1.0 if primary_class == FreshnessClass.REAL_TIME else 0.82,
            expires_at=occurred_at + primary_window,
            reason=f"{signal_type.value} signal is inside {primary_class.value} window",
        )
    if age <= _RECENT_DECISION_WINDOW:
        return SignalFreshness(
            freshness_class=FreshnessClass.RECENT_DECISION,
            age=age,
            weight=0.72,
            expires_at=occurred_at + _RECENT_DECISION_WINDOW,
            reason=f"{signal_type.value} signal is still inside decision window",
        )
    if age <= _LONG_TERM_WINDOW:
        return SignalFreshness(
            freshness_class=FreshnessClass.LONG_TERM_PLANNING,
            age=age,
            weight=0.42,
            expires_at=occurred_at + _LONG_TERM_WINDOW,
            reason=f"{signal_type.value} signal is stale for action but useful for planning",
        )
    return _expired(age=age, occurred_at=occurred_at, expired_after=_LONG_TERM_WINDOW)


def _expired(*, age: timedelta, occurred_at: datetime, expired_after: timedelta) -> SignalFreshness:
    return SignalFreshness(
        freshness_class=FreshnessClass.EXPIRED,
        age=age,
        weight=0.0,
        expires_at=occurred_at + expired_after,
        reason="signal exceeded freshness window",
    )


def _ranking_score(
    *,
    signal_type: DemandEventType,
    freshness: SignalFreshness,
    event_boost: float,
    source_score: float,
) -> float:
    value = (
        0.50 * _ACTION_SIGNAL_STRENGTH[signal_type]
        + 0.25 * freshness.weight
        + 0.15 * _clamp(event_boost)
        + 0.10 * _clamp(source_score)
    )
    if freshness.freshness_class == FreshnessClass.EXPIRED:
        value *= 0.2
    return round(_clamp(value), 6)


def _source_score_for_event(event: DemandEvent, source_score_by_id: dict[str, float]) -> float:
    candidate_ids = (
        event.source_entity_id,
        event.source_content_id,
        event.source_comment_id,
    )
    return max((_clamp(source_score_by_id.get(source_id, 0.0)) for source_id in candidate_ids if source_id), default=0.0)


def _ranking_reason(
    *,
    event_type: DemandEventType,
    freshness: SignalFreshness,
    event_boost: float,
    source_score: float,
    ranking_score: float,
) -> str:
    return (
        f"ranking_score={ranking_score:.3f}; signal_type={event_type.value}; "
        f"signal_strength={_ACTION_SIGNAL_STRENGTH[event_type]:.3f}; "
        f"freshness={freshness.freshness_class.value}; freshness_weight={freshness.weight:.3f}; "
        f"event_boost={_clamp(event_boost):.3f}; source_score={_clamp(source_score):.3f}"
    )


def _summarize_evidence(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _alert_id(*, chain: DemandEventChain, event: DemandEvent) -> str:
    source_id = event.source_comment_id or event.source_content_id or event.source_entity_id
    return f"{chain.platform}:{chain.public_profile_id}:{event.event_type.value}:{source_id}"


def _validate_chain(chain: DemandEventChain) -> None:
    if not chain.public_profile_id:
        raise ValueError("chain public_profile_id is required")
    if not chain.platform:
        raise ValueError("chain platform is required")


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
