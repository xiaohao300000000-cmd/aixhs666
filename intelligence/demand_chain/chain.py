from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from intelligence.text_processing import normalize_text


class DemandEventType(StrEnum):
    QUESTION = "question"
    COMPARISON = "comparison"
    PRICE = "price"
    TRIAL = "trial"
    COMPLAINT = "complaint"
    EXAM_RETRY = "exam_retry"
    PLANNING = "planning"
    UNKNOWN = "unknown"


class DemandEventStage(StrEnum):
    UNKNOWN = "unknown"
    EXPLORING = "exploring"
    PLANNING = "planning"
    EVALUATING = "evaluating"
    ACTION_READY = "action_ready"
    RECOVERY = "recovery"
    DISSATISFIED = "dissatisfied"


@dataclass(frozen=True)
class DemandTextRecord:
    public_profile_id: str
    platform: str
    text: str
    occurred_at: datetime
    source_entity_type: str
    source_entity_id: str
    source_content_id: str | None = None
    source_comment_id: str | None = None


@dataclass(frozen=True)
class DemandEvent:
    public_profile_id: str
    platform: str
    event_type: DemandEventType
    event_time: datetime
    stage: DemandEventStage
    evidence_text: str
    normalized_text: str
    source_entity_type: str
    source_entity_id: str
    source_content_id: str | None = None
    source_comment_id: str | None = None


@dataclass(frozen=True)
class DemandEventChain:
    public_profile_id: str
    platform: str
    started_at: datetime
    ended_at: datetime
    current_stage: DemandEventStage
    events: tuple[DemandEvent, ...]
    evidence_texts: tuple[str, ...]
    stage_transitions: tuple[DemandEventStage, ...] = field(default_factory=tuple)


_TYPE_KEYWORDS: tuple[tuple[DemandEventType, tuple[str, ...]], ...] = (
    (
        DemandEventType.PRICE,
        ("价格", "多少钱", "收费", "费用", "学费", "课时费", "贵不贵", "报价", "预算"),
    ),
    (
        DemandEventType.TRIAL,
        ("试听", "体验课", "试课", "约课", "先体验", "体验一下"),
    ),
    (
        DemandEventType.COMPARISON,
        ("比较", "对比", "哪家", "哪个", "哪个好", "怎么选", "靠谱不", "靠谱吗", "机构推荐", "求推荐"),
    ),
    (
        DemandEventType.EXAM_RETRY,
        ("二刷", "再考", "重考", "压线", "没过", "失败", "补考", "刷分", "没通过"),
    ),
    (
        DemandEventType.COMPLAINT,
        ("不满意", "退费", "效果差", "没效果", "踩雷", "投诉", "坑", "老师不行", "后悔"),
    ),
    (
        DemandEventType.PLANNING,
        ("准备", "计划", "规划", "多久", "周期", "来得及", "暑假", "寒假", "报名", "备考"),
    ),
    (
        DemandEventType.QUESTION,
        ("吗", "？", "?", "有没有", "想问", "请问", "求问", "怎么", "如何"),
    ),
)

_STAGE_BY_TYPE = {
    DemandEventType.QUESTION: DemandEventStage.EXPLORING,
    DemandEventType.COMPARISON: DemandEventStage.EVALUATING,
    DemandEventType.PRICE: DemandEventStage.ACTION_READY,
    DemandEventType.TRIAL: DemandEventStage.ACTION_READY,
    DemandEventType.COMPLAINT: DemandEventStage.DISSATISFIED,
    DemandEventType.EXAM_RETRY: DemandEventStage.RECOVERY,
    DemandEventType.PLANNING: DemandEventStage.PLANNING,
    DemandEventType.UNKNOWN: DemandEventStage.UNKNOWN,
}


def classify_demand_event(text: str | None) -> DemandEventType:
    normalized = normalize_text(text)
    lowered = normalized.casefold()
    if not lowered:
        return DemandEventType.UNKNOWN

    for event_type, keywords in _TYPE_KEYWORDS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            return event_type
    return DemandEventType.UNKNOWN


def build_demand_event_chains(records: list[DemandTextRecord]) -> list[DemandEventChain]:
    events_by_profile: dict[tuple[str, str], list[DemandEvent]] = defaultdict(list)
    for record in records:
        event_type = classify_demand_event(record.text)
        normalized = normalize_text(record.text)
        event = DemandEvent(
            public_profile_id=record.public_profile_id,
            platform=record.platform,
            event_type=event_type,
            event_time=record.occurred_at,
            stage=_STAGE_BY_TYPE[event_type],
            evidence_text=record.text,
            normalized_text=normalized,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
            source_content_id=record.source_content_id,
            source_comment_id=record.source_comment_id,
        )
        events_by_profile[(record.platform, record.public_profile_id)].append(event)

    chains = [
        _build_chain(public_profile_id=public_profile_id, platform=platform, events=events)
        for (platform, public_profile_id), events in events_by_profile.items()
    ]
    return sorted(chains, key=lambda chain: (chain.platform, chain.public_profile_id))


def _build_chain(public_profile_id: str, platform: str, events: list[DemandEvent]) -> DemandEventChain:
    ordered_events = tuple(
        sorted(events, key=lambda event: (event.event_time, event.source_entity_type, event.source_entity_id))
    )
    stage_transitions = _stage_transitions(ordered_events)
    return DemandEventChain(
        public_profile_id=public_profile_id,
        platform=platform,
        started_at=ordered_events[0].event_time,
        ended_at=ordered_events[-1].event_time,
        current_stage=stage_transitions[-1],
        events=ordered_events,
        evidence_texts=tuple(event.evidence_text for event in ordered_events),
        stage_transitions=stage_transitions,
    )


def _stage_transitions(events: tuple[DemandEvent, ...]) -> tuple[DemandEventStage, ...]:
    stages: list[DemandEventStage] = []
    for event in events:
        if not stages or stages[-1] != event.stage:
            stages.append(event.stage)
    return tuple(stages)


def demand_record_from_mapping(item: dict[str, Any]) -> DemandTextRecord:
    occurred_at = item.get("occurred_at") or item.get("event_time") or item.get("published_at")
    if not isinstance(occurred_at, datetime):
        raise TypeError("occurred_at must be a datetime")

    public_profile_id = item.get("public_profile_id") or item.get("profile_id") or item.get("author_profile_id")
    if not public_profile_id:
        raise ValueError("public_profile_id is required")

    source_entity_type = item.get("source_entity_type") or item.get("entity_type")
    source_entity_id = item.get("source_entity_id") or item.get("entity_id")
    if not source_entity_type or not source_entity_id:
        raise ValueError("source_entity_type and source_entity_id are required")

    return DemandTextRecord(
        public_profile_id=str(public_profile_id),
        platform=str(item.get("platform") or "xhs"),
        text=str(item.get("text") or item.get("body_text") or ""),
        occurred_at=occurred_at,
        source_entity_type=str(source_entity_type),
        source_entity_id=str(source_entity_id),
        source_content_id=_optional_str(item.get("source_content_id") or item.get("content_id")),
        source_comment_id=_optional_str(item.get("source_comment_id") or item.get("comment_id")),
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
