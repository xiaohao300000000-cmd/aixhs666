from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings
from storage.models import FeishuBitableRecord, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


SYSTEM_FIELDS = frozenset(
    {
        "客户唯一键",
        "评论审批状态",
        "评论发送结果",
        "最近评论时间",
        "最近评论错误",
        "评论回复记录 ID",
        "审批卡片消息 ID",
    }
)
HUMAN_FIELDS = frozenset({"当前客户状态", "负责人", "运营备注", "下次跟进时间"})
TERMINAL_HUMAN_STATUSES = frozenset({"已收到私信", "沟通中", "已成交", "已忽略"})


@dataclass(frozen=True, slots=True)
class CustomerFollowupSyncResult:
    status: str
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "status": self.status,
            "synced": self.synced,
            "skipped": self.skipped,
            "failed": self.failed,
            "error": self.error,
        }


def push_customer_followup(
    session_factory: sessionmaker[Session],
    *,
    reply_id: int,
    client: FeishuBitableClient | None = None,
) -> CustomerFollowupSyncResult:
    client = client or FeishuBitableClient(settings=FeishuBitableSettings.from_customer_followup_env())
    if client.settings.app_token is None or client.settings.table_id is None:
        return CustomerFollowupSyncResult(status="skipped", skipped=1)
    with session_factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        if reply is None or reply.lead_id is None:
            return CustomerFollowupSyncResult(status="skipped", skipped=1)
        lead = session.get(Lead, reply.lead_id)
        if lead is None:
            return CustomerFollowupSyncResult(status="skipped", skipped=1)
        profile = session.get(PublicProfile, lead.public_profile_id)
        if profile is None or not profile.platform_user_id:
            return CustomerFollowupSyncResult(status="skipped", skipped=1)
        mapping = _get_or_create_mapping(session, lead.id, client)
        fields = _push_fields(session, lead=lead, reply=reply, profile=profile)
        try:
            result = client.upsert_record(mapping.record_id, fields)
        except Exception as exc:  # noqa: BLE001 - sync failure is persisted and isolated from sending.
            _record_failure(mapping, exc)
            session.commit()
            return CustomerFollowupSyncResult(status="failed", failed=1, error=str(exc))
        _record_success(mapping, fields, result.record_id, dry_run=result.dry_run)
        session.commit()
        return CustomerFollowupSyncResult(status="synced", synced=1)


def pull_customer_followup_edits(
    session_factory: sessionmaker[Session],
    *,
    client: FeishuBitableClient | None = None,
) -> CustomerFollowupSyncResult:
    client = client or FeishuBitableClient(settings=FeishuBitableSettings.from_customer_followup_env())
    if client.settings.app_token is None or client.settings.table_id is None:
        return CustomerFollowupSyncResult(status="skipped", skipped=1)
    try:
        records = client.list_records()
    except Exception as exc:  # noqa: BLE001 - pull failures must not affect outreach state.
        return CustomerFollowupSyncResult(status="failed", failed=1, error=str(exc))
    synced = 0
    skipped = 0
    with session_factory() as session:
        for record in records:
            fields = record.get("fields")
            if not isinstance(fields, dict):
                skipped += 1
                continue
            customer_key = _text(fields.get("客户唯一键"))
            lead = _lead_by_customer_key(session, customer_key)
            if lead is None:
                skipped += 1
                continue
            _apply_human_fields(lead, fields)
            mapping = _get_or_create_mapping(session, lead.id, client)
            record_id = _text(record.get("record_id"))
            if record_id:
                mapping.record_id = record_id
            mapping.sync_direction = "bidirectional"
            mapping.last_remote_updated_at = datetime.now(UTC)
            mapping.last_sync_status = "synced"
            mapping.last_error = None
            mapping.remote_fields_json = {name: fields.get(name) for name in HUMAN_FIELDS if name in fields}
            synced += 1
        session.commit()
    return CustomerFollowupSyncResult(status="synced", synced=synced, skipped=skipped)


