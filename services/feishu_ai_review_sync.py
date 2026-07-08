from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings
from storage.models import Comment, Content, FeishuBitableRecord, LeadScreeningResult, PublicProfile


DEFAULT_CUSTOMER_TABLE_ID = "tblAHiwa7ip0IkxQ"
DEFAULT_EVIDENCE_TABLE_ID = "tblWuVvYREtAPHGs"
ELIGIBLE_REVIEW_STATUSES = {"accepted", "needs_review"}


@dataclass(frozen=True, slots=True)
class FeishuAIReviewSyncResult:
    customers_created: int = 0
    customers_updated: int = 0
    evidence_created: int = 0
    evidence_updated: int = 0
    dry_run: int = 0
    skipped: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "customers_created": self.customers_created,
            "customers_updated": self.customers_updated,
            "evidence_created": self.evidence_created,
            "evidence_updated": self.evidence_updated,
            "dry_run": self.dry_run,
            "skipped": self.skipped,
            "failed": self.failed,
        }


@dataclass(slots=True)
class _SyncCounters:
    customers_created: int = 0
    customers_updated: int = 0
    evidence_created: int = 0
    evidence_updated: int = 0
    dry_run: int = 0
    skipped: int = 0
    failed: int = 0

    def result(self) -> FeishuAIReviewSyncResult:
        return FeishuAIReviewSyncResult(
            customers_created=self.customers_created,
            customers_updated=self.customers_updated,
            evidence_created=self.evidence_created,
            evidence_updated=self.evidence_updated,
            dry_run=self.dry_run,
            skipped=self.skipped,
            failed=self.failed,
        )


@dataclass(frozen=True, slots=True)
class _CustomerGroup:
    local_id: int
    screenings: list[LeadScreeningResult]


def sync_feishu_ai_review_rows(
    session: Session,
    *,
    customer_client: FeishuBitableClient | None = None,
    evidence_client: FeishuBitableClient | None = None,
    limit: int | None = None,
) -> FeishuAIReviewSyncResult:
    customer_client = customer_client or _default_client(DEFAULT_CUSTOMER_TABLE_ID, "FEISHU_AI_REVIEW_CUSTOMER_TABLE_ID")
    evidence_client = evidence_client or _default_client(DEFAULT_EVIDENCE_TABLE_ID, "FEISHU_AI_REVIEW_EVIDENCE_TABLE_ID")
    counters = _SyncCounters()
    eligible = _eligible_screenings(session, limit=limit, counters=counters)
    groups = _group_by_customer(eligible)
    customer_record_ids: dict[int, str] = {}
    customer_evidence_record_ids: dict[int, list[str]] = {}

    for group in groups:
        mapping = _get_or_create_mapping(
            session,
            local_entity_type="ai_review_customer",
            local_entity_id=group.local_id,
            client=customer_client,
        )
        fields = _customer_fields(session, group.screenings)
        had_record = bool(mapping and mapping.record_id)
        try:
            result = customer_client.upsert_record(mapping.record_id if mapping is not None else None, fields)
        except Exception as exc:  # noqa: BLE001 - keep sync failure visible without stopping the batch.
            _record_failure(mapping, exc)
            counters.failed += 1
            continue
        _record_success(mapping, fields, result.record_id, dry_run=result.dry_run)
        if result.dry_run:
            counters.dry_run += 1
        elif had_record:
            counters.customers_updated += 1
        else:
            counters.customers_created += 1
        if result.record_id:
            customer_record_ids[group.local_id] = result.record_id
            customer_evidence_record_ids[group.local_id] = []

    for screening in eligible:
        local_customer_id = _customer_local_id(screening)
        mapping = _get_or_create_mapping(
            session,
            local_entity_type="ai_review_evidence",
            local_entity_id=int(screening.id),
            client=evidence_client,
        )
        fields = _evidence_fields(session, screening, customer_record_id=customer_record_ids.get(local_customer_id))
        had_record = bool(mapping and mapping.record_id)
        try:
            result = evidence_client.upsert_record(mapping.record_id if mapping is not None else None, fields)
        except Exception as exc:  # noqa: BLE001
            _record_failure(mapping, exc)
            counters.failed += 1
            continue
        _record_success(mapping, fields, result.record_id, dry_run=result.dry_run)
        if result.dry_run:
            counters.dry_run += 1
        elif had_record:
            counters.evidence_updated += 1
        else:
            counters.evidence_created += 1
        if result.record_id and local_customer_id in customer_evidence_record_ids:
            customer_evidence_record_ids[local_customer_id].append(result.record_id)

    for group in groups:
        customer_record_id = customer_record_ids.get(group.local_id)
        evidence_record_ids = customer_evidence_record_ids.get(group.local_id) or []
        if not customer_record_id or not evidence_record_ids:
            continue
        mapping = _find_mapping(
            session,
            local_entity_type="ai_review_customer",
            local_entity_id=group.local_id,
            client=customer_client,
        )
        fields = {**_customer_fields(session, group.screenings), "关联证据明细": evidence_record_ids}
        try:
            result = customer_client.upsert_record(customer_record_id, fields)
        except Exception as exc:  # noqa: BLE001
            _record_failure(mapping, exc)
            counters.failed += 1
            continue
        _record_success(mapping, fields, result.record_id or customer_record_id, dry_run=result.dry_run)

    session.flush()
    return counters.result()


