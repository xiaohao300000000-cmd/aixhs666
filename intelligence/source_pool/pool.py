from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable


class SourceType(StrEnum):
    CONTENT = "content"
    ACCOUNT = "account"
    COMMENT_SECTION = "comment_section"
    SEED_ACCOUNT = "seed_account"
    COMPETITOR_ACCOUNT = "competitor_account"


DEFAULT_REASON_WEIGHTS: dict[str, float] = {
    "explicit_local_demand": 0.24,
    "institution_comparison": 0.2,
    "price_question": 0.18,
    "trial_request": 0.18,
    "exam_retry": 0.16,
    "dissatisfaction": 0.14,
    "fresh_activity": 0.1,
    "high_comment_volume": 0.08,
    "seed_source": 0.22,
    "competitor_source": 0.2,
}


@dataclass(frozen=True, slots=True)
class SourceCandidate:
    source_type: SourceType
    platform: str
    source_id: str
    reason: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HighValueSource:
    source_type: SourceType
    platform: str
    source_id: str
    reason: str
    score: float
    tracking_interval: timedelta
    last_checked_at: datetime | None
    next_check_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def key(self) -> tuple[SourceType, str, str]:
        return (self.source_type, self.platform, self.source_id)


class HighValueSourcePool:
    def __init__(self, *, now: datetime | None = None) -> None:
        self._items: dict[tuple[SourceType, str, str], HighValueSource] = {}
        self._now = now

    def upsert(self, candidate: SourceCandidate, *, checked_at: datetime | None = None) -> HighValueSource:
        _validate_candidate(candidate)
        now = _as_aware(candidate.observed_at or self._clock())
        key = (candidate.source_type, candidate.platform, candidate.source_id)
        score = _clamp_score(candidate.score)
        interval = tracking_interval_for_score(score)

        existing = self._items.get(key)
        if existing is None:
            source = HighValueSource(
                source_type=candidate.source_type,
                platform=candidate.platform,
                source_id=candidate.source_id,
                reason=candidate.reason,
                score=score,
                tracking_interval=interval,
                last_checked_at=checked_at,
                next_check_at=now + interval,
                metadata=dict(candidate.metadata),
                created_at=now,
                updated_at=now,
            )
        else:
            merged_score = max(existing.score, score)
            merged_interval = tracking_interval_for_score(merged_score)
            merged_metadata = {**existing.metadata, **candidate.metadata}
            merged_reason = _merge_reason(existing.reason, candidate.reason)
            source = replace(
                existing,
                reason=merged_reason,
                score=merged_score,
                tracking_interval=merged_interval,
                last_checked_at=checked_at if checked_at is not None else existing.last_checked_at,
                next_check_at=now + merged_interval,
                metadata=merged_metadata,
                updated_at=now,
            )

        self._items[key] = source
        return source

    def upsert_many(self, candidates: Iterable[SourceCandidate]) -> list[HighValueSource]:
        return [self.upsert(candidate) for candidate in candidates]

    def list_sources(self) -> list[HighValueSource]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.next_check_at, -item.score, item.source_type.value, item.source_id),
        )

    def due_sources(self, *, at: datetime | None = None) -> list[HighValueSource]:
        check_time = _as_aware(at or self._clock())
        return [source for source in self.list_sources() if source.next_check_at <= check_time]

    def get(self, source_type: SourceType, platform: str, source_id: str) -> HighValueSource | None:
        return self._items.get((source_type, platform, source_id))

    def __len__(self) -> int:
        return len(self._items)

    def _clock(self) -> datetime:
        return _as_aware(self._now or datetime.now(timezone.utc))


def tracking_interval_for_score(score: float) -> timedelta:
    normalized = _clamp_score(score)
    if normalized >= 0.85:
        return timedelta(hours=6)
    if normalized >= 0.7:
        return timedelta(hours=12)
    if normalized >= 0.5:
        return timedelta(days=1)
    if normalized >= 0.3:
        return timedelta(days=3)
    return timedelta(days=7)


