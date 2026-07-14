from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Literal, Protocol
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from integrations.feishu.webhook import verify_callback_token
from services.comment_reply_generation import CommentReplyGenerator, validate_comment_reply_text
from storage.models import CollectionTask, Comment, Content, Lead, LeadCommentReply, LeadScreeningResult


CommentReplyOutcome = Literal["sent", "failed", "result_unknown"]
_ACTION_RE = re.compile(r"^(confirm|retry)_comment_reply_([1-9][0-9]*)$")


class FeishuMessageClient(Protocol):
    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]: ...
    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CommentReplySendResult:
    outcome: CommentReplyOutcome
    platform_reply_id: str | None = None
    response_json: dict[str, Any] | None = None
    error: str | None = None


class CommentReplyPreSubmitError(RuntimeError):
    """The platform request definitely was not submitted and is safe to retry."""


class CommentReplyWorkflowError(RuntimeError):
    """The approved screening cannot enter the comment-reply workflow."""


class CommentReplySender(Protocol):
    def reply_to_comment(
        self,
        *,
        platform_comment_id: str,
        platform_content_id: str,
        target_url: str | None,
        text: str,
    ) -> CommentReplySendResult: ...


@dataclass(frozen=True, slots=True)
class CommentReplyCallbackResult:
    applied: bool
    duplicate: bool
    reply_id: int
    status: str
    reconciliation_required: bool = False
    card_status: str | None = None
    card_error: str | None = None


@dataclass(frozen=True, slots=True)
class _SendClaim:
    reply_id: int
    attempt_count: int
    platform_comment_id: str
    platform_content_id: str
    target_url: str | None


def create_comment_reply_for_valid_screening(
    session: Session,
    *,
    screening_id: int,
    generator: CommentReplyGenerator,
    card_client: FeishuMessageClient,
    chat_id: str,
) -> LeadCommentReply | None:
    screening = session.get(LeadScreeningResult, screening_id)
    if screening is None:
        raise ValueError(f"screening result not found: {screening_id}")
    source = _valid_comment_source(session, screening)
    if source is None:
        return None
    comment, content = source
    lead = session.scalar(
        select(Lead).where(
            Lead.platform == "xhs",
            Lead.public_profile_id == screening.public_profile_id,
        )
    )
    if lead is None:
        raise CommentReplyWorkflowError(
            f"no xhs lead found for screening {screening.id} public_profile_id={screening.public_profile_id}; create or backfill the lead before generating a comment reply"
        )
    reply = _find_reply(session, screening.id, comment.platform_comment_id)
    if reply is None:
        draft = generator.generate(screening)
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            lead_id=lead.id,
            target_comment_id=comment.id,
            target_platform_comment_id=comment.platform_comment_id,
            target_content_id=content.id,
            target_platform_content_id=content.platform_content_id,
            target_url=content.url,
            draft_text=draft.text,
            model_name=draft.model_name,
            status="pending_review",
        )
        try:
            with session.begin_nested():
                session.add(reply)
                session.flush()
        except IntegrityError:
            reply = _find_reply(session, screening.id, comment.platform_comment_id)
            if reply is None:
                raise
        session.commit()
    elif reply.lead_id is None:
        reply.lead_id = lead.id
        session.commit()
    reply_id = int(reply.id)
    card_claim = f"card-claim:{uuid4().hex}"

    claimed = session.execute(
        update(LeadCommentReply)
        .where(
            LeadCommentReply.id == reply_id,
            LeadCommentReply.feishu_message_id.is_(None),
            or_(
                LeadCommentReply.feishu_card_status.is_(None),
                LeadCommentReply.feishu_card_status == "card_failed",
            ),
        )
        .values(feishu_card_status="card_creating", feishu_chat_id=card_claim, feishu_sync_error=None, updated_at=_utc_now())
    ).rowcount == 1
    session.commit()
    if not claimed:
        return session.get(LeadCommentReply, reply_id)

    try:
        response = card_client.send_interactive_card(
            chat_id=chat_id,
            card=build_comment_reply_approval_card(reply, screening),
        )
    except Exception as exc:
        session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.feishu_card_status == "card_creating",
                LeadCommentReply.feishu_message_id.is_(None),
                LeadCommentReply.feishu_chat_id == card_claim,
            )
            .values(feishu_card_status="card_failed", feishu_sync_error=str(exc), updated_at=_utc_now())
        )
        session.commit()
        raise

    message_id = response.get("message_id")
    if not message_id:
        session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.feishu_card_status == "card_creating",
                LeadCommentReply.feishu_message_id.is_(None),
                LeadCommentReply.feishu_chat_id == card_claim,
            )
            .values(feishu_sync_error="card send returned no message_id; reconciliation required", updated_at=_utc_now())
        )
        session.commit()
        return session.get(LeadCommentReply, reply_id)
    persisted = session.execute(
        update(LeadCommentReply)
        .where(
            LeadCommentReply.id == reply_id,
            LeadCommentReply.feishu_card_status == "card_creating",
            LeadCommentReply.feishu_message_id.is_(None),
            LeadCommentReply.feishu_chat_id == card_claim,
        )
        .values(
            feishu_message_id=message_id,
            feishu_chat_id=response.get("chat_id") or chat_id,
            feishu_card_status="card_pending",
            feishu_sync_error=None,
            updated_at=_utc_now(),
        )
    ).rowcount == 1
    session.commit()
    return session.get(LeadCommentReply, reply_id)