def _default_client(default_table_id: str, env_name: str) -> FeishuBitableClient:
    base = FeishuBitableSettings.from_env()
    table_id = os.getenv(env_name) or default_table_id
    return FeishuBitableClient(settings=replace(base, table_id=table_id))


def _eligible_screenings(
    session: Session,
    *,
    limit: int | None,
    counters: _SyncCounters,
) -> list[LeadScreeningResult]:
    rows = session.scalars(select(LeadScreeningResult).order_by(LeadScreeningResult.id.asc())).all()
    eligible: list[LeadScreeningResult] = []
    for screening in rows:
        if screening.review_status not in ELIGIBLE_REVIEW_STATUSES or screening.valuable is False:
            counters.skipped += 1
            continue
        eligible.append(screening)
        if limit is not None and len(eligible) >= limit:
            break
    return eligible


def _group_by_customer(screenings: list[LeadScreeningResult]) -> list[_CustomerGroup]:
    grouped: dict[int, list[LeadScreeningResult]] = {}
    for screening in screenings:
        grouped.setdefault(_customer_local_id(screening), []).append(screening)
    return [_CustomerGroup(local_id=local_id, screenings=items) for local_id, items in grouped.items()]


def _customer_local_id(screening: LeadScreeningResult) -> int:
    return int(screening.public_profile_id or -(screening.id or screening.source_entity_id))


def _customer_fields(session: Session, screenings: list[LeadScreeningResult]) -> dict[str, Any]:
    best = max(screenings, key=_screening_rank)
    profile = _profile(session, best)
    texts = [_raw_text(session, item) for item in screenings]
    all_text = "\n".join(text for text in texts if text)
    return {
        "客户": _customer_name(profile),
        "平台用户ID": _platform_user_id(profile, fallback=f"screening:{best.id}"),
        "意向程度": _intent_label(best),
        "需求摘要": _truncate(_summary_text(best, all_text), 500),
        "课程/考试": _detect_product(all_text),
        "为什么推荐": _recommendation_text(best),
        "下一步": _next_step(best),
        "状态": _review_status_label(best),
        "证据数量": len(screenings),
        "来源链接": _source_url(session, best),
        "抓取时间": _format_datetime(_published_at(session, best) or best.updated_at or best.created_at),
    }


def _evidence_fields(
    session: Session,
    screening: LeadScreeningResult,
    *,
    customer_record_id: str | None,
) -> dict[str, Any]:
    profile = _profile(session, screening)
    fields: dict[str, Any] = {
        "证据标题": f"{_customer_name(profile)}-{screening.source_entity_type}-{screening.source_entity_id}-screening-{screening.id}",
        "平台用户ID": _platform_user_id(profile, fallback=f"screening:{screening.id}"),
        "客户": _customer_name(profile),
        "证据类型": screening.source_entity_type,
        "AI判断": screening.review_status,
        "置信度": screening.confidence or 0,
        "动作": screening.demand_type or "",
        "为什么推荐": _recommendation_text(screening),
        "抓取原文": _truncate(_raw_text(session, screening), 1500),
        "来源链接": _source_url(session, screening),
        "发布时间": _format_datetime(_published_at(session, screening)),
        "内容ID": str(screening.content_id or ""),
        "评论ID": str(screening.comment_id or ""),
    }
    if customer_record_id:
        fields["关联客户线索"] = [customer_record_id]
    return fields


def _screening_rank(screening: LeadScreeningResult) -> tuple[int, int, int]:
    review_rank = {"accepted": 3, "needs_review": 2}.get(screening.review_status, 0)
    intent_rank = {"high": 3, "medium": 2, "low": 1}.get(str(screening.intent_strength or "").lower(), 0)
    return review_rank, intent_rank, screening.confidence or 0


def _profile(session: Session, screening: LeadScreeningResult) -> PublicProfile | None:
    if screening.public_profile_id is None:
        return None
    return session.get(PublicProfile, screening.public_profile_id)


def _content(session: Session, screening: LeadScreeningResult) -> Content | None:
    if screening.content_id is None:
        return None
    return session.get(Content, screening.content_id)


def _comment(session: Session, screening: LeadScreeningResult) -> Comment | None:
    if screening.comment_id is None:
        return None
    return session.get(Comment, screening.comment_id)


def _customer_name(profile: PublicProfile | None) -> str:
    return profile.display_name if profile and profile.display_name else "未知用户"


def _platform_user_id(profile: PublicProfile | None, *, fallback: str) -> str:
    return profile.platform_user_id if profile else fallback


def _intent_label(screening: LeadScreeningResult) -> str:
    return {"high": "高", "medium": "中", "low": "低"}.get(str(screening.intent_strength or "").lower(), "中")


def _review_status_label(screening: LeadScreeningResult) -> str:
    if screening.human_review_status == "valid":
        return "可跟进"
    if screening.human_review_status == "invalid":
        return "已忽略"
    return "待确认"


