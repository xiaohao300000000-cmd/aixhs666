from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from integrations.feishu.webhook import verify_callback_token
from services.comment_reply_generation import CommentReplyGenerator, validate_comment_reply_text
from storage.models import Comment, Content, LeadCommentReply, LeadScreeningResult


CommentReplyOutcome = Literal["sent", "failed", "result_unknown"]


class FeishuMessageClient(Protocol):
    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]: ...

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CommentReplySendResult:
    outcome: CommentReplyOutcome
    platform_reply_id: str | None = None
    response_json: dict[str, Any] | None = None
    error: str | None = None


class CommentReplySender(Protocol):
    def reply_to_comment(
        self,
        *,
        platform_comment_id: str,
        platform_content_id: str,
        text: str,
    ) -> CommentReplySendResult: ...


@dataclass(frozen=True, slots=True)
class CommentReplyCallbackResult:
    applied: bool
    duplicate: bool
    reply_id: int
    status: str


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

    reply = session.scalar(
        select(LeadCommentReply).where(
            (LeadCommentReply.screening_result_id == screening.id)
            | (LeadCommentReply.target_platform_comment_id == comment.platform_comment_id)
        )
    )
    if reply is None:
        draft = generator.generate(screening)
        reply = LeadCommentReply(
            screening_result_id=screening.id,
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
            reply = session.scalar(
                select(LeadCommentReply).where(
                    (LeadCommentReply.screening_result_id == screening.id)
                    | (LeadCommentReply.target_platform_comment_id == comment.platform_comment_id)
                )
            )
            if reply is None:
                raise

    if reply.feishu_message_id:
        return reply
    response = card_client.send_interactive_card(
        chat_id=chat_id,
        card=build_comment_reply_approval_card(reply, screening),
    )
    reply.feishu_message_id = response.get("message_id")
    reply.feishu_chat_id = response.get("chat_id") or chat_id
    reply.feishu_card_status = "pending_review"
    reply.feishu_sync_error = None
    session.flush()
    return reply


def build_comment_reply_approval_card(
    reply: LeadCommentReply,
    screening: LeadScreeningResult,
) -> dict[str, Any]:
    context = screening.context_json or {}
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": "小红书评论回复审批"}},
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": f"**原评论**\n> {context.get('current_comment') or ''}"},
                {"tag": "markdown", "content": f"**帖子**\n{context.get('post_title') or ''}"},
                {
                    "tag": "form",
                    "name": f"comment_reply_form_{reply.id}",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "comment_reply_text",
                            "label": {"tag": "plain_text", "content": "公开回复"},
                            "default_value": reply.approved_text or reply.draft_text,
                            "input_type": "multiline_text",
                            "required": True,
                            "max_length": 300,
                            "rows": 4,
                        },
                        {
                            "tag": "button",
                            "name": f"confirm_comment_reply_{reply.id}",
                            "text": {"tag": "plain_text", "content": "确认回复"},
                            "type": "primary",
                            "action_type": "form_submit",
                        },
                    ],
                },
            ],
        },
    }


