from services.feishu_task_center_events import event_to_callback_payload


def test_event_to_callback_payload_parses_action_and_form_values() -> None:
    payload = event_to_callback_payload({
        "event_id": "evt-1", "token": "update-token", "operator_id": "ou-1",
        "message_id": "om-1", "chat_id": "oc-1", "action_name": "skill_preview_7",
        "action_value": '{"action":"skill_preview_7"}',
        "form_value": '{"limit":"50","campaign_id":"education_fuzhou_offline"}',
    })
    assert payload["header"]["event_id"] == "evt-1"
    assert payload["event"]["action"]["name"] == "skill_preview_7"
    assert payload["event"]["action"]["form_value"]["limit"] == "50"