def _summary_text(screening: LeadScreeningResult, raw_text: str) -> str:
    context = screening.context_json or {}
    reason = screening.status_reason or screening.qualification_human_reason or "DeepSeek 识别为可能客户线索"
    source = raw_text or str(context.get("current_comment") or context.get("post_body") or "")
    return f"{reason}。原文：{source}".strip()


def _recommendation_text(screening: LeadScreeningResult) -> str:
    parts = [
        f"DeepSeek={screening.review_status}",
        f"Campaign={screening.qualification_decision or 'unknown'}",
        screening.status_reason,
        screening.qualification_human_reason,
        _evidence_text(screening),
        _location_text(screening),
    ]
    return "；".join(part for part in parts if part)


def _evidence_text(screening: LeadScreeningResult) -> str:
    values = screening.judgment_evidence_json or []
    return " / ".join(str(item) for item in values if item)


def _location_text(screening: LeadScreeningResult) -> str:
    location = screening.qualification_location_json or {}
    resolved = location.get("resolved_location") if isinstance(location, dict) else {}
    evidence = location.get("evidence") if isinstance(location, dict) else []
    raw_values: list[str] = []
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("raw_text"):
                raw_values.append(str(item["raw_text"]))
    normalized = ""
    if isinstance(resolved, dict):
        normalized = " ".join(str(resolved.get(key) or "") for key in ("province", "city")).strip()
    values = [value for value in ("/".join(raw_values), normalized) if value]
    return f"地区={'; '.join(values)}" if values else ""


def _next_step(screening: LeadScreeningResult) -> str:
    if screening.qualification_decision == "qualified":
        return "人工确认后可跟进"
    if screening.qualification_decision == "needs_review":
        return "先人工核对地区和需求"
    return "人工复核"


def _raw_text(session: Session, screening: LeadScreeningResult) -> str:
    context = screening.context_json or {}
    if screening.source_entity_type == "comment":
        comment = _comment(session, screening)
        return (comment.body_text if comment else None) or str(context.get("current_comment") or "")
    content = _content(session, screening)
    title = content.title if content else context.get("post_title")
    body = content.body_text if content else context.get("post_body")
    return "\n".join(str(part).strip() for part in (title, body) if part and str(part).strip())


def _source_url(session: Session, screening: LeadScreeningResult) -> str:
    context = screening.context_json or {}
    content = _content(session, screening)
    return (content.url if content else None) or str(context.get("source_url") or "")


def _published_at(session: Session, screening: LeadScreeningResult) -> datetime | None:
    comment = _comment(session, screening)
    if comment and comment.published_at:
        return comment.published_at
    content = _content(session, screening)
    return content.published_at if content else None


def _detect_product(text: str) -> str:
    products: list[str] = []
    normalized = text.upper()
    if "KET" in normalized:
        products.append("KET")
    if "PET" in normalized:
        products.append("PET")
    if "小剑桥" in text:
        products.append("小剑桥")
    return "、".join(products)


def _get_or_create_mapping(
    session: Session,
    *,
    local_entity_type: str,
    local_entity_id: int,
    client: FeishuBitableClient,
) -> FeishuBitableRecord | None:
    app_token = client.settings.app_token
    table_id = client.settings.table_id
    if not app_token or not table_id:
        return None
    mapping = _find_mapping(
        session,
        local_entity_type=local_entity_type,
        local_entity_id=local_entity_id,
        client=client,
    )
    if mapping is not None:
        return mapping
    mapping = FeishuBitableRecord(
        local_entity_type=local_entity_type,
        local_entity_id=local_entity_id,
        app_token=app_token,
        table_id=table_id,
        sync_direction="push",
        last_sync_status="pending",
    )
    session.add(mapping)
    session.flush()
    return mapping


def _find_mapping(
    session: Session,
    *,
    local_entity_type: str,
    local_entity_id: int,
    client: FeishuBitableClient,
) -> FeishuBitableRecord | None:
    if not client.settings.app_token or not client.settings.table_id:
        return None
    return session.scalar(
        select(FeishuBitableRecord).where(
            FeishuBitableRecord.local_entity_type == local_entity_type,
            FeishuBitableRecord.local_entity_id == local_entity_id,
            FeishuBitableRecord.app_token == client.settings.app_token,
            FeishuBitableRecord.table_id == client.settings.table_id,
        )
    )


def _record_success(
    mapping: FeishuBitableRecord | None,
    fields: dict[str, Any],
    record_id: str | None,
    *,
    dry_run: bool,
) -> None:
    if mapping is None:
        return
    mapping.record_id = record_id or mapping.record_id
    mapping.remote_fields_json = fields
    mapping.last_synced_at = datetime.now(UTC)
    mapping.last_sync_status = "dry_run" if dry_run else "synced"
    mapping.last_error = None


def _record_failure(mapping: FeishuBitableRecord | None, exc: Exception) -> None:
    if mapping is None:
        return
    mapping.last_sync_status = "failed"
    mapping.last_error = str(exc)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _truncate(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
