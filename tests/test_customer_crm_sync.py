from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.bitable import FeishuBitableSettings, FeishuBitableWriteResult
from services.customer_crm_sync import pull_customer_crm_edits, sync_customer_crm
from storage.database import Base
from storage.models import (
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    FeishuBitableRecord,
    Lead,
    LeadEvidence,
    LeadScreeningResult,
    PublicProfile,
)


class FakeBitableClient:
    def __init__(self, *, table_id: str) -> None:
        self.settings = FeishuBitableSettings(
            enabled=True,
            app_id="app-id",
            app_secret="app-secret",
            app_token="crm-base",
            table_id=table_id,
        )
        self.upserts: list[tuple[str | None, dict[str, object]]] = []
        self.remote_records: list[dict[str, object]] = []
        self.matches: dict[str, list[dict[str, object]]] = {}
        self.fail_customer_ids: set[str] = set()
        self.ambiguous_once = False

    def upsert_record(self, record_id: str | None, fields: dict[str, object]) -> FeishuBitableWriteResult:
        customer_id = str(fields.get("后端客户 ID") or "")
        if customer_id in self.fail_customer_ids:
            raise RuntimeError("isolated remote failure")
        if self.ambiguous_once and record_id is None:
            self.ambiguous_once = False
            request = httpx.Request("POST", "https://open.feishu.cn/records")
            raise httpx.ReadTimeout("result unknown", request=request)
        self.upserts.append((record_id, fields))
        generated = record_id or f"rec-{self.settings.table_id}-{len(self.upserts)}"
        return FeishuBitableWriteResult(record_id=generated, dry_run=False, payload={"fields": fields})

    def find_records_by_exact_field(self, field_name: str, value: str) -> list[dict[str, object]]:
        return self.matches.get(f"{field_name}:{value}", [])

    def list_records(self) -> list[dict[str, object]]:
        return self.remote_records


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_customer(factory: sessionmaker[Session], *, suffix: str = "1") -> tuple[int, int]:
    with factory() as session:
        profile = PublicProfile(
            platform="xhs",
            platform_user_id=f"crm-user-{suffix}",
            display_name=f"PET 家长 {suffix}",
            profile_url=f"https://www.xiaohongshu.com/user/profile/{suffix}",
            region_text="福州",
        )
        session.add(profile)
        session.flush()
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="qualified",
            demand_type="PET备考",
            product="PET",
            intent_stage="high",
            intent_score=90,
            recommended_next_step="准备首次公开回复",
            crm_stage="awaiting_first_contact",
            crm_sync_version=1,
        )
        session.add(lead)
        session.flush()
        session.add_all(
            [
                LeadEvidence(
                    lead_id=lead.id,
                    source_entity_type="comment",
                    source_entity_id=100 + int(suffix),
                    evidence_text="孩子正在准备 PET，想找合适课程",
                    demand_type="PET备考",
                    intent_stage="high",
                    score_contribution=90,
                ),
                LeadScreeningResult(
                    platform="xhs",
                    source_entity_type="comment",
                    source_entity_id=200 + int(suffix),
                    public_profile_id=profile.id,
                    demand_type="PET备考",
                    intent_strength="high",
                    confidence=90,
                    qualification_policy_version="education_fuzhou_offline:v1",
                ),
            ]
        )
        followup = CustomerFollowupRecord(
            lead_id=lead.id,
            event_key=f"followup-{suffix}",
            occurred_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
            action_type="待首次联系",
            channel="xhs_public_reply",
            target=f"comment-{suffix}",
            content="准备首次公开回复",
            result="pending",
            next_step="准备首次公开回复",
            source_entry="customer_progression",
            is_completed=False,
        )
        session.add(followup)
        session.commit()
        return lead.id, followup.id


def test_sync_projects_one_customer_and_one_row_per_followup_idempotently() -> None:
    factory = _factory()
    lead_id, followup_id = _seed_customer(factory)
    customer_client = FakeBitableClient(table_id="customer-table")
    followup_client = FakeBitableClient(table_id="followup-table")

    first = sync_customer_crm(
        factory,
        customer_ids=[lead_id],
        customer_client=customer_client,
        followup_client=followup_client,
        miaoda_base_url="https://miaoda.example/app",
    )
    second = sync_customer_crm(
        factory,
        customer_ids=[lead_id],
        customer_client=customer_client,
        followup_client=followup_client,
        miaoda_base_url="https://miaoda.example/app",
    )

    assert first.status == second.status == "synced"
    assert first.customers_synced == first.followups_synced == 1
    assert customer_client.upserts[0][0] is None
    assert customer_client.upserts[1][0] == "rec-customer-table-1"
    assert followup_client.upserts[0][0] is None
    assert followup_client.upserts[1][0] == "rec-followup-table-1"
    customer_fields = customer_client.upserts[0][1]
    assert customer_fields["后端客户 ID"] == str(lead_id)
    assert customer_fields["CRM阶段"] == "待首次联系"
    assert customer_fields["同步版本"] == 1
    assert customer_fields["妙搭详情链接"] == f"https://miaoda.example/app/customers/{lead_id}"
    assert customer_fields["客户"] == "PET 家长 1"
    assert customer_fields["意向程度"] == "高"
    assert customer_fields["课程/考试"] == "PET"
    assert customer_fields["下一步"] == "准备首次公开回复"
    assert customer_fields["下次跟进时间"] is None
    assert customer_fields["最近联系时间"] is None
    assert "客户名称" not in customer_fields
    assert "课程或考试" not in customer_fields
    assert "当前下一步" not in customer_fields
    assert followup_client.upserts[0][1]["跟进记录 ID"] == str(followup_id)
    assert followup_client.upserts[0][1]["下次跟进时间"] is None
    with factory() as session:
        mappings = session.scalars(select(FeishuBitableRecord)).all()
        assert {(item.local_entity_type, item.local_entity_id) for item in mappings} == {
            ("customer_crm", lead_id),
            ("customer_followup_record", followup_id),
        }


