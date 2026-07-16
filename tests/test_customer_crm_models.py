from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from storage.database import Base
from storage.models import CustomerFollowupRecord, Lead, PublicProfile


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_lead_has_stable_customer_crm_facts() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="crm-user")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id)
        session.add(lead)
        session.flush()

        assert lead.crm_stage == "candidate"
        assert lead.customer_tags_json == []
        assert lead.last_contact_at is None
        assert lead.last_contact_result is None
        assert lead.crm_sync_version == 0


def test_customer_followup_record_has_unique_event_key_and_customer_time_index() -> None:
    factory = _factory()
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="followup-user")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id)
        session.add(lead)
        session.flush()
        occurred_at = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)
        first = CustomerFollowupRecord(
            lead_id=lead.id,
            event_key="customer:first-contact:1",
            occurred_at=occurred_at,
            action_type="待首次联系",
            channel="xhs_public_reply",
            target="comment-1",
            content="准备首次公开回复",
            customer_reply=None,
            result="pending",
            next_step="准备首次公开回复",
            next_followup_at=None,
            source_entry="customer_progression",
            platform_evidence_json={"comment_id": "comment-1"},
            is_completed=False,
        )
        session.add(first)
        session.commit()

        session.add(
            CustomerFollowupRecord(
                lead_id=lead.id,
                event_key=first.event_key,
                occurred_at=occurred_at,
                action_type="待首次联系",
                is_completed=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    indexes = {item["name"] for item in inspect(factory.kw["bind"]).get_indexes("customer_followup_records")}
    assert "ix_customer_followup_records_lead_occurred" in indexes


def test_customer_crm_migration_uses_official_stage_and_backfills_customer_fact() -> None:
    migration = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0018_customer_crm.py"
    ).read_text(encoding="utf-8")

    assert "WHEN status = 'qualified' THEN 'new_customer'" in migration
    assert "WHEN status = 'qualified' THEN 'qualified'" not in migration
    assert "crm-migration-customer:" in migration
