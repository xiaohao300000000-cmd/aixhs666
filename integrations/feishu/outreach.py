from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.webhook import verify_callback_token
from services.outreach_generation import OutreachGenerator
from storage.models import CollectionEvent, LeadOutreachMessage, LeadScreeningResult, PublicProfile


OUTREACH_EVENT_TYPE = "feishu_outreach_callback"


class OutreachAction(StrEnum):
    SEND = "send"
    SKIP = "skip"


class OutreachCardClient(Protocol):
    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        """Send one interactive card and return message_id/chat_id."""

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        """Update the original interactive card with the callback token."""


class XiaohongshuMessageSender(Protocol):
    def send_message(self, *, profile_url: str, text: str) -> dict[str, str]:
        """Send one direct message to a Xiaohongshu public profile."""


@dataclass(frozen=True, slots=True)
class OutreachCallbackAction:
    callback_id: str
    action: OutreachAction
    outreach_id: int
    reviewer_id: str | None
    message_id: str | None
    chat_id: str | None
    update_token: str | None
    final_text: str | None


@dataclass(frozen=True, slots=True)
class OutreachCallbackResult:
    applied: bool
    duplicate: bool
    event_id: int | None
    outreach_id: int
    status: str


class OutreachCallbackError(ValueError):
    pass


def create_outreach_for_valid_screening(
    session: Session,
    *,
    screening_id: int,
    generator: OutreachGenerator,
    card_client: OutreachCardClient,
    chat_id: str,
) -> LeadOutreachMessage | None:
    screening = session.get(LeadScreeningResult, screening_id)
    if screening is None:
        raise ValueError(f"screening result not found: {screening_id}")
    if screening.human_review_status != "valid":
        return None
    existing = session.scalar(
        select(LeadOutreachMessage).where(LeadOutreachMessage.screening_result_id == screening_id)
    )
    if existing is not None:
        if existing.feishu_message_id:
            return existing
        outreach = existing
    else:
        draft = generator.generate(screening)
        outreach = LeadOutreachMessage(
            screening_result_id=screening.id,
            public_profile_id=screening.public_profile_id,
            platform=screening.platform,
            target_profile_url=_target_profile_url(session, screening),
            generated_text=draft.text,
            model_name=draft.model_name,
            status="draft",
        )
        session.add(outreach)
        session.flush()

    response = card_client.send_interactive_card(
        chat_id=chat_id,
        card=build_outreach_approval_card(outreach, screening),
    )
    outreach.feishu_message_id = response.get("message_id")
    outreach.feishu_chat_id = response.get("chat_id") or chat_id
    outreach.feishu_card_status = "sent"
    outreach.status = "card_sent"
    outreach.last_error = None
    outreach.updated_at = _utc_now()
    session.flush()
    return outreach


def build_outreach_approval_card(outreach: LeadOutreachMessage, screening: LeadScreeningResult) -> dict[str, Any]:
    context = screening.context_json or {}
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "小红书私信话术审批"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {"tag": "markdown", "content": f"**原评论**\n{_quote(_source_text(context))}"},
                {"tag": "markdown", "content": _screening_summary(screening)},
                {
                    "tag": "form",
                    "name": f"outreach_form_{outreach.id}",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "message_text",
                            "label": {"tag": "plain_text", "content": "待发送话术"},
                            "default_value": outreach.generated_text,
                            "input_type": "multiline_text",
                            "placeholder": {"tag": "plain_text", "content": "可手工修改后发送"},
                            "required": True,
                            "max_length": 500,
                            "rows": 5,
                        },
                        {
                            "tag": "button",
                            "name": f"send_outreach_{outreach.id}",
                            "text": {"tag": "plain_text", "content": "发送"},
                            "type": "primary_filled",
                            "width": "fill",
                            "form_action_type": "submit",
                            "confirm": {
                                "title": {"tag": "plain_text", "content": "确认发送？"},
                                "text": {"tag": "plain_text", "content": "将通过小红书私信发送给该用户。"},
                            },
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "跳过"},
                    "type": "default",
                    "width": "fill",
                    "behaviors": [{"type": "callback", "value": {"outreach_id": outreach.id, "action": OutreachAction.SKIP.value}}],
                },
            ],
        },
    }


def build_processed_outreach_card(
    outreach: LeadOutreachMessage,
    *,
    status: str,
    reviewer_id: str | None,
) -> dict[str, Any]:
    title = "小红书私信话术审批 - 已发送" if status == "sent" else "小红书私信话术审批 - 已处理"
    template = "green" if status == "sent" else "grey"
    text = outreach.final_text or outreach.generated_text
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": "\n".join(
                        [
                            f"**处理状态**：{_status_label(status)}",
                            f"**处理人**：{reviewer_id or '未知'}",
                            f"**话术ID**：{outreach.id}",
                            f"**最终话术**\n{_quote(text)}",
                        ]
                    ),
                }
            ],
        },
    }


