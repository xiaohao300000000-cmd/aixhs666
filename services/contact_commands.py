from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from scheduler import create_task
from storage.models import (
    CollectionTask,
    ContactCommandOperation,
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    Lead,
    LeadCommentReply,
    LeadScreeningResult,
)


CHANNEL = "xiaohongshu_public_reply"
TERMINAL = {"sent", "cancelled"}
EDITABLE = {"pending_review", "awaiting_approval", "approved", "failed"}


def prepare_contact_draft(
    session: Session,
    *,
    customer_id: int,
    idempotency_key: str,
) -> dict[str, Any]:
    key_hash = hashlib.sha256(_required(idempotency_key, "idempotency_key").encode()).hexdigest()
    existing = session.scalar(
        select(ContactCommandOperation).where(
            ContactCommandOperation.operation_scope == "prepare_contact_draft",
            ContactCommandOperation.entity_id == customer_id,
            ContactCommandOperation.idempotency_key_hash == key_hash,
        )
    )
    if existing is not None:
        return dict(existing.result_json)
    lead = session.get(Lead, customer_id)
    if lead is None or lead.status != "qualified":
        raise LookupError("qualified customer not found")
    screening = session.scalar(
        select(LeadScreeningResult)
        .where(
            LeadScreeningResult.public_profile_id == lead.public_profile_id,
            LeadScreeningResult.platform == "xhs",
            LeadScreeningResult.source_entity_type == "comment",
            LeadScreeningResult.review_status == "accepted",
            LeadScreeningResult.human_review_status == "valid",
            LeadScreeningResult.comment_id.is_not(None),
            LeadScreeningResult.content_id.is_not(None),
        )
        .order_by(LeadScreeningResult.updated_at.desc(), LeadScreeningResult.id.desc())
        .limit(1)
    )
    if screening is None:
        result = {"status": "target_unavailable", "customer_id": customer_id, "screening_id": None, "task_id": None}
    else:
        task = session.scalar(
            select(CollectionTask).where(
                CollectionTask.task_type == "comment_reply_prepare",
                CollectionTask.target_id == str(customer_id),
                CollectionTask.status.in_(("pending", "running", "retry", "partial")),
            )
        )
        if task is None:
            task = create_task(
                session,
                task_type="comment_reply_prepare",
                platform="xhs",
                target_id=str(customer_id),
                priority=95,
                max_attempts=3,
                payload_json={
                    "screening_id": screening.id,
                    "chat_id": screening.feishu_chat_id or os.getenv("FEISHU_LLM_REVIEW_CHAT_ID"),
                },
            )
        result = {"status": "queued", "customer_id": customer_id, "screening_id": screening.id, "task_id": task.id}
    session.flush()
    session.add(
        ContactCommandOperation(
            operation_scope="prepare_contact_draft",
            entity_id=customer_id,
            idempotency_key_hash=key_hash,
            request_json={"customer_id": customer_id},
            result_json=result,
        )
    )
    session.flush()
    return result


def edit_contact_draft(
    session: Session,
    *,
    reply_id: int,
    draft_revision: int,
    text: str,
    operator: str,
    idempotency_key: str,
) -> dict[str, Any]:
    normalized = " ".join(text.split())
    if not normalized:
        raise ValueError("draft text is required")
    request = {"draft_revision": draft_revision, "text": normalized, "operator": _required(operator, "operator")}

    def apply(reply: LeadCommentReply) -> dict[str, Any]:
        _require_editable(reply)
        _require_revision(reply, draft_revision)
        reply.draft_text = normalized
        reply.draft_revision += 1
        reply.status = "awaiting_approval"
        _timeline(session, reply, "contact_draft_edited", operator, {"draft_revision": reply.draft_revision})
        return contact_attempt_dict(reply)

    return _operate(session, "edit_contact_draft", reply_id, idempotency_key, request, apply)


def approve_contact_draft(
    session: Session,
    *,
    reply_id: int,
    draft_revision: int,
    operator: str,
    idempotency_key: str,
) -> dict[str, Any]:
    operator = _required(operator, "operator")
    request = {"draft_revision": draft_revision, "operator": operator, "channel": CHANNEL}

    def apply(reply: LeadCommentReply) -> dict[str, Any]:
        _require_mutable(reply)
        _require_revision(reply, draft_revision)
        if reply.status not in {"pending_review", "awaiting_approval", "failed", "approved"}:
            raise ValueError(f"illegal approval state: {reply.status}")
        if reply.status == "approved" and reply.approved_revision == draft_revision and reply.approved_text == reply.draft_text:
            return contact_attempt_dict(reply)
        reply.approved_text = reply.draft_text
        reply.approved_revision = reply.draft_revision
        reply.approved_by = operator
        reply.approved_at = datetime.now(UTC)
        reply.status = "approved"
        _timeline(session, reply, "contact_draft_approved", operator, {"draft_revision": draft_revision, "channel": CHANNEL})
        return contact_attempt_dict(reply)

    return _operate(session, "approve_contact_draft", reply_id, idempotency_key, request, apply)