def build_comment_reply_approval_card(
    reply: LeadCommentReply,
    screening: LeadScreeningResult,
    *,
    action: Literal["confirm", "retry"] = "confirm",
) -> dict[str, Any]:
    context = screening.context_json or {}
    customer_name = str(context.get("customer_name") or context.get("profile_name") or "未提供")
    post_url = str(context.get("source_url") or reply.target_url or "")
    demand_summary = str(
        context.get("demand_summary")
        or screening.qualification_human_reason
        or screening.status_reason
        or screening.demand_type
        or "未提供"
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": "小红书评论回复审批"}},
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": f"**原评论**\n> {context.get('current_comment') or ''}"},
                {"tag": "markdown", "content": f"**客户**：{customer_name}\n\n**需求摘要/原因**：{demand_summary}"},
                {"tag": "markdown", "content": f"**帖子**\n[{context.get('post_title') or '查看原帖'}]({post_url})\n\n**回复目标**：{reply.target_platform_comment_id}"},
                {
                    "tag": "form",
                    "name": f"comment_reply_form_{reply.id}",
                    "elements": [
                        {"tag": "input", "name": "comment_reply_text", "label": {"tag": "plain_text", "content": "公开回复"}, "default_value": reply.approved_text or reply.draft_text, "input_type": "multiline_text", "required": True, "max_length": 300, "rows": 4},
                        {"tag": "button", "name": f"{action}_comment_reply_{reply.id}", "text": {"tag": "plain_text", "content": "重试回复" if action == "retry" else "确认回复"}, "type": "primary", "action_type": "form_submit"},
                    ],
                },
            ],
        },
    }


def is_comment_reply_callback(payload: dict[str, Any]) -> bool:
    return _ACTION_RE.fullmatch(_action_name(payload)) is not None


def apply_comment_reply_callback(
    session_factory: sessionmaker[Session],
    payload: dict[str, Any],
    *,
    card_client: FeishuMessageClient,
    sender: CommentReplySender,
    verification_token: str | None,
) -> CommentReplyCallbackResult:
    if not verify_callback_token(payload, verification_token):
        raise ValueError("invalid Feishu callback token")
    event = _event(payload)
    match = _ACTION_RE.fullmatch(_action_name(payload))
    if match is None:
        raise ValueError("not a valid comment reply callback")
    action, reply_id_text = match.groups()
    reply_id = int(reply_id_text)
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    operator_id = operator.get("open_id") or operator.get("user_id")
    if not operator_id:
        raise ValueError("comment reply callback operator identity is required")
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    message_id = str(context.get("open_message_id") or "")
    chat_id = str(context.get("open_chat_id") or "")
    final_text = validate_comment_reply_text(_form_text(payload))

    claim = _claim_send(
        session_factory,
        reply_id=reply_id,
        action=action,
        final_text=final_text,
        operator_id=str(operator_id),
        message_id=message_id,
        chat_id=chat_id,
    )
    if isinstance(claim, CommentReplyCallbackResult):
        return claim

    return _execute_send_claim(
        session_factory,
        claim=claim,
        final_text=final_text,
        update_token=str(event.get("token") or "") or None,
        card_client=card_client,
        sender=sender,
    )