def test_sync_isolates_one_customer_failure() -> None:
    factory = _factory()
    first_id, _ = _seed_customer(factory, suffix="1")
    second_id, _ = _seed_customer(factory, suffix="2")
    customer_client = FakeBitableClient(table_id="customer-table")
    customer_client.fail_customer_ids.add(str(first_id))
    followup_client = FakeBitableClient(table_id="followup-table")

    result = sync_customer_crm(
        factory,
        customer_ids=[first_id, second_id],
        customer_client=customer_client,
        followup_client=followup_client,
    )

    assert result.status == "partial"
    assert result.failed == 1
    assert result.customers_synced == 1
    assert any(fields["后端客户 ID"] == str(second_id) for _, fields in customer_client.upserts)


def test_unknown_create_enters_reconciliation_and_never_blindly_recreates() -> None:
    factory = _factory()
    lead_id, _ = _seed_customer(factory)
    customer_client = FakeBitableClient(table_id="customer-table")
    customer_client.ambiguous_once = True
    followup_client = FakeBitableClient(table_id="followup-table")

    first = sync_customer_crm(
        factory,
        customer_ids=[lead_id],
        customer_client=customer_client,
        followup_client=followup_client,
    )
    second = sync_customer_crm(
        factory,
        customer_ids=[lead_id],
        customer_client=customer_client,
        followup_client=followup_client,
    )

    assert first.reconciliation_unknown == 1
    assert second.reconciliation_unknown == 1
    assert customer_client.upserts == []
    with factory() as session:
        mapping = session.scalar(
            select(FeishuBitableRecord).where(FeishuBitableRecord.local_entity_type == "customer_crm")
        )
        assert mapping is not None
        assert mapping.record_id is None
        assert mapping.last_sync_status == "reconciliation_unknown"


def test_pull_accepts_only_whitelisted_fields_and_creates_stage_audit_once() -> None:
    factory = _factory()
    lead_id, _ = _seed_customer(factory)
    customer_client = FakeBitableClient(table_id="customer-table")
    followup_client = FakeBitableClient(table_id="followup-table")
    sync_customer_crm(
        factory,
        customer_ids=[lead_id],
        customer_client=customer_client,
        followup_client=followup_client,
    )
    updated_at = datetime.now(UTC) + timedelta(minutes=1)
    customer_client.remote_records = [
        {
            "record_id": "rec-customer-table-1",
            "updated_time": int(updated_at.timestamp() * 1000),
            "fields": {
                "后端客户 ID": str(lead_id),
                "同步版本": 1,
                "CRM阶段": "已联系等待回复",
                "下次跟进时间": "2026-07-20 10:00:00",
                "跟进备注": "周一再联系",
                "联系结果": "已公开回复",
                "客户标签": ["PET", "高意向"],
                "客户名称": "恶意覆盖名称",
                "AI判断": "恶意覆盖系统事实",
            },
        }
    ]

    first = pull_customer_crm_edits(factory, client=customer_client)
    second = pull_customer_crm_edits(factory, client=customer_client)

    assert first.synced == 1
    assert second.synced == 0
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        assert lead.crm_stage == "contacted_waiting_reply"
        assert lead.next_followup_at is not None
        assert lead.operator_note == "周一再联系"
        assert lead.last_contact_result == "已公开回复"
        assert lead.customer_tags_json == ["PET", "高意向"]
        assert lead.crm_sync_version == 2
        assert lead.profile.display_name == "PET 家长 1"
        stage_events = session.scalars(
            select(CustomerTimelineEvent).where(CustomerTimelineEvent.event_type == "base_crm_stage_changed")
        ).all()
        stage_followups = session.scalars(
            select(CustomerFollowupRecord).where(CustomerFollowupRecord.action_type == "人工更新 CRM 阶段")
        ).all()
        assert len(stage_events) == len(stage_followups) == 1


def test_pull_rejects_remote_sync_version_that_does_not_match_backend() -> None:
    factory = _factory()
    lead_id, _ = _seed_customer(factory)
    client = FakeBitableClient(table_id="customer-table")
    client.remote_records = [
        {
            "record_id": "rec-customer-table-1",
            "updated_time": int(datetime.now(UTC).timestamp() * 1000),
            "fields": {
                "后端客户 ID": str(lead_id),
                "同步版本": 99,
                "CRM阶段": "已成交",
            },
        }
    ]

    result = pull_customer_crm_edits(factory, client=client)

    assert result.conflicted == 1
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        assert lead.crm_stage == "awaiting_first_contact"
        assert lead.crm_sync_version == 1
