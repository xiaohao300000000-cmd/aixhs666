from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from collectors.xiaohongshu.browser import XiaohongshuBrowserConfig
from collectors.xiaohongshu.comment_reply import XiaohongshuCommentReplySender
from integrations.feishu.comment_replies import execute_approved_comment_reply
from integrations.feishu.im import FeishuIMClient
from scheduler import TaskStatus, complete_task, fail_task
from services.feishu_customer_followup import push_customer_followup
from services.customer_crm_sync import sync_customer_crm
from storage.models import CollectionTask, LeadCommentReply


COMMENT_REPLY_SEND_TASK_TYPES = {"comment_reply_send"}


def run_comment_reply_send_task(
    session: Session,
    *,
    task: CollectionTask,
    session_factory: sessionmaker[Session],
) -> CollectionTask:
    if task.task_type not in COMMENT_REPLY_SEND_TASK_TYPES:
        fail_task(session, task.id, error=f"unsupported task type: {task.task_type}")
        return task
    try:
        reply_id = int(task.target_id or "")
    except ValueError:
        fail_task(session, task.id, error="comment reply send task target_id is invalid")
        return task
    payload = task.payload_json if isinstance(task.payload_json, dict) else {}
    try:
        draft_revision = int(payload.get("draft_revision"))
        if draft_revision < 1:
            raise ValueError
    except (TypeError, ValueError):
        fail_task(session, task.id, error="comment reply send task draft_revision is invalid")
        return task
    try:
        result = execute_approved_comment_reply(
            session_factory,
            reply_id=reply_id,
            draft_revision=draft_revision,
            update_token=str(payload.get("update_token") or "") or None,
            card_client=FeishuIMClient(),
            sender=_remote_comment_reply_sender(),
        )
        push_customer_followup(session_factory, reply_id=reply_id)
        with session_factory() as sync_session:
            reply = sync_session.get(LeadCommentReply, reply_id)
            customer_ids = [reply.lead_id] if reply is not None and reply.lead_id is not None else []
        if customer_ids:
            sync_customer_crm(session_factory, customer_ids=customer_ids)
        if result.status in {"approved_to_send", "queued"}:
            fail_task(session, task.id, error="comment reply send task did not claim approved reply")
            return task
        return complete_task(session, task.id)
    except Exception as exc:
        if task.status == TaskStatus.RUNNING.value:
            fail_task(session, task.id, error=str(exc))
        raise


def _remote_comment_reply_sender() -> XiaohongshuCommentReplySender:
    config = XiaohongshuBrowserConfig.from_env()
    if config.browser_mode != "remote_cdp":
        raise ValueError("comment reply send tasks require COMMENT_REPLY_BROWSER_MODE=remote_cdp")
    if not config.cdp_url:
        raise ValueError("comment reply send tasks require COMMENT_REPLY_CDP_URL")
    return XiaohongshuCommentReplySender(config)