def build_content_candidate(
    *,
    platform: str,
    platform_content_id: str,
    reason_signals: Iterable[str],
    base_score: float = 0.35,
    metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> SourceCandidate:
    signals = _normalize_signals(reason_signals)
    return SourceCandidate(
        source_type=SourceType.CONTENT,
        platform=platform,
        source_id=platform_content_id,
        reason=_reason("content", signals),
        score=_score_from_signals(base_score, signals),
        metadata=_metadata_with_signals(metadata, signals),
        observed_at=observed_at,
    )


def build_account_candidate(
    *,
    platform: str,
    platform_user_id: str,
    reason_signals: Iterable[str],
    base_score: float = 0.3,
    metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> SourceCandidate:
    signals = _normalize_signals(reason_signals)
    return SourceCandidate(
        source_type=SourceType.ACCOUNT,
        platform=platform,
        source_id=platform_user_id,
        reason=_reason("account", signals),
        score=_score_from_signals(base_score, signals),
        metadata=_metadata_with_signals(metadata, signals),
        observed_at=observed_at,
    )


def build_comment_section_candidate(
    *,
    platform: str,
    platform_content_id: str,
    reason_signals: Iterable[str],
    base_score: float = 0.32,
    metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> SourceCandidate:
    signals = _normalize_signals(reason_signals)
    return SourceCandidate(
        source_type=SourceType.COMMENT_SECTION,
        platform=platform,
        source_id=platform_content_id,
        reason=_reason("comment_section", signals),
        score=_score_from_signals(base_score, signals),
        metadata=_metadata_with_signals(metadata, signals),
        observed_at=observed_at,
    )


def build_seed_account_candidate(
    *,
    platform: str,
    platform_user_id: str,
    reason: str,
    score: float = 0.7,
    metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> SourceCandidate:
    return SourceCandidate(
        source_type=SourceType.SEED_ACCOUNT,
        platform=platform,
        source_id=platform_user_id,
        reason=reason,
        score=score,
        metadata=dict(metadata or {}),
        observed_at=observed_at,
    )


def build_competitor_account_candidate(
    *,
    platform: str,
    platform_user_id: str,
    reason: str,
    score: float = 0.75,
    metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> SourceCandidate:
    return SourceCandidate(
        source_type=SourceType.COMPETITOR_ACCOUNT,
        platform=platform,
        source_id=platform_user_id,
        reason=reason,
        score=score,
        metadata=dict(metadata or {}),
        observed_at=observed_at,
    )


def _validate_candidate(candidate: SourceCandidate) -> None:
    if not candidate.platform:
        raise ValueError("source platform is required")
    if not candidate.source_id:
        raise ValueError("source_id is required")
    if not candidate.reason:
        raise ValueError("source reason is required")


def _score_from_signals(base_score: float, signals: tuple[str, ...]) -> float:
    score = base_score + sum(DEFAULT_REASON_WEIGHTS.get(signal, 0.05) for signal in signals)
    return _clamp_score(score)


def _normalize_signals(reason_signals: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    normalized: list[str] = []
    for signal in reason_signals:
        clean = signal.strip()
        if clean and clean not in seen:
            normalized.append(clean)
            seen.add(clean)
    return tuple(normalized)


def _metadata_with_signals(metadata: dict[str, Any] | None, signals: tuple[str, ...]) -> dict[str, Any]:
    result = dict(metadata or {})
    result["reason_signals"] = list(signals)
    return result


def _reason(prefix: str, signals: tuple[str, ...]) -> str:
    if not signals:
        return f"{prefix}: manually selected for tracking"
    return f"{prefix}: " + ", ".join(signals)


def _merge_reason(existing: str, new: str) -> str:
    if existing == new or new in existing:
        return existing
    if existing in new:
        return new
    return f"{existing}; {new}"


def _clamp_score(score: float) -> float:
    return min(1.0, max(0.0, float(score)))


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
