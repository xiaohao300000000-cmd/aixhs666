from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from storage.database import Base, get_session
from storage.models import EnrichmentTask, Lead, LeadEvidence, PublicProfile


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()

    def override_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_leads_summary_groups_business_statuses(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        _seed_lead(session, status="new")
        _seed_lead(session, status="needs_enrichment", platform_user_id="u-2")
        _seed_lead(session, status="qualified", platform_user_id="u-3")
        _seed_lead(session, status="handled", platform_user_id="u-4")
        session.commit()

    response = client.get("/api/leads/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["today_new"] == 1
    assert payload["needs_enrichment"] == 1
    assert payload["qualified"] == 1
    assert payload["handled"] == 1


def test_leads_list_returns_cards_with_evidence(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        _seed_lead(session, status="needs_enrichment")
        session.commit()

    response = client.get("/api/leads", params={"status": "needs_enrichment"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["platform_user_id"] == "u-1"
    assert item["display_name"] == "福州家长"
    assert item["product"] == "PET"
    assert item["missing_info"] == ["contact"]
    assert item["evidence"][0]["evidence_text"] == "孩子 PET 压线没过，想找二刷冲刺班"
    assert item["enrichment_tasks"][0]["task_type"] == "fill_contact"


def test_lead_status_update(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        lead = _seed_lead(session, status="qualified")
        session.commit()
        lead_id = lead.id

    response = client.post(f"/api/leads/{lead_id}/status", json={"status": "handled"})

    assert response.status_code == 200
    assert response.json()["status"] == "handled"


def test_leads_page_is_product_entry(client: TestClient) -> None:
    response = client.get("/leads")

    assert response.status_code == 200
    assert "今日新发现" in response.text
    assert "待完善信息" in response.text
    assert "可跟进客户" in response.text
    assert "已处理客户" in response.text


def _seed_lead(session: Session, *, status: str, platform_user_id: str = "u-1") -> Lead:
    profile = PublicProfile(
        platform="xhs",
        platform_user_id=platform_user_id,
        display_name="福州家长",
        profile_url=f"https://example.test/user/{platform_user_id}",
        region_text="福州",
    )
    session.add(profile)
    session.flush()
    lead = Lead(
        platform="xhs",
        public_profile_id=profile.id,
        status=status,
        region_text="福州",
        demand_type="exam_retry",
        product="PET",
        intent_stage="recovery",
        intent_score=78,
        information_completeness=60,
        known_info_json={"region": "福州", "product": "PET"},
        missing_info_json=["contact"],
        recommended_next_step="补充公开联系方式后人工判断是否可跟进",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    session.add(lead)
    session.flush()
    session.add(
        LeadEvidence(
            lead_id=lead.id,
            source_entity_type="content",
            source_entity_id=1,
            evidence_text="孩子 PET 压线没过，想找二刷冲刺班",
            demand_type="exam_retry",
            intent_stage="recovery",
            score_contribution=78,
        )
    )
    session.add(
        EnrichmentTask(
            lead_id=lead.id,
            task_type="fill_contact",
            status="pending",
            reason="缺少公开联系方式，无法直接跟进",
        )
    )
    return lead
