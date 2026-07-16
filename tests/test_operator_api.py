from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from services.customer_progression import CustomerProgressionResult
from services.customer_crm_sync import CustomerCrmSyncResult
from storage.database import Base, get_session


@pytest.fixture()
def operator_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("OPS_TOKEN", "operator-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_operator_workbench_rejects_missing_token(operator_client: TestClient) -> None:
    response = operator_client.get("/operator/api/workbench")

    assert response.status_code == 401


def test_operator_workbench_rejects_wrong_token(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_operator_workbench_returns_aggregate(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer operator-secret"},
    )

    assert response.status_code == 200
    assert response.json()["attention"]["review_queue"] == 0
    assert response.json()["next_action"]["kind"] == "none"


def test_operator_workbench_accepts_compatibility_header(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"X-Ops-Token": "operator-secret"},
    )

    assert response.status_code == 200


def test_operator_leads_and_tasks_require_same_token(operator_client: TestClient) -> None:
    missing_leads = operator_client.get("/operator/api/leads")
    missing_tasks = operator_client.get("/operator/api/tasks")
    headers = {"Authorization": "Bearer operator-secret"}

    leads = operator_client.get("/operator/api/leads", headers=headers)
    tasks = operator_client.get("/operator/api/tasks", headers=headers)

    assert missing_leads.status_code == 401
    assert missing_tasks.status_code == 401
    assert leads.status_code == 200
    assert tasks.status_code == 200


def test_operator_promote_returns_structured_consequences(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def progress(_session: Session, lead_id: int, **kwargs: object) -> CustomerProgressionResult:
        calls.append({"lead_id": lead_id, **kwargs})
        return CustomerProgressionResult(
            customer_id=lead_id,
            customer_stage="awaiting_first_contact",
            next_action="prepare_public_reply",
            timeline_event_id=91,
            timeline_event_type="candidate_promoted",
            screening_id=17,
            idempotent_replay=False,
        )

    monkeypatch.setattr("apps.api.routes.operator_api.progress_operator_lead", progress)
    monkeypatch.setattr("apps.api.routes.operator_api.get_operator_lead", lambda _session, lead_id: {"id": lead_id})

    response = operator_client.post(
        "/operator/api/leads/151/review",
        headers={"Authorization": "Bearer operator-secret"},
        json={
            "action": "promote",
            "reason": "需求明确",
            "reviewer_id": "operator-1",
            "idempotency_key": "ui-review-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["lead"] == {"id": 151}
    assert response.json()["progression"]["customer_stage"] == "awaiting_first_contact"
    assert response.json()["progression"]["next_action"] == "prepare_public_reply"
    assert calls[0]["action"] == "promote"
    assert calls[0]["idempotency_key"] == "ui-review-1"


def test_operator_customer_routes_and_sync_require_idempotency_key(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Authorization": "Bearer operator-secret"}
    monkeypatch.setattr(
        "apps.api.routes.operator_api.list_operator_customers",
        lambda _session, **_kwargs: {"items": [{"customer_id": 151}], "count": 1},
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_customer",
        lambda _session, customer_id: {"customer_id": customer_id},
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_customer_timeline",
        lambda _session, customer_id: {"customer_id": customer_id, "items": []},
    )
    sync_calls: list[list[int] | None] = []

    def sync(_factory, *, customer_ids=None):
        sync_calls.append(customer_ids)
        return CustomerCrmSyncResult(status="synced", customers_synced=1)

    monkeypatch.setattr("apps.api.routes.operator_api.sync_customer_crm", sync)

    listing = operator_client.get("/operator/api/customers", headers=headers)
    detail = operator_client.get("/operator/api/customers/151", headers=headers)
    timeline = operator_client.get("/operator/api/customers/151/timeline", headers=headers)
    missing_key = operator_client.post("/operator/api/customers/sync", headers=headers, json={})
    synced = operator_client.post(
        "/operator/api/customers/sync",
        headers=headers,
        json={"customer_ids": [151], "idempotency_key": "customer-sync-1"},
    )

    assert listing.status_code == 200
    assert detail.json()["customer_id"] == 151
    assert timeline.json()["items"] == []
    assert missing_key.status_code == 422
    assert synced.status_code == 200
    assert synced.json()["idempotency_key"] == "customer-sync-1"
    assert synced.json()["sync"]["customers_synced"] == 1
    assert sync_calls == [[151]]