def _push_fields(
    session: Session,
    *,
    lead: Lead,
    reply: LeadCommentReply,
    profile: PublicProfile,
) -> dict[str, Any]:
    screening = session.get(LeadScreeningResult, reply.screening_result_id) if reply.screening_result_id else None
    automatic_status = "已评论引导，等待客户私信" if reply.status == "sent" else "待评论引导"
    current_status = lead.followup_status if lead.followup_status in TERMINAL_HUMAN_STATUSES else automatic_status
    return {
        "客户唯一键": f"{lead.platform}:{profile.platform_user_id}",
        "当前客户状态": current_status,
        "负责人": lead.owner_name or "",
        "运营备注": lead.operator_note or "",
        "下次跟进时间": _format_datetime(lead.next_followup_at),
        "评论审批状态": _approval_status(reply.status),
        "评论发送结果": _send_status(reply.status),
        "最近评论时间": _format_datetime(reply.sent_at or reply.last_attempt_at),
        "最近评论错误": reply.last_error or reply.feishu_sync_error or "",
        "评论回复记录 ID": str(reply.id),
        "审批卡片消息 ID": reply.feishu_message_id or "",
        "需求类型": screening.demand_type if screening else "",
        "客户昵称": profile.display_name or "",
    }


def _apply_human_fields(lead: Lead, fields: dict[str, Any]) -> None:
    if "当前客户状态" in fields:
        lead.followup_status = _text(fields.get("当前客户状态")) or None
    if "负责人" in fields:
        lead.owner_name = _text(fields.get("负责人")) or None
    if "运营备注" in fields:
        lead.operator_note = _text(fields.get("运营备注")) or None
    if "下次跟进时间" in fields:
        lead.next_followup_at = _parse_datetime(fields.get("下次跟进时间"))
    lead.last_feedback_at = datetime.now(UTC)


def _lead_by_customer_key(session: Session, customer_key: str) -> Lead | None:
    platform, separator, platform_user_id = customer_key.partition(":")
    if not separator or not platform_user_id:
        return None
    return session.scalar(
        select(Lead)
        .join(PublicProfile, PublicProfile.id == Lead.public_profile_id)
        .where(Lead.platform == platform, PublicProfile.platform_user_id == platform_user_id)
    )


def _get_or_create_mapping(session: Session, lead_id: int, client: FeishuBitableClient) -> FeishuBitableRecord:
    app_token = client.settings.app_token
    table_id = client.settings.table_id
    assert app_token is not None and table_id is not None
    mapping = session.scalar(
        select(FeishuBitableRecord).where(
            FeishuBitableRecord.local_entity_type == "customer_followup",
            FeishuBitableRecord.local_entity_id == lead_id,
            FeishuBitableRecord.app_token == app_token,
            FeishuBitableRecord.table_id == table_id,
        )
    )
    if mapping is not None:
        return mapping
    mapping = FeishuBitableRecord(
        local_entity_type="customer_followup",
        local_entity_id=lead_id,
        app_token=app_token,
        table_id=table_id,
        sync_direction="bidirectional",
        last_sync_status="pending",
    )
    session.add(mapping)
    session.flush()
    return mapping


def _record_success(mapping: FeishuBitableRecord, fields: dict[str, Any], record_id: str | None, *, dry_run: bool) -> None:
    mapping.record_id = record_id or mapping.record_id
    mapping.remote_fields_json = fields
    mapping.last_synced_at = datetime.now(UTC)
    mapping.last_sync_status = "dry_run" if dry_run else "synced"
    mapping.last_error = None


def _record_failure(mapping: FeishuBitableRecord, exc: Exception) -> None:
    mapping.last_sync_status = "failed"
    mapping.last_error = str(exc)


def _approval_status(status: str) -> str:
    return {
        "pending_review": "待审批",
        "approved_to_send": "已审批",
        "rejected": "已拒绝",
        "sent": "已审批",
    }.get(status, status)


def _send_status(status: str) -> str:
    if status == "sent":
        return "评论成功"
    if status in {"send_failed", "failed"}:
        return "评论失败"
    return "未发送"


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("value") or "")
    return "" if value is None else str(value)
