from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

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
        _seed_lead(session, status="watch", platform_user_id="u-5")
        _seed_lead(session, status="information_insufficient", platform_user_id="u-6")
        session.commit()

    response = client.get("/api/leads/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["today_new"] == 1
    assert payload["needs_enrichment"] == 1
    assert payload["qualified"] == 1
    assert payload["handled"] == 1
    assert payload["watch"] == 1
    assert payload["information_insufficient"] == 1
    assert payload["priority_immediate"] >= 1


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


def test_leads_list_returns_workbench_judgment_context(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        _seed_lead(session, status="needs_enrichment", first_seen_delta=timedelta(hours=2), source_entity_type="comment")
        session.commit()

    response = client.get("/api/leads", params={"status": "needs_enrichment"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["business_summary"] == "福州家长咨询 PET 二刷冲刺班，评论区表达备考需求"
    assert item["priority_bucket"] == "立即处理"
    assert item["sla_due_label"] == "24小时内处理"
    assert item["freshness_label"] == "2小时前"
    assert item["source_role"] == "评论者表达需求"
    assert item["why_recommended"] == [
        "评论原文明确提到 PET 压线没过和二刷冲刺班",
        "意向分 78，属于高优先级线索",
        "地区已知：福州",
    ]
    assert item["judgment_actions"] == [
        {"status": "qualified", "label": "有效"},
        {"status": "ignored", "label": "无效"},
        {"status": "watch", "label": "观察"},
        {"status": "information_insufficient", "label": "信息不足"},
        {"status": "duplicate", "label": "重复"},
        {"status": "handled", "label": "已联系"},
    ]
    assert item["evidence_context"][0]["source_role"] == "评论者表达需求"
    assert item["evidence_context"][0]["full_text"] == "孩子 PET 压线没过，想找二刷冲刺班"


def test_leads_list_sorts_by_business_priority_before_pagination(
    factory: sessionmaker[Session], client: TestClient
) -> None:
    with factory() as session:
        _seed_lead(
            session,
            status="needs_enrichment",
            platform_user_id="u-high",
            first_seen_delta=timedelta(hours=2),
            created_delta=timedelta(days=2),
            intent_score=82,
        )
        _seed_lead(
            session,
            status="needs_enrichment",
            platform_user_id="u-low",
            first_seen_delta=timedelta(days=10),
            created_delta=timedelta(minutes=1),
            intent_score=95,
        )
        session.commit()

    response = client.get("/api/leads", params={"page_size": 1})

    assert response.status_code == 200
    assert response.json()["items"][0]["platform_user_id"] == "u-high"


def test_lead_status_update(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        lead = _seed_lead(session, status="qualified")
        session.commit()
        lead_id = lead.id

    response = client.post(f"/api/leads/{lead_id}/status", json={"status": "handled"})

    assert response.status_code == 200
    assert response.json()["status"] == "handled"


def test_lead_status_update_accepts_operator_judgment_statuses(factory: sessionmaker[Session], client: TestClient) -> None:
    with factory() as session:
        lead = _seed_lead(session, status="needs_enrichment")
        session.commit()
        lead_id = lead.id

    response = client.post(f"/api/leads/{lead_id}/status", json={"status": "watch"})

    assert response.status_code == 200
    assert response.json()["status"] == "watch"


def test_leads_page_is_product_entry(client: TestClient) -> None:
    response = client.get("/leads")

    assert response.status_code == 200
    assert "今日新发现" in response.text
    assert "立即处理" in response.text
    assert "今日内处理" in response.text
    assert "可观察" in response.text
    assert "信息不足" in response.text


def _seed_lead(
    session: Session,
    *,
    status: str,
    platform_user_id: str = "u-1",
    first_seen_delta: timedelta = timedelta(hours=1),
    created_delta: timedelta | None = None,
    source_entity_type: str = "content",
    intent_score: int = 78,
) -> Lead:
    seen_at = datetime.now(UTC) - first_seen_delta
    created_at = datetime.now(UTC) - created_delta if created_delta is not None else None
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
        intent_score=intent_score,
        information_completeness=60,
        known_info_json={"region": "福州", "product": "PET"},
        missing_info_json=["contact"],
        recommended_next_step="补充公开联系方式后人工判断是否可跟进",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    if created_at is not None:
        lead.created_at = created_at
        lead.updated_at = created_at
    session.add(lead)
    session.flush()
    session.add(
        LeadEvidence(
            lead_id=lead.id,
            source_entity_type=source_entity_type,
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
