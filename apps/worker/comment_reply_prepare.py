from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from integrations.feishu.comment_replies import create_comment_reply_for_valid_screening
from integrations.feishu.im import FeishuIMClient
from scheduler import complete_task, fail_task
from services.comment_reply_generation import OpenAICompatibleCommentReplyGenerator
from storage.models import CollectionTask


COMMENT_REPLY_PREPARE_TASK_TYPES = {"comment_reply_prepare"}


def prepare_comment_reply(
    session_factory: sessionmaker[Session],
    *,
    screening_id: int,
    chat_id: str,
) -> None:
    if not chat_id.strip():
        raise ValueError("comment reply preparation requires a Feishu chat_id")
    with session_factory() as session:
        create_comment_reply_for_valid_screening(
            session,
            screening_id=screening_id,
            generator=OpenAICompatibleCommentReplyGenerator(),
            card_client=FeishuIMClient(),
            chat_id=chat_id,
        )


def run_comment_reply_prepare_task(
    session: Session,
    *,
    task: CollectionTask,
    session_factory: sessionmaker[Session],
) -> CollectionTask:
    payload = task.payload_json if isinstance(task.payload_json, dict) else {}
    try:
        screening_id = int(payload.get("screening_id"))
        chat_id = str(payload.get("chat_id") or "")
        prepare_comment_reply(session_factory, screening_id=screening_id, chat_id=chat_id)
        return complete_task(session, task.id)
    except Exception as exc:
        fail_task(session, task.id, error=str(exc))
        raise
