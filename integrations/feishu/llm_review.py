from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.webhook import verify_callback_token
from services.lead_screening_flow import PENDING_FEISHU, REVIEWED, SEND_UNCERTAIN, SENDING, SENT
from storage.models import CollectionEvent, Lead, LeadEvidence, LeadScreeningResult


LLM_REVIEW_EVENT_TYPE = "feishu_llm_review_callback"


class LLMReviewAction(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    WATCH = "watch"


class LLMReviewCardClient(Protocol):
    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        """Send one interactive card and return message_id/chat_id."""

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        """Update the original interactive card with the callback token."""


@dataclass(frozen=True, slots=True)
class LLMReviewCallbackAction:
    callback_id: str
    action: LLMReviewAction
    screening_result_id: int
    reviewer_id: str | None
    message_id: str | None
    chat_id: str | None
    update_token: str | None
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMReviewCallbackResult:
    applied: bool
    duplicate: bool
    event_id: int | None
    screening_result_id: int
    human_review_status: str | None = None


class LLMReviewCallbackError(ValueError):
    pass


class FeishuSendUncertainError(RuntimeError):
    """Raised when Feishu may have received the request but local state is uncertain."""


def build_llm_review_card(screening: LeadScreeningResult) -> dict[str, Any]:
    context = screening.context_json or {}
    evidence = screening.judgment_evidence_json or []
    original = _source_text(context)
    dashboard_url = os.getenv("FEISHU_LLM_REVIEW_DASHBOARD_URL", "").strip()
    dashboard_line = f"\n\n**多维表格仪表盘**：{dashboard_url}" if dashboard_url else ""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "template": _header_template(screening),
            "title": {"tag": "plain_text", "content": "LLM 客户线索审核"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 16px 12px",
            "elements": [
                {"tag": "markdown", "content": f"**原文**\n{_quote(original)}"},
                {"tag": "markdown", "content": _metadata_markdown(screening)},
                {"tag": "markdown", "content": f"**上下文摘要**\n{_context_summary(context)}{dashboard_line}"},
                {"tag": "markdown", "content": f"**证据**\n{_evidence_markdown(evidence)}"},
                {"tag": "markdown", "content": _qualification_markdown(screening, context)},
                {"tag": "markdown", "content": f"**AI说明**\n{screening.status_reason or _raw_reason(screening) or '无'}"},
                _button("有效", LLMReviewAction.VALID, screening.id, "primary_filled"),
                _button("无效", LLMReviewAction.INVALID, screening.id, "danger"),
                _button("暂时观察", LLMReviewAction.WATCH, screening.id, "default"),
            ],
        },
    }


def build_processed_llm_review_card(screening: LeadScreeningResult, *, action: LLMReviewAction, reviewer_id: str | None) -> dict[str, Any]:
    card = build_llm_review_card(screening)
    card["header"] = {
        "template": "green" if action == LLMReviewAction.VALID else "grey",
        "title": {"tag": "plain_text", "content": "LLM 客户线索审核 - 已处理"},
    }
    body = card.setdefault("body", {})
    elements = body.get("elements") if isinstance(body.get("elements"), list) else []
    body["elements"] = [
        {
            "tag": "markdown",
            "content": (
                f"**已处理**：{_action_label(action)}\n"
                f"**处理人**：{reviewer_id or '未知'}\n"
                f"**分析ID**：{screening.id}"
            ),
        },
        *[element for element in elements if element.get("tag") != "button"],
    ]
    return card