def enqueue_comment_reply_callback(
    session_factory: sessionmaker[Session],
    payload: dict[str, Any],
    *,
    verification_token: str | None,
) -> CommentReplyCallbackResult:
    from scheduler import create_task

    if not verify_callback_token(payload, verification_token):
        raise ValueError("invalid Feishu callback token")
    event = _event(payload)
    match = _ACTION_RE.fullmatch(_action_name(payload))
    if match is None:
        raise ValueError("not a valid comment reply callback")
    action, reply_id_text = match.groups()
    reply_id = int(reply_id_text)
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    operator_id = operator.get("open_id") or operator.get("user_id")
    if not operator_id:
        raise ValueError("comment reply callback operator identity is required")
    context = event.get("context") if isinstance(event.get("context"), dict) else {}
    message_id = str(context.get("open_message_id") or "")
    chat_id = str(context.get("open_chat_id") or "")
    final_text = validate_comment_reply_text(_form_text(payload))
    allowed = ("pending_review",) if action == "confirm" else ("failed",)

    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        if not message_id or message_id != reply.feishu_message_id:
            raise ValueError("comment reply callback message does not match stored message")
        if not chat_id or chat_id != reply.feishu_chat_id:
            raise ValueError("comment reply callback chat does not match stored chat")
        claimed = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.status.in_(allowed))
            .values(
                status="approved_to_send",
                approved_text=final_text,
                approved_by=str(operator_id),
                approved_at=_utc_now(),
                last_error=None,
            )
        ).rowcount == 1
        if not claimed:
            session.refresh(reply)
            return CommentReplyCallbackResult(False, True, reply_id, reply.status)
        create_task(
            session,
            task_type="comment_reply_send",
            platform="xhs",
            target_id=str(reply_id),
            priority=100,
            max_attempts=1,
            payload_json={"update_token": str(event.get("token") or "") or None},
        )
        session.commit()
    return CommentReplyCallbackResult(True, False, reply_id, "approved_to_send")


def execute_approved_comment_reply(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    update_token: str | None,
    card_client: FeishuMessageClient,
    sender: CommentReplySender,
) -> CommentReplyCallbackResult:
    with session_factory() as session:
        claimed = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.status == "approved_to_send")
            .values(
                status="sending",
                last_attempt_at=_utc_now(),
                attempt_count=LeadCommentReply.attempt_count + 1,
                last_error=None,
            )
        ).rowcount == 1
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        if not claimed:
            return CommentReplyCallbackResult(False, True, reply_id, reply.status)
        if not reply.approved_text:
            raise ValueError(f"comment reply approved text is missing: {reply_id}")
        session.commit()
        claim = _SendClaim(
            reply_id=reply_id,
            attempt_count=reply.attempt_count,
            platform_comment_id=reply.target_platform_comment_id,
            platform_content_id=reply.target_platform_content_id,
            target_url=reply.target_url,
        )
        final_text = reply.approved_text

    return _execute_send_claim(
        session_factory,
        claim=claim,
        final_text=final_text,
        update_token=update_token,
        card_client=card_client,
        sender=sender,
    )


