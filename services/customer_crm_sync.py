from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings
from storage.models import (
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    FeishuBitableRecord,
    Lead,
    LeadEvidence,
    LeadScreeningResult,
    PublicProfile,
)


CUSTOMER_ENTITY_TYPE = "customer_crm"
FOLLOWUP_ENTITY_TYPE = "customer_followup_record"
HUMAN_FIELDS = frozenset({"CRM阶段", "下次跟进时间", "跟进备注", "联系结果", "客户标签"})
CRM_STAGE_LABELS = {
    "new_customer": "新客户",
    "awaiting_first_contact": "待首次联系",
    "contact_approved": "话术已确认",
    "awaiting_send": "等待发送",
    "contact_sent_waiting_reply": "已联系待回复",
    "customer_replied": "客户已回复",
    "in_conversation": "沟通中",
    "high_intent": "有明确意向",
    "converted": "已转化",
    "deferred": "暂缓",
    "temporarily_unreachable": "暂时失联",
    "invalid": "无效",
}
CRM_STAGE_VALUES = {label: value for value, label in CRM_STAGE_LABELS.items()}


@dataclass(frozen=True, slots=True)
class CustomerCrmSyncResult:
    status: str
    customers_synced: int = 0
    followups_synced: int = 0
    skipped: int = 0
    conflicted: int = 0
    reconciliation_unknown: int = 0
    failed: int = 0
    errors: tuple[str, ...] = ()

    @property
    def synced(self) -> int:
        return self.customers_synced + self.followups_synced

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "customers_synced": self.customers_synced,
            "followups_synced": self.followups_synced,
            "synced": self.synced,
            "skipped": self.skipped,
            "conflicted": self.conflicted,
            "reconciliation_unknown": self.reconciliation_unknown,
            "failed": self.failed,
            "errors": list(self.errors),
        }


def sync_customer_crm(
    session_factory: sessionmaker[Session],
    *,
    customer_ids: list[int] | None = None,
    customer_client: FeishuBitableClient | None = None,
    followup_client: FeishuBitableClient | None = None,
    miaoda_base_url: str | None = None,
) -> CustomerCrmSyncResult:
    customer_client = customer_client or FeishuBitableClient(settings=FeishuBitableSettings.from_customer_crm_env())
    followup_client = followup_client or FeishuBitableClient(
        settings=FeishuBitableSettings.from_customer_followup_record_env()
    )
    if not _configured(customer_client) or not _configured(followup_client):
        return CustomerCrmSyncResult(status="skipped", skipped=1)
    with session_factory() as session:
        if customer_ids is None:
            customer_ids = list(
                session.scalars(
                    select(Lead.id)
                    .where(Lead.status == "qualified", Lead.crm_stage.notin_({"candidate", "invalid"}))
                    .order_by(Lead.id)
                ).all()
            )

    customers_synced = 0
    followups_synced = 0
    skipped = 0
    reconciliation_unknown = 0
    failed = 0
    errors: list[str] = []
    for customer_id in customer_ids:
        with session_factory() as session:
            lead = session.get(Lead, customer_id)
            if lead is None or lead.status != "qualified" or lead.crm_stage in {"candidate", "invalid"}:
                skipped += 1
                continue
            profile = session.get(PublicProfile, lead.public_profile_id)
            if profile is None:
                skipped += 1
                continue
            customer_fields = _customer_fields(
                session,
                lead=lead,
                profile=profile,
                transport=customer_client.settings.transport,
                miaoda_base_url=miaoda_base_url,
            )
            outcome, error = _sync_projection(
                session,
                client=customer_client,
                entity_type=CUSTOMER_ENTITY_TYPE,
                entity_id=lead.id,
                key_field="后端客户 ID",
                key_value=str(lead.id),
                fields=customer_fields,
            )
            if outcome == "synced":
                customers_synced += 1
            elif outcome == "reconciliation_unknown":
                reconciliation_unknown += 1
            elif outcome == "skipped":
                skipped += 1
            else:
                failed += 1
                if error:
                    errors.append(f"customer {lead.id}: {error}")

            followups = session.scalars(
                select(CustomerFollowupRecord)
                .where(CustomerFollowupRecord.lead_id == lead.id)
                .order_by(CustomerFollowupRecord.occurred_at, CustomerFollowupRecord.id)
            ).all()
            for followup in followups:
                followup_fields = _followup_fields(
                    followup,
                    customer_id=lead.id,
                    customer_name=profile.display_name,
                    transport=followup_client.settings.transport,
                )
                outcome, error = _sync_projection(
                    session,
                    client=followup_client,
                    entity_type=FOLLOWUP_ENTITY_TYPE,
                    entity_id=followup.id,
                    key_field="跟进记录 ID",
                    key_value=str(followup.id),
                    fields=followup_fields,
                )
                if outcome == "synced":
                    followups_synced += 1
                elif outcome == "reconciliation_unknown":
                    reconciliation_unknown += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    if error:
                        errors.append(f"followup {followup.id}: {error}")

    status = _summary_status(
        succeeded=customers_synced + followups_synced,
        failed=failed,
        reconciliation_unknown=reconciliation_unknown,
    )
    return CustomerCrmSyncResult(
        status=status,
        customers_synced=customers_synced,
        followups_synced=followups_synced,
        skipped=skipped,
        reconciliation_unknown=reconciliation_unknown,
        failed=failed,
        errors=tuple(errors),
    )


