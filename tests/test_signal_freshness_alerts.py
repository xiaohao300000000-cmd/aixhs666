from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.worker.signal_alerts import build_worker_signal_alerts, prepare_feishu_signal_alert_payloads
from intelligence.demand_chain import DemandEvent, DemandEventChain, DemandEventStage, DemandEventType
from intelligence.event_calendar import EventPrioritySuggestion, EventStatus, EventType
from intelligence.scoring import QuerySourceScore, ScoringTargetType
from intelligence.signal_alerts import FreshnessClass, classify_signal_freshness


NOW = datetime(2026, 7, 2, 4, 30, tzinfo=timezone.utc)


def test_classify_signal_freshness_uses_signal_type_windows() -> None:
    price = classify_signal_freshness(
        signal_type=DemandEventType.PRICE,
        occurred_at=NOW - timedelta(hours=6),
        now=NOW,
    )
    retry = classify_signal_freshness(
        signal_type=DemandEventType.EXAM_RETRY,
        occurred_at=NOW - timedelta(days=7),
        now=NOW,
    )
    planning = classify_signal_freshness(
        signal_type=DemandEventType.PLANNING,
        occurred_at=NOW - timedelta(days=30),
        now=NOW,
    )
    expired = classify_signal_freshness(
        signal_type=DemandEventType.PRICE,
        occurred_at=NOW - timedelta(days=120),
        now=NOW,
    )

    assert price.freshness_class == FreshnessClass.REAL_TIME
    assert retry.freshness_class == FreshnessClass.RECENT_DECISION
    assert planning.freshness_class == FreshnessClass.LONG_TERM_PLANNING
    assert expired.freshness_class == FreshnessClass.EXPIRED
    assert price.weight > retry.weight > planning.weight > expired.weight


def test_action_signals_rank_above_market_intel() -> None:
    chain = _chain(
        _event(DemandEventType.UNKNOWN, "普通经验分享", "note-1", NOW - timedelta(hours=1)),
        _event(DemandEventType.PRICE, "福州 PET 价格多少？想约试听", "comment-1", NOW - timedelta(hours=1)),
    )

    alerts = build_worker_signal_alerts(chains=(chain,), now=NOW)

    assert [alert.signal_type for alert in alerts] == [DemandEventType.PRICE, DemandEventType.UNKNOWN]
    assert alerts[0].freshness.freshness_class == FreshnessClass.REAL_TIME
    assert alerts[0].ranking_score > alerts[1].ranking_score


def test_event_boost_and_source_score_increase_alert_score() -> None:
    chain = _chain(_event(DemandEventType.TRIAL, "福州 PET 想试听", "comment-1", NOW - timedelta(hours=2)))
    without_boost = build_worker_signal_alerts(chains=(chain,), now=NOW)[0]
    with_boost = build_worker_signal_alerts(
        chains=(chain,),
        event_suggestions=(
            EventPrioritySuggestion(
                query_id="q1",
                query_text="福州 PET 报名",
                event_name="福州 PET 报名",
                event_type=EventType.REGISTRATION,
                event_status=EventStatus.ACTIVE,
                boost=0.45,
                reason="event active",
                valid_until=NOW + timedelta(days=1),
            ),
        ),
        source_scores=(
            QuerySourceScore(
                target_type=ScoringTargetType.SOURCE,
                target_id="comment-1",
                label="comment source",
                new_content_rate=0.9,
                new_user_rate=0.9,
                new_expression_rate=0.7,
                duplicate_rate=0.1,
                failure_rate=0.0,
                task_value_score=0.82,
                reason="high value",
            ),
        ),
        now=NOW,
    )[0]

    assert with_boost.event_boost == 0.45
    assert with_boost.source_score == 0.82
    assert with_boost.ranking_score > without_boost.ranking_score
    assert "event_boost=0.450" in with_boost.ranking_reason


def test_feishu_payloads_are_local_objects_without_network_io() -> None:
    alert = build_worker_signal_alerts(
        chains=(_chain(_event(DemandEventType.COMPLAINT, "机构踩雷想退费", "comment-1", NOW)),),
        now=NOW,
    )[0]

    payloads = prepare_feishu_signal_alert_payloads((alert,))

    assert len(payloads) == 1
    assert payloads[0].message_type == "interactive"
    assert payloads[0].callback_value["alert_id"] == alert.alert_id
    assert payloads[0].card["header"]["title"]["content"] == "高价值信号预警"
    assert payloads[0].card["elements"][-1]["tag"] == "action"


def _chain(*events: DemandEvent) -> DemandEventChain:
    ordered = tuple(sorted(events, key=lambda event: event.event_time))
    return DemandEventChain(
        public_profile_id="profile-1",
        platform="xhs",
        started_at=ordered[0].event_time,
        ended_at=ordered[-1].event_time,
        current_stage=ordered[-1].stage,
        events=ordered,
        evidence_texts=tuple(event.evidence_text for event in ordered),
        stage_transitions=tuple(event.stage for event in ordered),
    )


def _event(event_type: DemandEventType, text: str, source_entity_id: str, occurred_at: datetime) -> DemandEvent:
    stage_by_type = {
        DemandEventType.PRICE: DemandEventStage.ACTION_READY,
        DemandEventType.TRIAL: DemandEventStage.ACTION_READY,
        DemandEventType.EXAM_RETRY: DemandEventStage.RECOVERY,
        DemandEventType.COMPLAINT: DemandEventStage.DISSATISFIED,
        DemandEventType.COMPARISON: DemandEventStage.EVALUATING,
        DemandEventType.PLANNING: DemandEventStage.PLANNING,
        DemandEventType.QUESTION: DemandEventStage.EXPLORING,
        DemandEventType.UNKNOWN: DemandEventStage.UNKNOWN,
    }
    return DemandEvent(
        public_profile_id="profile-1",
        platform="xhs",
        event_type=event_type,
        event_time=occurred_at,
        stage=stage_by_type[event_type],
        evidence_text=text,
        normalized_text=text,
        source_entity_type="comment",
        source_entity_id=source_entity_id,
        source_content_id="note-1",
        source_comment_id=source_entity_id,
    )
