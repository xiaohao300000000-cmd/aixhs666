from __future__ import annotations

from datetime import datetime
from typing import Iterable

from intelligence.demand_chain import DemandEventChain
from intelligence.event_calendar import EventPrioritySuggestion
from intelligence.scoring import QuerySourceScore
from intelligence.signal_alerts import SignalAlert, build_signal_alerts
from integrations.feishu import FeishuSignalAlertPayload, build_signal_alert_payloads


def build_worker_signal_alerts(
    *,
    chains: Iterable[DemandEventChain],
    event_suggestions: Iterable[EventPrioritySuggestion] = (),
    source_scores: Iterable[QuerySourceScore] = (),
    now: datetime | None = None,
) -> list[SignalAlert]:
    return build_signal_alerts(
        chains=chains,
        event_suggestions=event_suggestions,
        source_scores=source_scores,
        now=now,
    )


def prepare_feishu_signal_alert_payloads(alerts: Iterable[SignalAlert]) -> list[FeishuSignalAlertPayload]:
    return build_signal_alert_payloads(alerts)
