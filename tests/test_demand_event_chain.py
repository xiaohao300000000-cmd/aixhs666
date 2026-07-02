from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.worker.demand_chain import build_worker_demand_event_chains
from intelligence.demand_chain import (
    DemandEventStage,
    DemandEventType,
    DemandTextRecord,
    build_demand_event_chains,
    classify_demand_event,
)


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def test_classify_demand_event_identifies_key_types() -> None:
    assert classify_demand_event("PET 二刷压线，想再考") == DemandEventType.EXAM_RETRY
    assert classify_demand_event("福州哪家机构比较靠谱？") == DemandEventType.COMPARISON
    assert classify_demand_event("这个班多少钱，收费贵不贵") == DemandEventType.PRICE
    assert classify_demand_event("可以约试听或者体验课吗") == DemandEventType.TRIAL
    assert classify_demand_event("学了半年没效果，想退费") == DemandEventType.COMPLAINT
    assert classify_demand_event("暑假准备 KET 来得及吗") == DemandEventType.PLANNING
    assert classify_demand_event("有人了解这个考试吗") == DemandEventType.QUESTION
    assert classify_demand_event("谢谢分享") == DemandEventType.UNKNOWN


def test_build_demand_event_chains_groups_by_public_profile_and_sorts_time() -> None:
    records = [
        DemandTextRecord(
            public_profile_id="profile-a",
            platform="xhs",
            text="现在 PET 二刷压线，准备再考",
            occurred_at=_dt(2),
            source_entity_type="comment",
            source_entity_id="comment-2",
            source_content_id="content-1",
            source_comment_id="comment-2",
        ),
        DemandTextRecord(
            public_profile_id="profile-a",
            platform="xhs",
            text="福州哪家机构比较靠谱？",
            occurred_at=_dt(1),
            source_entity_type="content",
            source_entity_id="content-1",
            source_content_id="content-1",
        ),
        DemandTextRecord(
            public_profile_id="profile-b",
            platform="xhs",
            text="试听课怎么约",
            occurred_at=_dt(3),
            source_entity_type="comment",
            source_entity_id="comment-3",
            source_comment_id="comment-3",
        ),
    ]

    chains = build_demand_event_chains(records)

    assert [chain.public_profile_id for chain in chains] == ["profile-a", "profile-b"]
    profile_a = chains[0]
    assert profile_a.started_at == _dt(1)
    assert profile_a.ended_at == _dt(2)
    assert [event.source_entity_id for event in profile_a.events] == ["content-1", "comment-2"]
    assert [event.event_type for event in profile_a.events] == [
        DemandEventType.COMPARISON,
        DemandEventType.EXAM_RETRY,
    ]
    assert profile_a.evidence_texts == ("福州哪家机构比较靠谱？", "现在 PET 二刷压线，准备再考")
    assert profile_a.stage_transitions == (DemandEventStage.EVALUATING, DemandEventStage.RECOVERY)
    assert profile_a.current_stage == DemandEventStage.RECOVERY


def test_demand_event_chain_preserves_evidence_and_source_ids() -> None:
    records = [
        DemandTextRecord(
            public_profile_id="profile-a",
            platform="xhs",
            text="这个 KET 冲刺班价格多少？能不能试听",
            occurred_at=_dt(1, 9),
            source_entity_type="comment",
            source_entity_id="comment-1",
            source_content_id="content-9",
            source_comment_id="comment-1",
        )
    ]

    chain = build_demand_event_chains(records)[0]
    event = chain.events[0]

    assert event.event_type == DemandEventType.PRICE
    assert event.stage == DemandEventStage.ACTION_READY
    assert event.evidence_text == "这个 KET 冲刺班价格多少？能不能试听"
    assert event.normalized_text == "这个 KET 冲刺班价格多少?能不能试听"
    assert event.source_content_id == "content-9"
    assert event.source_comment_id == "comment-1"


def test_worker_entry_accepts_mapping_records() -> None:
    chains = build_worker_demand_event_chains(
        [
            {
                "author_profile_id": "profile-a",
                "platform": "xhs",
                "body_text": "想问 PET 备考周期多久",
                "published_at": _dt(1),
                "entity_type": "content",
                "entity_id": "content-1",
                "content_id": "content-1",
            },
            {
                "author_profile_id": "profile-a",
                "platform": "xhs",
                "body_text": "新东方和学而思哪个适合五年级",
                "published_at": _dt(2),
                "entity_type": "comment",
                "entity_id": "comment-2",
                "comment_id": "comment-2",
            },
        ]
    )

    assert len(chains) == 1
    assert [event.event_type for event in chains[0].events] == [
        DemandEventType.PLANNING,
        DemandEventType.COMPARISON,
    ]


def test_worker_entry_rejects_records_without_required_identity() -> None:
    with pytest.raises(ValueError, match="public_profile_id is required"):
        build_worker_demand_event_chains(
            [
                {
                    "body_text": "价格多少",
                    "published_at": _dt(1),
                    "entity_type": "comment",
                    "entity_id": "comment-1",
                }
            ]
        )
