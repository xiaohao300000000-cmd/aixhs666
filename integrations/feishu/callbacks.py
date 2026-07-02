from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.phrase_review import PhraseReviewAction
from integrations.feishu.webhook import verify_callback_token
from storage.models import CollectionEvent, Query


PHRASE_REVIEW_EVENT_TYPE = "feishu_phrase_review_callback"
SIGNAL_ALERT_EVENT_TYPE = "feishu_signal_alert_callback"


@dataclass(frozen=True, slots=True)
class FeishuCallbackAction:
    callback_id: str
    action: str
    target_type: str
    target_id: str
    reviewer_id: str | None
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FeishuCallbackResult:
    applied: bool
    duplicate: bool
    event_id: int | None
    query_id: int | None = None


class FeishuCallbackError(ValueError):
    """Raised when a callback cannot be verified or parsed."""


def apply_phrase_review_callback(
    session: Session,
    payload: dict[str, Any],
    *,
    verification_token: str | None = None,
    now: datetime | None = None,
) -> FeishuCallbackResult:
    if not verify_callback_token(payload, verification_token):
        raise FeishuCallbackError("invalid Feishu verification token")

    action = parse_callback_action(payload)
    normalized = PhraseReviewAction(action.action)
    if action.target_type != "candidate":
        raise FeishuCallbackError(f"expected candidate callback, got {action.target_type}")

    existing = _existing_callback_event(session, PHRASE_REVIEW_EVENT_TYPE, action.callback_id)
    if existing is not None:
        query_id = None
        event_data = existing.event_data or {}
        if isinstance(event_data.get("query_id"), int):
            query_id = event_data["query_id"]
        return FeishuCallbackResult(applied=False, duplicate=True, event_id=existing.id, query_id=query_id)

    query_id = None
    if normalized == PhraseReviewAction.CONVERT_TO_QUERY:
        query = _create_query_from_callback(session, action)
        query_id = query.id

    event = _record_callback_event(
        session,
        event_type=PHRASE_REVIEW_EVENT_TYPE,
        entity_type="phrase_candidate",
        entity_id=action.target_id,
        action=action,
        occurred_at=now or datetime.now(UTC),
        extra={"query_id": query_id, "review_status": _review_status(normalized)},
    )
    return FeishuCallbackResult(applied=True, duplicate=False, event_id=event.id, query_id=query_id)


def apply_signal_alert_callback(
    session: Session,
    payload: dict[str, Any],
    *,
    verification_token: str | None = None,
    now: datetime | None = None,
) -> FeishuCallbackResult:
    if not verify_callback_token(payload, verification_token):
        raise FeishuCallbackError("invalid Feishu verification token")
    action = parse_callback_action(payload)
    if action.target_type != "alert":
        raise FeishuCallbackError(f"expected alert callback, got {action.target_type}")

    existing = _existing_callback_event(session, SIGNAL_ALERT_EVENT_TYPE, action.callback_id)
    if existing is not None:
        return FeishuCallbackResult(applied=False, duplicate=True, event_id=existing.id)

    event = _record_callback_event(
        session,
        event_type=SIGNAL_ALERT_EVENT_TYPE,
        entity_type="signal_alert",
        entity_id=action.target_id,
        action=action,
        occurred_at=now or datetime.now(UTC),
    )
    return FeishuCallbackResult(applied=True, duplicate=False, event_id=event.id)


def parse_callback_action(payload: dict[str, Any]) -> FeishuCallbackAction:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    action_payload = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action_payload.get("value") if isinstance(action_payload.get("value"), dict) else {}
    action = value.get("action")
    if not action:
        raise FeishuCallbackError("Feishu callback action is missing")

    candidate_id = value.get("candidate_id")
    alert_id = value.get("alert_id")
    target_type = "candidate" if candidate_id else "alert" if alert_id else None
    target_id = candidate_id or alert_id
    if target_type is None or target_id is None:
        raise FeishuCallbackError("Feishu callback target id is missing")

    callback_id = _callback_id(payload, action=str(action), target_id=str(target_id))
    return FeishuCallbackAction(
        callback_id=callback_id,
        action=str(action),
        target_type=target_type,
        target_id=str(target_id),
        reviewer_id=_reviewer_id(event),
        value=value,
    )


def _existing_callback_event(session: Session, event_type: str, callback_id: str) -> CollectionEvent | None:
    return session.scalar(
        select(CollectionEvent)
        .where(CollectionEvent.event_type == event_type)
        .where(CollectionEvent.event_data["callback_id"].as_string() == callback_id)
    )


def _record_callback_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    action: FeishuCallbackAction,
    occurred_at: datetime,
    extra: dict[str, Any] | None = None,
) -> CollectionEvent:
    event_data = {
        "callback_id": action.callback_id,
        "action": action.action,
        "target_type": action.target_type,
        "target_id": action.target_id,
        "reviewer_id": action.reviewer_id,
        "value": action.value,
    }
    if extra:
        event_data.update(extra)
    event = CollectionEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=0,
        event_data={**event_data, "external_entity_id": entity_id},
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def _create_query_from_callback(session: Session, action: FeishuCallbackAction) -> Query:
    query_text = str(action.value.get("query_text") or action.value.get("phrase") or action.target_id).strip()
    if not query_text:
        raise FeishuCallbackError("convert_to_query callback requires query_text, phrase, or candidate id")
    query = Query(
        query_text=query_text,
        platform=str(action.value.get("platform") or "xhs"),
        query_type="seed",
        status="active",
        source="feishu_phrase_review",
    )
    session.add(query)
    session.flush()
    return query


def _callback_id(payload: dict[str, Any], *, action: str, target_id: str) -> str:
    for path in (("header", "event_id"), ("event", "event_id"), ("event_id",)):
        value = _nested_value(payload, path)
        if value:
            return str(value)
    return f"{target_id}:{action}"


def _reviewer_id(event: dict[str, Any]) -> str | None:
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    return operator.get("open_id") or operator.get("user_id") or operator.get("union_id")


def _review_status(action: PhraseReviewAction) -> str:
    if action == PhraseReviewAction.APPROVE:
        return "approved"
    if action == PhraseReviewAction.REJECT:
        return "rejected"
    return "converted_to_query"


def _nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