def send_approved_contact(
    session: Session,
    *,
    reply_id: int,
    draft_revision: int,
    confirmed: bool,
    operator: str,
    idempotency_key: str,
    update_token: str | None = None,
) -> dict[str, Any]:
    operator = _required(operator, "operator")
    if confirmed is not True:
        raise ValueError("confirmed=true is required to send")
    normalized_update_token = update_token.strip() if update_token else None
    request = {
        "draft_revision": draft_revision,
        "confirmed": True,
        "operator": operator,
        "channel": CHANNEL,
        "update_token_present": normalized_update_token is not None,
    }

    def apply(reply: LeadCommentReply) -> dict[str, Any]:
        _require_mutable(reply)
        _require_revision(reply, draft_revision)
        safe = (
            reply.status == "approved"
            and reply.approved_revision == reply.draft_revision
            and reply.approved_text == reply.draft_text
        )
        if not safe:
            raise ValueError("stale or unapproved draft cannot be sent")
        task = session.scalar(
            select(CollectionTask).where(
                CollectionTask.task_type == "comment_reply_send",
                CollectionTask.target_id == str(reply.id),
                CollectionTask.status.in_(("pending", "running", "retry", "partial")),
            )
        )
        if task is None:
            task = create_task(
                session,
                task_type="comment_reply_send",
                platform="xhs",
                target_id=str(reply.id),
                priority=100,
                max_attempts=1,
                payload_json={
                    "draft_revision": reply.draft_revision,
                    **({"update_token": normalized_update_token} if normalized_update_token else {}),
                },
            )
        elif normalized_update_token and not task.payload_json.get("update_token"):
            task.payload_json = {**task.payload_json, "update_token": normalized_update_token}
        reply.status = "queued"
        reply.queued_at = datetime.now(UTC)
        _timeline(session, reply, "contact_send_queued", operator, {"draft_revision": draft_revision, "task_id": task.id})
        result = contact_attempt_dict(reply)
        result["task_id"] = task.id
        return result

    return _operate(session, "send_approved_contact", reply_id, idempotency_key, request, apply)


