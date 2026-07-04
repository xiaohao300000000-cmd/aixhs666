from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.bitable import FeishuBitableClient
from services.agent_runtime import AgentLeadRow
from storage.models import FeishuBitableRecord, Lead


@dataclass(frozen=True)
class FeishuWorkbenchSyncResult:
    created: int = 0
    updated: int = 0
    dry_run: int = 0
    failed: int = 0


STATUS_FROM_FEISHU = {
    "新发现": "new",
    "待确认": "needs_enrichment",
    "可跟进": "qualified",
    "已跟进": "handled",
    "不合适": "ignored",
}


def build_workbench_fields(row: AgentLeadRow) -> dict[str, Any]:
    return {
        "客户": row.customer,
        "需求": row.need,
        "课程/考试": row.product,
        "意向程度": row.intent_level,
        "为什么推荐": row.reason,
        "下一步": row.next_step,
        "状态": row.status_label,
        "来源链接": row.source_url,
        "发现时间": row.discovered_at,
    }


def sync_workbench_rows(
    session: Session,
    client: FeishuBitableClient,
    rows: list[AgentLeadRow],
) -> FeishuWorkbenchSyncResult:
    counts = {"created": 0, "updated": 0, "dry_run": 0, "failed": 0}
    app_token = client.settings.app_token
    table_id = client.settings.table_id
    can_persist_mapping = bool(app_token and table_id)
    now = datetime.now(UTC)
    for row in rows:
        mapping = (
            _get_or_create_mapping(
                session,
                row.lead_id,
                app_token=app_token,
                table_id=table_id,
            )
            if can_persist_mapping
            else None
        )
        fields = build_workbench_fields(row)
        try:
            result = client.upsert_record(mapping.record_id if mapping is not None else None, fields)
        except Exception as exc:
            if mapping is not None:
                mapping.last_sync_status = "failed"
                mapping.last_error = str(exc)
            counts["failed"] += 1
            continue
        if result.dry_run:
            counts["dry_run"] += 1
        elif mapping is not None and mapping.record_id:
            counts["updated"] += 1
        else:
            counts["created"] += 1
        if mapping is not None:
            mapping.record_id = result.record_id or mapping.record_id
            mapping.remote_fields_json = fields
            mapping.last_synced_at = now
            mapping.last_sync_status = "dry_run" if result.dry_run else "synced"
            mapping.last_error = None
    session.flush()
    return FeishuWorkbenchSyncResult(**counts)


def pull_workbench_feedback(session: Session, client: FeishuBitableClient) -> dict[str, int]:
    updated = 0
    skipped = 0
    records = client.list_records()
    app_token = client.settings.app_token or "dry-run-app"
    table_id = client.settings.table_id or "dry-run-table"
    for record in records:
        record_id = str(record.get("record_id") or "")
        fields = record.get("fields") or {}
        status_label = fields.get("状态")
        mapping = session.scalar(
            select(FeishuBitableRecord).where(
                FeishuBitableRecord.app_token == app_token,
                FeishuBitableRecord.table_id == table_id,
                FeishuBitableRecord.record_id == record_id,
            )
        )
        if mapping is None or status_label not in STATUS_FROM_FEISHU:
            skipped += 1
            continue
        lead = session.get(Lead, mapping.local_entity_id)
        if lead is None:
            skipped += 1
            continue
        lead.status = STATUS_FROM_FEISHU[str(status_label)]
        lead.owner_name = fields.get("负责人") or lead.owner_name
        lead.operator_note = fields.get("备注") or lead.operator_note
        lead.last_feedback_at = datetime.now(UTC)
        mapping.remote_fields_json = dict(fields)
        mapping.last_sync_status = "feedback_pulled"
        updated += 1
    session.flush()
    return {"updated": updated, "skipped": skipped}


def _get_or_create_mapping(
    session: Session,
    lead_id: int,
    *,
    app_token: str,
    table_id: str,
) -> FeishuBitableRecord:
    mapping = session.scalar(
        select(FeishuBitableRecord).where(
            FeishuBitableRecord.local_entity_type == "lead",
            FeishuBitableRecord.local_entity_id == lead_id,
            FeishuBitableRecord.app_token == app_token,
            FeishuBitableRecord.table_id == table_id,
        )
    )
    if mapping is not None:
        return mapping
    mapping = FeishuBitableRecord(
        local_entity_type="lead",
        local_entity_id=lead_id,
        app_token=app_token,
        table_id=table_id,
        sync_direction="push",
        last_sync_status="pending",
    )
    session.add(mapping)
    session.flush()
    return mapping