def pull_customer_crm_edits(
    session_factory: sessionmaker[Session],
    *,
    client: FeishuBitableClient | None = None,
) -> CustomerCrmSyncResult:
    client = client or FeishuBitableClient(settings=FeishuBitableSettings.from_customer_crm_env())
    if not _configured(client):
        return CustomerCrmSyncResult(status="skipped", skipped=1)
    try:
        records = client.list_records()
    except Exception as exc:  # noqa: BLE001 - remote sync failures never replay business actions.
        return CustomerCrmSyncResult(status="failed", failed=1, errors=(str(exc),))

    synced = 0
    skipped = 0
    conflicted = 0
    failed = 0
    errors: list[str] = []
    with session_factory() as session:
        for index, record in enumerate(records):
            try:
                with session.begin_nested():
                    fields = record.get("fields")
                    if not isinstance(fields, dict):
                        raise ValueError("record fields must be an object")
                    customer_id = _int_value(fields.get("后端客户 ID"))
                    lead = session.get(Lead, customer_id) if customer_id is not None else None
                    if lead is None:
                        skipped += 1
                        continue
                    mapping = _get_or_create_mapping(session, client, CUSTOMER_ENTITY_TYPE, lead.id)
                    record_id = _text(record.get("record_id"))
                    if mapping.record_id and record_id and mapping.record_id != record_id:
                        conflicted += 1
                        continue
                    remote_version = _int_value(fields.get("同步版本"))
                    remote_updated_at = _remote_updated_at(record)
                    if remote_updated_at is None and client.settings.transport == "lark_cli" and record_id:
                        remote_updated_at = _parse_datetime(client.get_record_updated_time(record_id))
                    if remote_version != lead.crm_sync_version or remote_updated_at is None:
                        conflicted += 1
                        continue
                    if mapping.last_synced_at and remote_updated_at <= _aware_utc(mapping.last_synced_at):
                        conflicted += 1
                        continue
                    if mapping.last_remote_updated_at and remote_updated_at <= _aware_utc(mapping.last_remote_updated_at):
                        skipped += 1
                        continue

                    changed = _apply_human_fields(
                        session,
                        lead=lead,
                        fields={name: fields[name] for name in HUMAN_FIELDS if name in fields},
                        record_id=record_id or f"customer-{lead.id}",
                        remote_updated_at=remote_updated_at,
                    )
                    if not changed:
                        skipped += 1
                        continue
                    lead.crm_sync_version += 1
                    lead.last_feedback_at = datetime.now(UTC)
                    lead.updated_at = datetime.now(UTC)
                    mapping.record_id = record_id or mapping.record_id
                    mapping.sync_direction = "bidirectional"
                    mapping.last_remote_updated_at = remote_updated_at
                    mapping.last_sync_status = "pending"
                    mapping.last_error = None
                    merged = dict(mapping.remote_fields_json or {})
                    merged.update({name: fields.get(name) for name in HUMAN_FIELDS if name in fields})
                    mapping.remote_fields_json = merged
                    synced += 1
            except Exception as exc:  # noqa: BLE001 - one malformed row must not block later rows.
                failed += 1
                errors.append(f"record {index}: {exc}")
        session.commit()

    status = "partial" if failed and synced else "failed" if failed else "conflict" if conflicted and not synced else "synced"
    return CustomerCrmSyncResult(
        status=status,
        customers_synced=synced,
        skipped=skipped,
        conflicted=conflicted,
        failed=failed,
        errors=tuple(errors),
    )


