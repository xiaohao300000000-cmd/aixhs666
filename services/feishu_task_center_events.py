from __future__ import annotations

import json
from typing import Any


def event_to_callback_payload(event: dict[str, Any]) -> dict[str, Any]:
    action_value = _json_object(event.get("action_value"))
    form_value = _json_object(event.get("form_value"))
    action_name = str(event.get("action_name") or action_value.get("action") or "")
    return {
        "header": {"event_id": str(event.get("event_id") or "")},
        "event": {
            "token": event.get("token"),
            "operator": {"open_id": event.get("operator_id")},
            "context": {"open_message_id": event.get("message_id"), "open_chat_id": event.get("chat_id")},
            "action": {"name": action_name, "value": action_value, "form_value": form_value},
        },
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