def apply_outreach_callback(
    session: Session,
    payload: dict[str, Any],
    *,
    card_client: OutreachCardClient | None,
    xhs_sender: XiaohongshuMessageSender,
    verification_token: str | None = None,
    now: datetime | None = None,
) -> OutreachCallbackResult:
    if not verify_callback_token(payload, verification_token):
        raise OutreachCallbackError("invalid Feishu verification token")
    action = parse_outreach_callback_action(payload)
    outreach = session.get(LeadOutreachMessage, action.outreach_id)
    if outreach is None:
        raise OutreachCallbackError(f"outreach message not found: {action.outreach_id}")

    existing = _existing_callback_event(session, action.callback_id)
    if existing is not None or outreach.status in {"sent", "skipped"}:
        return OutreachCallbackResult(
            applied=False,
            duplicate=True,
            event_id=existing.id if existing is not None else None,
            outreach_id=outreach.id,
            status=outreach.status,
        )

    occurred_at = now or _utc_now()
    if action.action == OutreachAction.SKIP:
        outreach.status = "skipped"
        outreach.reviewer_id = action.reviewer_id
        outreach.reviewed_at = occurred_at
        outreach.feishu_message_id = outreach.feishu_message_id or action.message_id
        outreach.feishu_chat_id = outreach.feishu_chat_id or action.chat_id
        outreach.feishu_card_status = "processed"
        outreach.updated_at = occurred_at
        event = _record_event(session, action=action, status="skipped", occurred_at=occurred_at)
        _update_card(card_client, action, outreach, status="skipped")
        return OutreachCallbackResult(True, False, event.id, outreach.id, outreach.status)

    final_text = (action.final_text or outreach.generated_text or "").strip()
    if not final_text:
        raise OutreachCallbackError("outreach message text is empty")
    if len(final_text) > 500:
        raise OutreachCallbackError("outreach message text is too long")
    profile_url = (outreach.target_profile_url or "").strip()
    if not profile_url:
        raise OutreachCallbackError("target Xiaohongshu profile URL is missing")

    outreach.status = "sending"
    outreach.final_text = final_text
    outreach.reviewer_id = action.reviewer_id
    outreach.reviewed_at = occurred_at
    outreach.attempt_count = (outreach.attempt_count or 0) + 1
    outreach.updated_at = occurred_at
    session.flush()

    try:
        xhs_sender.send_message(profile_url=profile_url, text=final_text)
    except Exception as exc:  # noqa: BLE001 - callback should persist retry-visible failure.
        outreach.status = "failed"
        outreach.last_error = str(exc)
        outreach.feishu_card_status = "failed"
        outreach.updated_at = occurred_at
        event = _record_event(session, action=action, status="failed", occurred_at=occurred_at, error=str(exc))
        _update_card(card_client, action, outreach, status="failed")
        return OutreachCallbackResult(True, False, event.id, outreach.id, outreach.status)

    outreach.status = "sent"
    outreach.sent_at = occurred_at
    outreach.last_error = None
    outreach.feishu_message_id = outreach.feishu_message_id or action.message_id
    outreach.feishu_chat_id = outreach.feishu_chat_id or action.chat_id
    outreach.feishu_card_status = "processed"
    outreach.updated_at = occurred_at
    event = _record_event(session, action=action, status="sent", occurred_at=occurred_at)
    _update_card(card_client, action, outreach, status="sent")
    return OutreachCallbackResult(True, False, event.id, outreach.id, outreach.status)


def parse_outreach_callback_action(payload: dict[str, Any]) -> OutreachCallbackAction:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action_payload = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action_payload.get("value") if isinstance(action_payload.get("value"), dict) else {}
    name = str(action_payload.get("name") or "")
    raw_action = str(value.get("action") or "")
    if name.startswith("send_outreach_"):
        action = OutreachAction.SEND
        outreach_id = int(name.rsplit("_", 1)[-1])
    elif raw_action == OutreachAction.SKIP.value:
        action = OutreachAction.SKIP
        outreach_id = int(value["outreach_id"])
    else:
        raise OutreachCallbackError("not an outreach callback")

    form_value = action_payload.get("form_value") if isinstance(action_payload.get("form_value"), dict) else {}
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    return OutreachCallbackAction(
        callback_id=_callback_id(payload, action=action.value, target_id=str(outreach_id)),
        action=action,
        outreach_id=outreach_id,
        reviewer_id=_reviewer_id(event),
        message_id=context.get("open_message_id") or event.get("message_id"),
        chat_id=context.get("open_chat_id") or event.get("chat_id"),
        update_token=event.get("token"),
        final_text=str(form_value.get("message_text") or "").strip() or None,
    )