def record_contact_result(
    session: Session,
    *,
    reply_id: int,
    attempt_count: int,
    draft_revision: int,
    outcome: str,
    idempotency_key: str,
    error: str | None = None,
    platform_reply_id: str | None = None,
    platform_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if outcome not in {"sent", "failed", "result_unknown"}:
        raise ValueError("unsupported contact result")
    request = {"attempt_count": attempt_count, "draft_revision": draft_revision, "outcome": outcome}

    def apply(reply: LeadCommentReply) -> dict[str, Any]:
        if reply.status != "sending" or reply.attempt_count != attempt_count:
            raise ValueError("stale contact result attempt")
        if reply.draft_revision != draft_revision or reply.approved_revision != draft_revision:
            raise ValueError("stale contact result revision")
        now = datetime.now(UTC)
        reply.status = outcome
        reply.last_error = _safe_error(error)
        reply.platform_reply_id = platform_reply_id
        reply.platform_response_json = platform_response
        reply.sent_at = now if outcome == "sent" else None
        if reply.lead_id is not None:
            lead = session.get(Lead, reply.lead_id)
            if lead is not None:
                if outcome == "sent":
                    lead.crm_stage = "contact_sent_waiting_reply"
                    lead.followup_status = "waiting_reply"
                    lead.last_contact_at = now
                    lead.last_contact_result = "public_reply_sent"
                    lead.recommended_next_step = "等待客户公开回复"
                elif outcome == "result_unknown":
                    lead.recommended_next_step = "人工核对小红书目标页面"
                else:
                    lead.recommended_next_step = "检查发送失败原因，修改后重新确认"
                lead.crm_sync_version = (lead.crm_sync_version or 0) + 1
                session.add(
                    CustomerFollowupRecord(
                        lead_id=lead.id,
                        event_key=f"contact-result:{reply.id}:{attempt_count}:{outcome}",
                        occurred_at=now,
                        action_type="发送公开回复",
                        channel=CHANNEL,
                        target=reply.target_url or reply.target_platform_comment_id,
                        content=reply.approved_text,
                        result=outcome,
                        next_step=lead.recommended_next_step,
                        source_entry="comment_reply_worker",
                        platform_evidence_json={"platform_reply_id": platform_reply_id} if platform_reply_id else None,
                        is_completed=outcome == "sent",
                    )
                )
        _timeline(session, reply, f"contact_result_{outcome}", "comment_reply_worker", {"attempt_count": attempt_count})
        return contact_attempt_dict(reply)

    return _operate(session, "record_contact_result", reply_id, idempotency_key, request, apply)


def confirm_contact_not_sent(
    session: Session,
    *,
    reply_id: int,
    operator: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    operator = _required(operator, "operator")
    reason = _required(reason, "reason")
    request = {"operator": operator, "reason": reason}

    def apply(reply: LeadCommentReply) -> dict[str, Any]:
        if reply.status != "result_unknown":
            raise ValueError("only result_unknown can be confirmed not sent")
        reply.status = "failed"
        reply.last_error = f"operator {operator} confirmed not sent: {reason}"[:1000]
        _timeline(session, reply, "contact_result_confirmed_not_sent", operator, {"reason": reason})
        return contact_attempt_dict(reply)

    return _operate(session, "confirm_contact_not_sent", reply_id, idempotency_key, request, apply)


def contact_attempt_dict(reply: LeadCommentReply) -> dict[str, Any]:
    status = {"pending_review": "awaiting_approval", "approved_to_send": "queued"}.get(reply.status, reply.status)
    safe_to_send = (
        status == "approved"
        and reply.approved_revision == reply.draft_revision
        and reply.approved_text == reply.draft_text
    )
    return {
        "attempt_id": reply.id,
        "customer_id": reply.lead_id,
        "channel": CHANNEL,
        "target": {"comment_id": reply.target_platform_comment_id, "url": reply.target_url},
        "draft_text": reply.draft_text,
        "draft_revision": reply.draft_revision,
        "approved_revision": reply.approved_revision,
        "status": status,
        "safe_to_send": safe_to_send,
        "safe_to_retry": status == "failed",
        "next_action": _next_action(status, safe_to_send),
    }


def _operate(
    session: Session,
    scope: str,
    reply_id: int,
    key: str,
    request: dict[str, Any],
    apply: Callable[[LeadCommentReply], dict[str, Any]],
) -> dict[str, Any]:
    key_hash = hashlib.sha256(_required(key, "idempotency_key").encode()).hexdigest()
    existing = session.scalar(
        select(ContactCommandOperation).where(
            ContactCommandOperation.operation_scope == scope,
            ContactCommandOperation.entity_id == reply_id,
            ContactCommandOperation.idempotency_key_hash == key_hash,
        )
    )
    if existing is not None:
        if existing.request_json != request:
            raise ValueError("idempotency_key request mismatch")
        return dict(existing.result_json)
    reply = session.scalar(
        select(LeadCommentReply).where(LeadCommentReply.id == reply_id).with_for_update()
    )
    if reply is None:
        raise LookupError("contact attempt not found")
    result = apply(reply)
    session.flush()
    session.add(
        ContactCommandOperation(
            operation_scope=scope,
            entity_id=reply_id,
            idempotency_key_hash=key_hash,
            request_json=request,
            result_json=result,
        )
    )
    session.flush()
    return result


def _timeline(session: Session, reply: LeadCommentReply, event_type: str, actor: str, data: dict[str, Any]) -> None:
    if reply.lead_id is None:
        return
    session.add(
        CustomerTimelineEvent(
            lead_id=reply.lead_id,
            event_key=f"{event_type}:{reply.id}:{reply.draft_revision}:{reply.attempt_count}",
            event_type=event_type,
            actor_id=actor,
            data_json={"contact_attempt_id": reply.id, **data},
            occurred_at=datetime.now(UTC),
        )
    )


def _require_revision(reply: LeadCommentReply, revision: int) -> None:
    if reply.draft_revision != revision:
        raise ValueError(f"stale draft revision: expected {reply.draft_revision}, got {revision}")


def _require_mutable(reply: LeadCommentReply) -> None:
    if reply.status in TERMINAL:
        raise ValueError(f"terminal contact attempt cannot be changed: {reply.status}")


def _require_editable(reply: LeadCommentReply) -> None:
    if reply.status not in EDITABLE:
        raise ValueError(f"contact attempt cannot be edited in state: {reply.status}")


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _safe_error(error: str | None) -> str | None:
    return " ".join(error.split())[:1000] if error else None


def _next_action(status: str, safe_to_send: bool) -> str:
    if safe_to_send:
        return "send_approved_contact"
    return {
        "awaiting_approval": "approve_contact_draft",
        "failed": "approve_contact_draft",
        "result_unknown": "confirm_contact_not_sent",
        "sent": "wait_for_customer_reply",
    }.get(status, "wait")