def customer_base_record_url(app_token: str, table_id: str, record_id: str) -> str:
    return f"https://my.feishu.cn/base/{app_token}?table={table_id}&record={record_id}"


def miaoda_customer_url(customer_id: int, *, base_url: str | None = None) -> str:
    root = (base_url or os.getenv("MIAODA_CUSTOMER_BASE_URL") or "").strip().rstrip("/")
    return f"{root}/customers/{customer_id}" if root else f"/customers/{customer_id}"


def _customer_fields(
    session: Session,
    *,
    lead: Lead,
    profile: PublicProfile,
    transport: str,
    miaoda_base_url: str | None,
) -> dict[str, Any]:
    screening = session.scalar(
        select(LeadScreeningResult)
        .where(LeadScreeningResult.public_profile_id == lead.public_profile_id)
        .order_by(LeadScreeningResult.updated_at.desc(), LeadScreeningResult.id.desc())
        .limit(1)
    )
    evidence = session.scalars(
        select(LeadEvidence).where(LeadEvidence.lead_id == lead.id).order_by(LeadEvidence.id).limit(3)
    ).all()
    now = datetime.now(UTC)
    return {
        "后端客户 ID": str(lead.id),
        "客户": profile.display_name or f"客户 #{lead.id}",
        "平台用户 ID": profile.platform_user_id,
        "主页链接": profile.profile_url or "",
        "地区": lead.region_text or profile.region_text or "",
        "需求摘要": evidence[0].evidence_text if evidence else lead.demand_type or "",
        "课程/考试": lead.product or lead.demand_type or "",
        "意向程度": _intent_label(lead.intent_stage, lead.intent_score),
        "CRM阶段": CRM_STAGE_LABELS.get(lead.crm_stage, lead.crm_stage),
        "下一步": lead.recommended_next_step or "",
        "下次跟进时间": _format_datetime(lead.next_followup_at, transport=transport),
        "最近联系时间": _format_datetime(lead.last_contact_at, transport=transport),
        "联系结果": lead.last_contact_result or "",
        "跟进备注": lead.operator_note or "",
        "客户标签": list(lead.customer_tags_json or []),
        "来源 Campaign": screening.qualification_policy_version if screening else "",
        "关联线索": str(lead.id),
        "关联证据": "\n".join(item.evidence_text for item in evidence),
        "AI判断": screening.review_status if screening else "",
        "来源链接": profile.profile_url or "",
        "妙搭详情链接": miaoda_customer_url(lead.id, base_url=miaoda_base_url),
        "同步版本": lead.crm_sync_version,
        "同步状态": "后端已同步",
        "最近同步时间": _format_datetime(now, transport=transport),
    }


def _followup_fields(
    followup: CustomerFollowupRecord,
    *,
    customer_id: int,
    customer_name: str | None,
    transport: str,
) -> dict[str, Any]:
    return {
        "跟进记录 ID": str(followup.id),
        "后端客户 ID": str(customer_id),
        "关联客户": customer_name or f"客户 #{customer_id}",
        "发生时间": _format_datetime(followup.occurred_at, transport=transport),
        "操作类型": followup.action_type,
        "联系渠道": followup.channel or "",
        "联系目标": followup.target or "",
        "内容": followup.content or "",
        "客户回复": followup.customer_reply or "",
        "本次结果": followup.result or "",
        "下一步": followup.next_step or "",
        "下次跟进时间": _format_datetime(followup.next_followup_at, transport=transport),
        "来源入口": followup.source_entry or "",
        "平台发送证据": _evidence_text(followup.platform_evidence_json),
        "是否完成": followup.is_completed,
    }


