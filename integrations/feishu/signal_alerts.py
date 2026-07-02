from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from intelligence.signal_alerts import SignalAlert


@dataclass(frozen=True, slots=True)
class FeishuSignalAlertPayload:
    alert_id: str
    message_type: str
    card: dict[str, Any]
    callback_value: dict[str, str]


def build_signal_alert_payload(alert: SignalAlert, *, locale: str = "zh_cn") -> FeishuSignalAlertPayload:
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _header_template(alert.ranking_score),
            "title": {"tag": "plain_text", "content": "高价值信号预警"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**证据摘要**：{alert.evidence_summary}"},
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"信号类型：{alert.signal_type.value}"}},
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"新鲜度：{alert.freshness.freshness_class.value}",
                        },
                    },
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"排序分：{alert.ranking_score:.4f}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"事件加权：{alert.event_boost:.4f}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"来源分：{alert.source_score:.4f}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"平台：{alert.platform}"}},
                ],
            },
            {"tag": "markdown", "content": f"**排序原因**：{alert.ranking_reason}"},
            {
                "tag": "action",
                "actions": [
                    _button("保留", "keep", alert.alert_id, "primary"),
                    _button("忽略", "dismiss", alert.alert_id, "default"),
                    _button("稍后跟进", "follow_up_later", alert.alert_id, "primary"),
                ],
            },
        ],
    }
    return FeishuSignalAlertPayload(
        alert_id=alert.alert_id,
        message_type="interactive",
        card=card,
        callback_value={"alert_id": alert.alert_id, "locale": locale},
    )


def build_signal_alert_payloads(alerts: Iterable[SignalAlert]) -> list[FeishuSignalAlertPayload]:
    return [build_signal_alert_payload(alert) for alert in alerts]


def _button(label: str, action: str, alert_id: str, button_type: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "value": {"alert_id": alert_id, "action": action},
        "type": button_type,
    }


def _header_template(score: float) -> str:
    if score >= 0.85:
        return "red"
    if score >= 0.65:
        return "orange"
    return "blue"