def _execute_send_claim(
    session_factory: sessionmaker[Session],
    *,
    claim: _SendClaim,
    final_text: str,
    update_token: str | None,
    card_client: FeishuMessageClient,
    sender: CommentReplySender,
) -> CommentReplyCallbackResult:

    try:
        send_result = sender.reply_to_comment(
            platform_comment_id=claim.platform_comment_id,
            platform_content_id=claim.platform_content_id,
            target_url=claim.target_url,
            text=final_text,
        )
    except CommentReplyPreSubmitError as exc:
        send_result = CommentReplySendResult(outcome="failed", error=str(exc))
    except Exception as exc:
        send_result = CommentReplySendResult(outcome="result_unknown", error=str(exc))
    if not isinstance(send_result, CommentReplySendResult):
        send_result = CommentReplySendResult(
            outcome="result_unknown",
            error=f"sender returned unsupported result type: {type(send_result).__name__}",
        )
    elif send_result.outcome not in {"sent", "failed", "result_unknown"}:
        send_result = CommentReplySendResult(
            outcome="result_unknown",
            platform_reply_id=send_result.platform_reply_id,
            response_json=send_result.response_json,
            error=f"unsupported sender outcome: {send_result.outcome}",
        )

    completed_at = _utc_now()
    with session_factory() as session:
        completed = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == claim.reply_id,
                LeadCommentReply.status == "sending",
                LeadCommentReply.attempt_count == claim.attempt_count,
            )
            .values(
                status=send_result.outcome,
                platform_reply_id=send_result.platform_reply_id,
                platform_response_json=send_result.response_json,
                last_error=_sanitize_persisted_error(send_result.error),
                sent_at=completed_at if send_result.outcome == "sent" else None,
            )
        ).rowcount == 1
        session.commit()
    if not completed:
        with session_factory() as session:
            current = session.get(LeadCommentReply, claim.reply_id)
            if current is None:
                raise ValueError(f"comment reply not found after lost completion ownership: {claim.reply_id}")
            return CommentReplyCallbackResult(False, True, claim.reply_id, current.status, True)

    if update_token:
        try:
            card_client.update_interactive_card(
                token=update_token,
                card=_result_card(claim.reply_id, final_text, send_result, completed_at),
            )
        except Exception as exc:
            with session_factory() as session:
                session.execute(
                    update(LeadCommentReply)
                    .where(
                        LeadCommentReply.id == claim.reply_id,
                        LeadCommentReply.status == send_result.outcome,
                        LeadCommentReply.attempt_count == claim.attempt_count,
                    )
                    .values(feishu_sync_error=str(exc))
                )
                session.commit()
        else:
            with session_factory() as session:
                session.execute(
                    update(LeadCommentReply)
                    .where(
                        LeadCommentReply.id == claim.reply_id,
                        LeadCommentReply.status == send_result.outcome,
                        LeadCommentReply.attempt_count == claim.attempt_count,
                    )
                    .values(feishu_card_status=send_result.outcome, feishu_sync_error=None)
                )
                session.commit()
    return CommentReplyCallbackResult(True, False, claim.reply_id, send_result.outcome)


def reconcile_stale_comment_reply(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    now: datetime,
    card_timeout: timedelta,
    send_timeout: timedelta,
) -> CommentReplyCallbackResult:
    card_cutoff = now - card_timeout
    send_cutoff = now - send_timeout
    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        card_recovered = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.feishu_card_status == "card_creating",
                LeadCommentReply.feishu_message_id.is_(None),
                LeadCommentReply.updated_at <= card_cutoff,
            )
            .values(
                feishu_card_status="card_result_unknown",
                feishu_sync_error="card creation timed out; reconciliation required before retry",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        ).rowcount == 1
        if card_recovered:
            session.commit()
            session.expire_all()
            current = session.get(LeadCommentReply, reply_id)
            return CommentReplyCallbackResult(True, False, reply_id, current.status, True)
        send_recovered = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.status == "sending",
                LeadCommentReply.last_attempt_at.is_not(None),
                LeadCommentReply.last_attempt_at <= send_cutoff,
            )
            .values(
                status="result_unknown",
                last_error="operator reconciliation: stale sending claim requires platform verification",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        ).rowcount == 1
        session.commit()
        session.expire_all()
        current = session.get(LeadCommentReply, reply_id)
        return CommentReplyCallbackResult(send_recovered, not send_recovered, reply_id, current.status, send_recovered)


def adopt_reconciled_comment_reply_card(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    message_id: str,
    chat_id: str,
    operator: str,
    reason: str,
) -> CommentReplyCallbackResult:
    message_id_text = message_id.strip()
    chat_id_text = chat_id.strip()
    operator_text = operator.strip()
    reason_text = reason.strip()
    if not message_id_text:
        raise ValueError("reconciled card message_id is required")
    if not chat_id_text:
        raise ValueError("reconciled card chat_id is required")
    if not operator_text:
        raise ValueError("reconciled card operator is required")
    if not reason_text:
        raise ValueError("reconciled card reason is required")
    audit_text = f"operator {operator_text} adopted reconciled card: {reason_text}"
    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        adopted = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.feishu_card_status == "card_result_unknown",
                LeadCommentReply.feishu_message_id.is_(None),
            )
            .values(
                feishu_message_id=message_id_text,
                feishu_chat_id=chat_id_text,
                feishu_card_status="card_pending",
                feishu_sync_error=audit_text,
                updated_at=_utc_now(),
            )
            .execution_options(synchronize_session=False)
        ).rowcount == 1
        session.commit()
        session.expire_all()
        current = session.get(LeadCommentReply, reply_id)
        return CommentReplyCallbackResult(adopted, not adopted, reply_id, current.status, not adopted)