def send_pending_llm_review_cards(
    session: Session,
    *,
    client: LLMReviewCardClient,
    chat_id: str,
    limit: int = 10,
    screening_ids: set[int] | None = None,
) -> dict[str, int]:
    counts = {"sent": 0, "skipped": 0, "failed": 0}
    screenings = claim_pending_llm_review_cards(session, limit=limit, screening_ids=screening_ids)
    for screening in screenings:
        if screening.id is None:
            counts["skipped"] += 1
            continue
        try:
            response = client.send_interactive_card(chat_id=chat_id, card=build_llm_review_card(screening))
        except FeishuSendUncertainError as exc:
            screening.workflow_status = SEND_UNCERTAIN
            screening.last_error = str(exc)
            screening.updated_at = _utc_now()
            counts["failed"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - batch should continue; caller gets failed count.
            screening.workflow_status = PENDING_FEISHU
            screening.last_error = str(exc)
            screening.updated_at = _utc_now()
            counts["failed"] += 1
            continue
        screening.feishu_message_id = response.get("message_id")
        screening.feishu_chat_id = response.get("chat_id") or chat_id
        screening.feishu_card_status = "sent"
        screening.workflow_status = SENT
        screening.last_error = None
        screening.updated_at = _utc_now()
        counts["sent"] += 1
    session.flush()
    return counts


def claim_pending_llm_review_cards(
    session: Session,
    *,
    limit: int = 10,
    screening_ids: set[int] | None = None,
) -> list[LeadScreeningResult]:
    statement = (
        select(LeadScreeningResult)
        .where(LeadScreeningResult.workflow_status == PENDING_FEISHU)
        .where(LeadScreeningResult.qualification_decision.in_(("qualified", "needs_review")))
        .where(LeadScreeningResult.human_review_status.is_(None))
        .where(LeadScreeningResult.feishu_message_id.is_(None))
        .order_by(LeadScreeningResult.id.asc())
        .with_for_update(skip_locked=True)
    )
    if screening_ids:
        statement = statement.where(LeadScreeningResult.id.in_(screening_ids))
    screenings = session.scalars(statement.limit(limit)).all()
    for screening in screenings:
        screening.attempt_count = (screening.attempt_count or 0) + 1
        screening.workflow_status = SENDING
        screening.last_error = None
        screening.updated_at = _utc_now()
    session.flush()
    return screenings


def apply_llm_review_callback(
    session: Session,
    payload: dict[str, Any],
    *,
    client: LLMReviewCardClient,
    verification_token: str | None = None,
    now: datetime | None = None,
) -> LLMReviewCallbackResult:
    if not verify_callback_token(payload, verification_token):
        raise LLMReviewCallbackError("invalid Feishu verification token")
    action = parse_llm_review_callback_action(payload)
    screening = session.get(LeadScreeningResult, action.screening_result_id)
    if screening is None:
        raise LLMReviewCallbackError(f"screening result not found: {action.screening_result_id}")

    existing = _existing_callback_event(session, action.callback_id)
    prior = _existing_result_review_event(session, action.screening_result_id)
    if existing is not None or screening.human_review_status is not None or prior is not None:
        if screening.human_review_status is not None and screening.workflow_status != REVIEWED:
            screening.workflow_status = REVIEWED
            screening.updated_at = now or _utc_now()
        event_id = existing.id if existing is not None else prior.id if prior is not None else None
        return LLMReviewCallbackResult(
            applied=False,
            duplicate=True,
            event_id=event_id,
            screening_result_id=action.screening_result_id,
            human_review_status=screening.human_review_status,
        )

    occurred_at = now or _utc_now()
    screening.human_review_status = action.action.value
    screening.human_reviewer_id = action.reviewer_id
    screening.human_reviewed_at = occurred_at
    screening.feishu_message_id = screening.feishu_message_id or action.message_id
    screening.feishu_chat_id = screening.feishu_chat_id or action.chat_id
    screening.feishu_card_status = "processed"
    screening.workflow_status = REVIEWED
    screening.last_error = None
    screening.updated_at = occurred_at
    _update_related_lead(session, screening, action.action)
    event = _record_review_event(session, action=action, occurred_at=occurred_at)
    if action.update_token:
        client.update_interactive_card(
            token=action.update_token,
            card=build_processed_llm_review_card(screening, action=action.action, reviewer_id=action.reviewer_id),
        )
    return LLMReviewCallbackResult(
        applied=True,
        duplicate=False,
        event_id=event.id,
        screening_result_id=action.screening_result_id,
        human_review_status=action.action.value,
    )


def parse_llm_review_callback_action(payload: dict[str, Any]) -> LLMReviewCallbackAction:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action_payload = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action_payload.get("value") if isinstance(action_payload.get("value"), dict) else {}
    action_text = value.get("action")
    if not action_text:
        raise LLMReviewCallbackError("Feishu callback action is missing")
    try:
        action = LLMReviewAction(str(action_text))
    except ValueError as exc:
        raise LLMReviewCallbackError(f"unknown LLM review action: {action_text}") from exc
    screening_result_id = value.get("screening_result_id") or value.get("analysis_result_id")
    if screening_result_id is None:
        raise LLMReviewCallbackError("screening_result_id is missing")
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    callback_id = _callback_id(payload, action=action.value, target_id=str(screening_result_id))
    return LLMReviewCallbackAction(
        callback_id=callback_id,
        action=action,
        screening_result_id=int(screening_result_id),
        reviewer_id=_reviewer_id(event),
        message_id=context.get("open_message_id") or event.get("message_id"),
        chat_id=context.get("open_chat_id") or event.get("chat_id"),
        update_token=event.get("token"),
        value=value,
    )


def _update_related_lead(session: Session, screening: LeadScreeningResult, action: LLMReviewAction) -> None:
    evidence = session.scalar(
        select(LeadEvidence).where(
            LeadEvidence.source_entity_type == screening.source_entity_type,
            LeadEvidence.source_entity_id == screening.source_entity_id,
        )
    )
    if evidence is None:
        return
    lead = session.get(Lead, evidence.lead_id)
    if lead is None:
        return
    if action == LLMReviewAction.VALID:
        lead.status = "qualified"
    elif action == LLMReviewAction.INVALID:
        lead.status = "ignored"
    else:
        lead.status = "needs_enrichment"
    lead.last_feedback_at = screening.human_reviewed_at
    lead.updated_at = screening.human_reviewed_at or _utc_now()


def _record_review_event(
    session: Session,
    *,
    action: LLMReviewCallbackAction,
    occurred_at: datetime,
) -> CollectionEvent:
    event = CollectionEvent(
        event_type=LLM_REVIEW_EVENT_TYPE,
        entity_type="lead_screening_result",
        entity_id=action.screening_result_id,
        event_data={
            "callback_id": action.callback_id,
            "action": action.action.value,
            "screening_result_id": action.screening_result_id,
            "reviewer_id": action.reviewer_id,
            "message_id": action.message_id,
            "chat_id": action.chat_id,
            "human_review_status": action.action.value,
            "value": action.value,
        },
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def _existing_callback_event(session: Session, callback_id: str) -> CollectionEvent | None:
    return session.scalar(
        select(CollectionEvent)
        .where(CollectionEvent.event_type == LLM_REVIEW_EVENT_TYPE)
        .where(CollectionEvent.event_data["callback_id"].as_string() == callback_id)
    )


def _existing_result_review_event(session: Session, screening_result_id: int) -> CollectionEvent | None:
    return session.scalar(
        select(CollectionEvent)
        .where(CollectionEvent.event_type == LLM_REVIEW_EVENT_TYPE)
        .where(CollectionEvent.entity_type == "lead_screening_result")
        .where(CollectionEvent.entity_id == screening_result_id)
    )


def _callback_id(payload: dict[str, Any], *, action: str, target_id: str) -> str:
    for path in (("header", "event_id"), ("event", "event_id"), ("event_id",)):
        value = _nested_value(payload, path)
        if value:
            return str(value)
    return f"lead_screening_result:{target_id}:{action}"


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


def _button(label: str, action: LLMReviewAction, screening_id: int | None, button_type: str) -> dict[str, Any]:
    value = {"screening_result_id": screening_id, "action": action.value}
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "behaviors": [{"type": "callback", "value": value}],
        "type": button_type,
        "width": "fill",
    }


def _metadata_markdown(screening: LeadScreeningResult) -> str:
    return "\n".join(
        [
            f"**分析ID**：{screening.id}",
            f"**AI判断**：{screening.demand_type or '未知'}",
            f"**意向等级**：{screening.intent_strength or '未知'}",
            f"**置信度**：{screening.confidence or 0}%",
        ]
    )


def _qualification_markdown(screening: LeadScreeningResult, context: dict[str, Any]) -> str:
    location = screening.qualification_location_json or {}
    resolved = location.get("resolved_location") if isinstance(location.get("resolved_location"), dict) else {}
    raw_value = resolved.get("raw_value") or _first_location_raw(location)
    normalized = (
        f"province={resolved.get('province') or '无'}, "
        f"city={resolved.get('city') or '无'}"
    )
    lines = [
        "**资格判断**",
        f"- decision：{screening.qualification_decision or '未知'}",
        f"- reason：{screening.qualification_human_reason or '无'}",
        f"- 地区原始值：{raw_value or '无'}",
        f"- 标准化地区：{normalized}",
        f"- Campaign地区匹配：{location.get('match_status') or '未知'} / {location.get('reason') or '无'}",
    ]
    source_url = str(context.get("source_url") or "").strip()
    if source_url:
        lines.append(f"- 原始链接：{source_url}")
    return "\n".join(lines)


def _first_location_raw(location: dict[str, Any]) -> str | None:
    evidence = location.get("evidence")
    if not isinstance(evidence, list):
        return None
    for item in evidence:
        if isinstance(item, dict) and item.get("raw_value"):
            return str(item["raw_value"])
    return None


def _header_template(screening: LeadScreeningResult) -> str:
    confidence = screening.confidence or 0
    if confidence >= 80:
        return "red"
    if confidence >= 60:
        return "orange"
    return "blue"


def _source_text(context: dict[str, Any]) -> str:
    current_comment = str(context.get("current_comment") or "").strip()
    if current_comment:
        return current_comment
    return " ".join(str(context.get(key) or "").strip() for key in ("post_title", "post_body") if context.get(key))


def _context_summary(context: dict[str, Any]) -> str:
    lines = []
    if context.get("post_title"):
        lines.append(f"- 帖子标题：{_short(str(context['post_title']), 80)}")
    if context.get("post_body"):
        lines.append(f"- 帖子正文：{_short(str(context['post_body']), 120)}")
    if context.get("parent_comment"):
        lines.append(f"- 父评论：{_short(str(context['parent_comment']), 120)}")
    return "\n".join(lines) if lines else "暂无上下文"


def _evidence_markdown(evidence: list[Any]) -> str:
    values = [str(item).strip() for item in evidence if str(item).strip()]
    if not values:
        return "- 暂无"
    return "\n".join(f"- {item}" for item in values[:5])


def _raw_reason(screening: LeadScreeningResult) -> str:
    raw = screening.llm_raw_json or {}
    return str(raw.get("reason") or raw.get("判断原因") or "")


def _quote(value: str) -> str:
    text = value.strip() or "暂无原文"
    return "\n".join(f"> {line}" for line in text.splitlines())


def _short(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[:limit - 1]}..."


def _action_label(action: LLMReviewAction) -> str:
    return {
        LLMReviewAction.VALID: "有效",
        LLMReviewAction.INVALID: "无效",
        LLMReviewAction.WATCH: "暂时观察",
    }[action]


def _utc_now() -> datetime:
    return datetime.now(UTC)