def _sync_projection(
    session: Session,
    *,
    client: FeishuBitableClient,
    entity_type: str,
    entity_id: int,
    key_field: str,
    key_value: str,
    fields: dict[str, Any],
) -> tuple[str, str | None]:
    mapping = _get_or_create_mapping(session, client, entity_type, entity_id)
    search_only = False
    if mapping.record_id is None:
        if mapping.last_sync_status in {"creating", "reconciling", "reconciliation_unknown"}:
            mapping.last_sync_status = "reconciling"
            search_only = True
        else:
            mapping.last_sync_status = "creating"
            mapping.last_error = None
        session.commit()
    try:
        if mapping.record_id is None:
            matches = client.find_records_by_exact_field(key_field, key_value)
            if len(matches) > 1:
                raise ValueError(f"duplicate remote key for {entity_type}:{entity_id}")
            if matches:
                record_id = _text(matches[0].get("record_id"))
                if not record_id:
                    raise ValueError(f"remote record missing record_id for {entity_type}:{entity_id}")
                mapping.record_id = record_id
            elif search_only:
                mapping.last_sync_status = "reconciliation_unknown"
                mapping.last_error = "remote create result remains unknown; operator reconciliation required"
                session.commit()
                return "reconciliation_unknown", mapping.last_error
        result = client.upsert_record(mapping.record_id, fields)
    except Exception as exc:  # noqa: BLE001 - every projection failure is persisted and isolated.
        mapping.last_sync_status = "reconciliation_unknown" if mapping.record_id is None and _ambiguous(exc) else "failed"
        mapping.last_error = str(exc)
        session.commit()
        return mapping.last_sync_status, str(exc)
    if mapping.record_id is None and result.record_id is None and not result.dry_run:
        mapping.last_sync_status = "reconciliation_unknown"
        mapping.last_error = "remote create returned no record_id; operator reconciliation required"
        session.commit()
        return "reconciliation_unknown", mapping.last_error
    mapping.record_id = result.record_id or mapping.record_id
    mapping.sync_direction = "bidirectional" if entity_type == CUSTOMER_ENTITY_TYPE else "push"
    mapping.remote_fields_json = fields
    mapping.last_synced_at = datetime.now(UTC)
    mapping.last_sync_status = "dry_run" if result.dry_run else "synced"
    mapping.last_error = None
    session.commit()
    return "synced", None


def _get_or_create_mapping(
    session: Session,
    client: FeishuBitableClient,
    entity_type: str,
    entity_id: int,
) -> FeishuBitableRecord:
    app_token = client.settings.app_token
    table_id = client.settings.table_id
    assert app_token is not None and table_id is not None
    query = select(FeishuBitableRecord).where(
        FeishuBitableRecord.local_entity_type == entity_type,
        FeishuBitableRecord.local_entity_id == entity_id,
        FeishuBitableRecord.app_token == app_token,
        FeishuBitableRecord.table_id == table_id,
    )
    mapping = session.scalar(query)
    if mapping is not None:
        return mapping
    mapping = FeishuBitableRecord(
        local_entity_type=entity_type,
        local_entity_id=entity_id,
        app_token=app_token,
        table_id=table_id,
        sync_direction="bidirectional" if entity_type == CUSTOMER_ENTITY_TYPE else "push",
        last_sync_status="pending",
    )
    try:
        with session.begin_nested():
            session.add(mapping)
            session.flush()
        return mapping
    except IntegrityError:
        session.expire_all()
        winner = session.scalar(query)
        if winner is None:
            raise
        return winner