def confirm_comment_reply_not_sent(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    operator: str,
    reason: str,
    card_client: FeishuMessageClient,
) -> CommentReplyCallbackResult:
    operator_text = operator.strip()
    reason_text = reason.strip()
    if not operator_text:
        raise ValueError("comment reply confirmation operator is required")
    if not reason_text:
        raise ValueError("comment reply confirmation reason is required")
    audit_text = f"operator {operator_text} confirmed result_unknown was not sent: {reason_text}"
    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        screening = session.get(LeadScreeningResult, reply.screening_result_id) if reply.screening_result_id else None
        if screening is None:
            raise ValueError(f"comment reply screening not found: {reply_id}")
        chat_id = (reply.feishu_chat_id or "").strip()
        if not chat_id or chat_id.startswith("card-claim:"):
            raise ValueError(f"comment reply has no usable Feishu chat for retry card: {reply_id}")
        confirmed = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.status == "result_unknown",
            )
            .values(
                status="failed",
                last_error=audit_text,
                feishu_card_status="retry_card_creating",
                feishu_sync_error=audit_text,
                updated_at=_utc_now(),
            )
            .execution_options(synchronize_session=False)
        ).rowcount == 1
        session.commit()
        if not confirmed:
            session.expire_all()
            current = session.get(LeadCommentReply, reply_id)
            card_status = "replaced" if current.feishu_card_status == "card_pending" else "replacement_unknown" if current.feishu_card_status == "retry_card_creating" else "not_replaced"
            return CommentReplyCallbackResult(False, True, reply_id, current.status, card_status != "replaced", card_status, current.feishu_sync_error)
        session.refresh(reply)
        retry_card = build_comment_reply_approval_card(reply, screening, action="retry")

    try:
        response = card_client.send_interactive_card(chat_id=chat_id, card=retry_card)
    except Exception as exc:
        error = f"retry card replacement result unknown; reconcile Feishu before another replacement: {exc}"
        with session_factory() as session:
            session.execute(
                update(LeadCommentReply)
                .where(
                    LeadCommentReply.id == reply_id,
                    LeadCommentReply.status == "failed",
                    LeadCommentReply.feishu_card_status == "retry_card_creating",
                )
                .values(feishu_sync_error=error, updated_at=_utc_now())
            )
            session.commit()
        return CommentReplyCallbackResult(True, False, reply_id, "failed", True, "replacement_unknown", error)

    message_id = (response.get("message_id") or "").strip()
    if not message_id:
        error = "retry card replacement returned no message_id; reconcile Feishu before another replacement"
        with session_factory() as session:
            session.execute(
                update(LeadCommentReply)
                .where(LeadCommentReply.id == reply_id, LeadCommentReply.feishu_card_status == "retry_card_creating")
                .values(feishu_sync_error=error, updated_at=_utc_now())
            )
            session.commit()
        return CommentReplyCallbackResult(True, False, reply_id, "failed", True, "replacement_unknown", error)

    with session_factory() as session:
        replaced = session.execute(
            update(LeadCommentReply)
            .where(
                LeadCommentReply.id == reply_id,
                LeadCommentReply.status == "failed",
                LeadCommentReply.feishu_card_status == "retry_card_creating",
            )
            .values(
                feishu_message_id=message_id,
                feishu_chat_id=response.get("chat_id") or chat_id,
                feishu_card_status="card_pending",
                feishu_sync_error=audit_text,
                updated_at=_utc_now(),
            )
        ).rowcount == 1
        session.commit()
    if not replaced:
        error = "retry card was sent but database binding lost ownership; operator reconciliation required"
        return CommentReplyCallbackResult(True, False, reply_id, "failed", True, "replacement_unknown", error)
    return CommentReplyCallbackResult(True, False, reply_id, "failed", False, "replaced", None)