def is_outreach_callback(payload: dict[str, Any]) -> bool:
    try:
        parse_outreach_callback_action(payload)
    except (OutreachCallbackError, KeyError, TypeError, ValueError):
        return False
    return True


def _target_profile_url(session: Session, screening: LeadScreeningResult) -> str | None:
    if screening.public_profile_id is None:
        return None
    profile = session.get(PublicProfile, screening.public_profile_id)
    if profile is None:
        return None
    if profile.profile_url:
        return profile.profile_url
    if profile.platform == "xhs" and profile.platform_user_id:
        return f"https://www.xiaohongshu.com/user/profile/{profile.platform_user_id}"
    return None


def _record_event(
    session: Session,
    *,
    action: OutreachCallbackAction,
    status: str,
    occurred_at: datetime,
    error: str | None = None,
) -> CollectionEvent:
    event = CollectionEvent(
        event_type=OUTREACH_EVENT_TYPE,
        entity_type="lead_outreach_message",
        entity_id=action.outreach_id,
        event_data={
            "callback_id": action.callback_id,
            "action": action.action.value,
            "outreach_id": action.outreach_id,
            "reviewer_id": action.reviewer_id,
            "message_id": action.message_id,
            "chat_id": action.chat_id,
            "status": status,
            "error": error,
        },
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def _existing_callback_event(session: Session, callback_id: str) -> CollectionEvent | None:
    return session.scalar(
        select(CollectionEvent)
        .where(CollectionEvent.event_type == OUTREACH_EVENT_TYPE)
        .where(CollectionEvent.event_data["callback_id"].as_string() == callback_id)
    )


def _update_card(
    card_client: OutreachCardClient | None,
    action: OutreachCallbackAction,
    outreach: LeadOutreachMessage,
    *,
    status: str,
) -> None:
    if card_client is None or not action.update_token:
        return
    try:
        card_client.update_interactive_card(
            token=action.update_token,
            card=build_processed_outreach_card(outreach, status=status, reviewer_id=action.reviewer_id),
        )
    except Exception as exc:  # noqa: BLE001 - never roll back the send outcome because card update failed.
        detail = f"Feishu card update failed: {exc}"
        outreach.last_error = f"{outreach.last_error}; {detail}" if outreach.last_error else detail


def _screening_summary(screening: LeadScreeningResult) -> str:
    location = screening.qualification_location_json or {}
    resolved = location.get("resolved_location") if isinstance(location.get("resolved_location"), dict) else {}
    context = screening.context_json or {}
    source_url = str(context.get("source_url") or "").strip()
    lines = [
        f"**筛选结果**：{screening.demand_type or '未知'} / {screening.intent_strength or '未知'} / {screening.confidence or 0}%",
        f"**地区原始值**：{resolved.get('raw_value') or _first_location_raw(location) or '无'}",
        f"**标准化地区**：province={resolved.get('province') or '无'}, city={resolved.get('city') or '无'}",
        f"**资格判断**：{screening.qualification_decision or '未知'}",
        f"**qualification reason**：{screening.qualification_human_reason or '无'}",
    ]
    if source_url:
        lines.append(f"**原始内容链接**：{source_url}")
    return "\n".join(lines)


def _source_text(context: dict[str, Any]) -> str:
    current_comment = str(context.get("current_comment") or "").strip()
    if current_comment:
        return current_comment
    return " ".join(str(context.get(key) or "").strip() for key in ("post_title", "post_body") if context.get(key))


def _quote(value: str) -> str:
    text = value.strip() or "暂无"
    return "\n".join(f"> {line}" for line in text.splitlines())


def _first_location_raw(location: dict[str, Any]) -> str | None:
    evidence = location.get("evidence")
    if not isinstance(evidence, list):
        return None
    for item in evidence:
        if isinstance(item, dict) and item.get("raw_value"):
            return str(item["raw_value"])
    return None


def _status_label(status: str) -> str:
    return {"sent": "已发送", "skipped": "已跳过", "failed": "发送失败"}.get(status, status)


def _callback_id(payload: dict[str, Any], *, action: str, target_id: str) -> str:
    for path in (("header", "event_id"), ("event", "event_id"), ("event_id",)):
        value = _nested_value(payload, path)
        if value:
            return str(value)
    return f"lead_outreach_message:{target_id}:{action}"


def _reviewer_id(event: dict[str, Any]) -> str | None:
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    operator_id = operator.get("operator_id") if isinstance(operator.get("operator_id"), dict) else {}
    return operator.get("open_id") or operator.get("user_id") or operator_id.get("open_id") or operator_id.get("user_id")


def _nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)
