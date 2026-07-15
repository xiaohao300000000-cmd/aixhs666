from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings
from storage.models import FeishuBitableRecord, SkillRun


def skill_run_history_fields(run: SkillRun) -> dict[str, Any]:
    result = run.result_summary_json or {}
    return {"任务运行ID": str(run.id), "任务": "历史线索智能筛选", "状态": run.status, "当前阶段": run.current_stage or "", "进度": run.progress_percent, "处理数量": result.get("processed_count", 0), "有效需求": result.get("valid_demands", 0), "高意向客户": result.get("high_intent_customers", 0), "待确认数量": result.get("needs_confirmation", 0), "Campaign": (run.parameters_json or {}).get("campaign_id", ""), "请求人": run.requested_by or "", "错误": run.error_message or ""}


def sync_skill_run_history(session: Session, run: SkillRun, *, client: FeishuBitableClient | None = None) -> bool:
    table_id = (os.getenv("FEISHU_SKILL_RUN_TABLE_ID") or "").strip()
    if client is None and not table_id:
        return False
    if client is None:
        settings = FeishuBitableSettings.from_env()
        client = FeishuBitableClient(settings=replace(settings, table_id=table_id))
    app_token = client.settings.app_token or "unconfigured"
    actual_table = client.settings.table_id or table_id or "unconfigured"
    mapping = session.scalar(select(FeishuBitableRecord).where(FeishuBitableRecord.local_entity_type == "skill_run", FeishuBitableRecord.local_entity_id == run.id, FeishuBitableRecord.app_token == app_token, FeishuBitableRecord.table_id == actual_table))
    if mapping is None:
        mapping = FeishuBitableRecord(local_entity_type="skill_run", local_entity_id=run.id, app_token=app_token, table_id=actual_table)
        session.add(mapping)
    fields = skill_run_history_fields(run)
    try:
        result = client.upsert_record(mapping.record_id, fields)
        mapping.record_id = result.record_id or mapping.record_id
        mapping.last_sync_status = "dry_run" if result.dry_run else "synced"
        mapping.last_error = None; mapping.remote_fields_json = fields; mapping.last_synced_at = datetime.now(UTC)
        run.feishu_sync_error = None
        return True
    except Exception as exc:
        mapping.last_sync_status = "failed"; mapping.last_error = str(exc); run.feishu_sync_error = str(exc)
        return False