def _claim_send(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    action: str,
    final_text: str,
    operator_id: str,
    message_id: str,
    chat_id: str,
) -> _SendClaim | CommentReplyCallbackResult:
    allowed = ("pending_review",) if action == "confirm" else ("failed",)
    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        if not message_id or message_id != reply.feishu_message_id:
            raise ValueError("comment reply callback message does not match stored message")
        if not chat_id or chat_id != reply.feishu_chat_id:
            raise ValueError("comment reply callback chat does not match stored chat")
        claimed = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.status.in_(allowed))
            .values(
                status="sending",
                approved_text=final_text,
                approved_by=operator_id,
                approved_at=_utc_now(),
                last_attempt_at=_utc_now(),
                attempt_count=LeadCommentReply.attempt_count + 1,
                last_error=None,
            )
        ).rowcount == 1
        if not claimed:
            session.refresh(reply)
            return CommentReplyCallbackResult(False, True, reply_id, reply.status)
        session.commit()
        claimed_reply = session.get(LeadCommentReply, reply_id)
        return _SendClaim(
            reply_id=reply_id,
            attempt_count=claimed_reply.attempt_count,
            platform_comment_id=claimed_reply.target_platform_comment_id,
            platform_content_id=claimed_reply.target_platform_content_id,
            target_url=claimed_reply.target_url,
        )


def _find_reply(session: Session, screening_id: int, platform_comment_id: str) -> LeadCommentReply | None:
    return session.scalar(
        select(LeadCommentReply).where(
            (LeadCommentReply.screening_result_id == screening_id)
            | (LeadCommentReply.target_platform_comment_id == platform_comment_id)
        )
    )


def _valid_comment_source(session: Session, screening: LeadScreeningResult) -> tuple[Comment, Content] | None:
    if screening.platform != "xhs" or screening.source_entity_type != "comment" or screening.review_status != "accepted" or screening.human_review_status != "valid" or screening.comment_id is None or screening.content_id is None:
        return None
    comment = session.get(Comment, screening.comment_id)
    content = session.get(Content, screening.content_id)
    if comment is None or content is None or comment.content_id != content.id or screening.source_entity_id != comment.id:
        return None
    return comment, content


def _event(payload: dict[str, Any]) -> dict[str, Any]:
    wrapped = payload.get("event")
    return wrapped if isinstance(wrapped, dict) else payload


def _action_name(payload: dict[str, Any]) -> str:
    event = _event(payload)
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    return str(action.get("name") or "")


def _form_text(payload: dict[str, Any]) -> str:
    event = _event(payload)
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    form = action.get("form_value") if isinstance(action.get("form_value"), dict) else {}
    return str(form.get("comment_reply_text") or "")


def _result_card(reply_id: int, text: str, result: CommentReplySendResult, completed_at: datetime) -> dict[str, Any]:
    if result.outcome == "sent":
        label = "评论成功"
        detail = f"**发送时间**：{completed_at.isoformat()}\n**平台回复ID**：{result.platform_reply_id or '未返回'}"
    elif result.outcome == "failed":
        label = "发送失败，可重试"
        detail = f"**错误**：{result.error or '未知错误'}"
    else:
        label = "发送结果未知，请人工核验"
        detail = f"**核验信息**：{result.error or '平台结果未确认'}"
    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": f"**状态：{label}**\n\n**最终回复**\n{text}\n\n{detail}"}]
    if result.outcome == "failed":
        elements.append({"tag": "form", "name": f"comment_reply_retry_form_{reply_id}", "elements": [{"tag": "input", "name": "comment_reply_text", "default_value": text, "required": True}, {"tag": "button", "name": f"retry_comment_reply_{reply_id}", "text": {"tag": "plain_text", "content": "重试"}, "type": "primary", "action_type": "form_submit"}]})
    return {"schema": "2.0", "config": {"update_multi": True}, "header": {"template": "green" if result.outcome == "sent" else "orange", "title": {"tag": "plain_text", "content": "小红书评论回复"}}, "body": {"elements": elements}}


def _sanitize_persisted_error(error: str | None) -> str | None:
    if error is None:
        return None
    sanitized = " ".join(error.split())
    return sanitized[:1000] or None


def _utc_now() -> datetime:
    return datetime.now(UTC)