def _apply_human_fields(
    session: Session,
    *,
    lead: Lead,
    fields: dict[str, Any],
    record_id: str,
    remote_updated_at: datetime,
) -> bool:
    changed = False
    if "CRM阶段" in fields:
        stage_label = _text(fields["CRM阶段"])
        new_stage = CRM_STAGE_VALUES.get(stage_label, stage_label if stage_label in CRM_STAGE_LABELS else None)
        if new_stage is None:
            raise ValueError(f"unsupported CRM stage: {stage_label}")
        if new_stage != lead.crm_stage:
            event_key = f"base-crm-stage:{record_id}:{int(remote_updated_at.timestamp() * 1000)}"
            event = session.scalar(select(CustomerTimelineEvent).where(CustomerTimelineEvent.event_key == event_key))
            if event is None:
                old_stage = lead.crm_stage
                session.add(
                    CustomerTimelineEvent(
                        lead_id=lead.id,
                        event_key=event_key,
                        event_type="base_crm_stage_changed",
                        actor_id="feishu_base",
                        data_json={"old_stage": old_stage, "new_stage": new_stage, "source": "feishu_base"},
                        occurred_at=remote_updated_at,
                    )
                )
                session.add(
                    CustomerFollowupRecord(
                        lead_id=lead.id,
                        event_key=f"customer-followup:{event_key}",
                        occurred_at=remote_updated_at,
                        action_type="人工更新 CRM 阶段",
                        result=new_stage,
                        next_step=lead.recommended_next_step,
                        source_entry="feishu_base",
                        is_completed=True,
                    )
                )
            lead.crm_stage = new_stage
            changed = True
    if "下次跟进时间" in fields:
        value = _parse_datetime(fields["下次跟进时间"])
        if value != _optional_aware_utc(lead.next_followup_at):
            lead.next_followup_at = value
            changed = True
    if "跟进备注" in fields:
        value = _text(fields["跟进备注"]) or None
        if value != lead.operator_note:
            lead.operator_note = value
            changed = True
    if "联系结果" in fields:
        value = _text(fields["联系结果"]) or None
        if value != lead.last_contact_result:
            lead.last_contact_result = value
            lead.last_contact_at = remote_updated_at
            changed = True
    if "客户标签" in fields:
        value = _string_list(fields["客户标签"])
        if value != list(lead.customer_tags_json or []):
            lead.customer_tags_json = value
            changed = True
    return changed


def _configured(client: FeishuBitableClient) -> bool:
    return bool(client.settings.app_token and client.settings.table_id)


def _summary_status(*, succeeded: int, failed: int, reconciliation_unknown: int) -> str:
    if (failed or reconciliation_unknown) and succeeded:
        return "partial"
    if failed:
        return "failed"
    if reconciliation_unknown:
        return "reconciliation_unknown"
    return "synced"


def _ambiguous(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, (httpx.TimeoutException, httpx.TransportError, subprocess.TimeoutExpired)):
            return True
        current = current.__cause__
    return False


def _remote_updated_at(record: dict[str, Any]) -> datetime | None:
    for name in ("updated_time", "last_modified_time", "record_updated_time"):
        if name in record:
            return _parse_datetime(record[name])
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.lstrip("-").isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(os.getenv("FEISHU_CUSTOMER_CRM_TIMEZONE", "Asia/Shanghai")))
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime | None, *, transport: str) -> int | str | None:
    if value is None:
        return None
    aware = _aware_utc(value)
    if transport == "lark_cli":
        timezone = ZoneInfo(os.getenv("FEISHU_CUSTOMER_CRM_TIMEZONE", "Asia/Shanghai"))
        return aware.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
    return int(aware.timestamp() * 1000)


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _optional_aware_utc(value: datetime | None) -> datetime | None:
    return _aware_utc(value) if value is not None else None


def _int_value(value: Any) -> int | None:
    text = _text(value)
    try:
        return int(text) if text else None
    except ValueError:
        return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for item in value if (text := _text(item).strip())]
    text = _text(value).strip()
    return [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]


def _evidence_text(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    return "; ".join(f"{key}={item}" for key, item in sorted(value.items()))


def _intent_label(intent_stage: str | None, intent_score: int) -> str:
    normalized = (intent_stage or "").strip().casefold()
    if normalized in {"高", "high"} or intent_score >= 80:
        return "高"
    if normalized in {"中", "medium"} or intent_score >= 50:
        return "中"
    return "低"


def _text(value: Any) -> str:
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("value") or "")
    return "" if value is None else str(value)