def is_comment_reply_callback(payload: dict[str, Any]) -> bool:
    name = _action_name(payload)
    return name.startswith("confirm_comment_reply_") or name.startswith("retry_comment_reply_")


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
    action_name = _action_name(payload)
    action, reply_id = _parse_action(action_name)
    final_text = validate_comment_reply_text(_form_text(payload))
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    operator_id = operator.get("open_id") or operator.get("user_id")
    now = _utc_now()
    allowed = ("pending_review",) if action == "confirm" else ("failed",)

    with session_factory() as session:
        claimed = session.execute(
            update(LeadCommentReply)
            .where(LeadCommentReply.id == reply_id, LeadCommentReply.status.in_(allowed))
            .values(
                status="sending",
                approved_text=final_text,
                approved_by=operator_id,
                approved_at=now,
                last_attempt_at=now,
                attempt_count=LeadCommentReply.attempt_count + 1,
                last_error=None,
            )
        ).rowcount == 1
        if not claimed:
            existing = session.get(LeadCommentReply, reply_id)
            if existing is None:
                raise ValueError(f"comment reply not found: {reply_id}")
            return CommentReplyCallbackResult(False, True, reply_id, existing.status)
        session.commit()

    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        platform_comment_id = reply.target_platform_comment_id
        platform_content_id = reply.target_platform_content_id

    try:
        send_result = sender.reply_to_comment(
            platform_comment_id=platform_comment_id,
            platform_content_id=platform_content_id,
            text=final_text,
        )
    except Exception as exc:
        send_result = CommentReplySendResult(outcome="result_unknown", error=str(exc))
    if send_result.outcome not in {"sent", "failed", "result_unknown"}:
        raise ValueError(f"unsupported comment reply outcome: {send_result.outcome}")

    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None:
            raise ValueError(f"comment reply not found: {reply_id}")
        reply.status = send_result.outcome
        reply.platform_reply_id = send_result.platform_reply_id
        reply.platform_response_json = send_result.response_json
        reply.last_error = send_result.error
        reply.sent_at = _utc_now() if send_result.outcome == "sent" else None
        session.commit()

    update_token = event.get("token")
    if update_token:
        try:
            card_client.update_interactive_card(
                token=str(update_token),
                card=_result_card(reply_id, final_text, send_result),
            )
        except Exception as exc:
            with session_factory() as session:
                reply = session.get(LeadCommentReply, reply_id)
                if reply is not None:
                    reply.feishu_sync_error = str(exc)
                    session.commit()
        else:
            with session_factory() as session:
                reply = session.get(LeadCommentReply, reply_id)
                if reply is not None:
                    reply.feishu_card_status = send_result.outcome
                    reply.feishu_sync_error = None
                    session.commit()
    return CommentReplyCallbackResult(True, False, reply_id, send_result.outcome)


def _valid_comment_source(
    session: Session,
    screening: LeadScreeningResult,
) -> tuple[Comment, Content] | None:
    if (
        screening.platform != "xhs"
        or screening.source_entity_type != "comment"
        or screening.review_status != "accepted"
        or screening.human_review_status != "valid"
        or screening.comment_id is None
        or screening.content_id is None
    ):
        return None
    comment = session.get(Comment, screening.comment_id)
    content = session.get(Content, screening.content_id)
    if comment is None or content is None or comment.content_id != content.id:
        return None
    if screening.source_entity_id != comment.id:
        return None
    return comment, content


def _action_name(payload: dict[str, Any]) -> str:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    return str(action.get("name") or "")


def _parse_action(name: str) -> tuple[str, int]:
    for action in ("confirm", "retry"):
        prefix = f"{action}_comment_reply_"
        if name.startswith(prefix):
            try:
                return action, int(name.removeprefix(prefix))
            except ValueError as exc:
                raise ValueError("invalid comment reply callback id") from exc
    raise ValueError("not a comment reply callback")


def _form_text(payload: dict[str, Any]) -> str:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    form = action.get("form_value") if isinstance(action.get("form_value"), dict) else {}
    return str(form.get("comment_reply_text") or "")


def _result_card(reply_id: int, text: str, result: CommentReplySendResult) -> dict[str, Any]:
    label = {"sent": "已发送", "failed": "发送失败，可重试", "result_unknown": "发送结果未知，请人工核验"}[result.outcome]
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": f"**状态：{label}**\n\n{text}"},
    ]
    if result.outcome == "failed":
        elements.append(
            {
                "tag": "form",
                "name": f"comment_reply_retry_form_{reply_id}",
                "elements": [
                    {"tag": "input", "name": "comment_reply_text", "default_value": text, "required": True},
                    {
                        "tag": "button",
                        "name": f"retry_comment_reply_{reply_id}",
                        "text": {"tag": "plain_text", "content": "重试"},
                        "type": "primary",
                        "action_type": "form_submit",
                    },
                ],
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"template": "green" if result.outcome == "sent" else "orange", "title": {"tag": "plain_text", "content": "小红书评论回复"}},
        "body": {"elements": elements},
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)
