from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from services.operator_customers import (
    get_operator_customer,
    get_operator_customer_timeline,
    list_operator_customers,
)
from storage.database import Base
from storage.models import (
    CustomerFollowupRecord,
    CustomerTimelineEvent,
    FeishuBitableRecord,
    Lead,
    PublicProfile,
)


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(session: Session) -> Lead:
    profile = PublicProfile(
        platform="xhs",
        platform_user_id="operator-customer",
        display_name="PET 家长",
        profile_url="https://www.xiaohongshu.com/user/profile/operator-customer",
    )
    session.add(profile)
    session.flush()
    lead = Lead(
        platform="xhs",
        public_profile_id=profile.id,
        status="qualified",
        crm_stage="awaiting_first_contact",
        crm_sync_version=3,
        recommended_next_step="准备首次公开回复",
    )
    session.add(lead)
    session.flush()
    session.add_all(
        [
            CustomerTimelineEvent(
                lead_id=lead.id,
                event_key="operator-timeline-1",
                event_type="candidate_promoted",
                data_json={"customer_stage": "awaiting_first_contact"},
                occurred_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
            ),
            CustomerFollowupRecord(
                lead_id=lead.id,
                event_key="operator-followup-1",
                action_type="待首次联系",
                result="pending",
                next_step="准备首次公开回复",
                occurred_at=datetime(2026, 7, 16, 9, 0, tzinfo=UTC),
                is_completed=False,
            ),
            FeishuBitableRecord(
                local_entity_type="customer_crm",
                local_entity_id=lead.id,
                app_token="crm-base-token",
                table_id="customer-table",
                record_id="rec-customer",
                sync_direction="bidirectional",
                last_sync_status="synced",
            ),
        ]
    )
    session.commit()
    return lead


def test_operator_customer_views_use_stable_customer_id_and_deep_links() -> None:
    factory = _factory()
    with factory() as session:
        lead = _seed(session)

        listing = list_operator_customers(session, limit=50, miaoda_base_url="https://miaoda.example/app")
        detail = get_operator_customer(session, lead.id, miaoda_base_url="https://miaoda.example/app")
        timeline = get_operator_customer_timeline(session, lead.id)

        assert listing["count"] == 1
        assert listing["items"][0]["customer_id"] == lead.id
        assert detail["customer_id"] == lead.id
        assert detail["crm_stage"] == "awaiting_first_contact"
        assert detail["sync_version"] == 3
        assert detail["sync_status"] == "synced"
        assert detail["next_step"] == "准备首次公开回复"
        assert detail["base_record_url"].endswith("?table=customer-table&record=rec-customer")
        assert detail["miaoda_detail_url"] == f"https://miaoda.example/app/customers/{lead.id}"
        assert [item["kind"] for item in timeline["items"]] == ["timeline_event", "followup_record"]


def test_operator_customer_detail_rejects_candidate_only_lead() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="candidate-only")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id)
        session.add(lead)
        session.commit()

        try:
            get_operator_customer(session, lead.id)
        except LookupError as exc:
            assert str(exc) == "customer not found"
        else:
            raise AssertionError("candidate-only Lead must not be exposed as a customer")


def test_operator_customer_views_include_migrated_qualified_customer_at_sync_version_zero() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="legacy-qualified")
        session.add(profile)
        session.flush()
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="qualified",
            crm_stage="new_customer",
            crm_sync_version=0,
        )
        session.add(lead)
        session.commit()

        listing = list_operator_customers(session)
        detail = get_operator_customer(session, lead.id)

        assert [item["customer_id"] for item in listing["items"]] == [lead.id]
        assert detail["customer_id"] == lead.id
        assert detail["sync_version"] == 0


def test_operator_customer_views_hide_deferred_candidate() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="deferred-candidate")
        session.add(profile)
        session.flush()
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="watch",
            crm_stage="deferred",
            crm_sync_version=1,
        )
        session.add(lead)
        session.commit()

        listing = list_operator_customers(session)

        assert listing["items"] == []
        try:
            get_operator_customer(session, lead.id)
        except LookupError as exc:
            assert str(exc) == "customer not found"
        else:
            raise AssertionError("deferred candidate must not be exposed as a customer")
