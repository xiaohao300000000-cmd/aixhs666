from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.operator_gateway import create_operator_gateway
from storage.database import Base, get_session


@pytest.fixture()
def gateway_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("OPS_TOKEN", "gateway-secret")
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

    app = create_operator_gateway()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_gateway_exposes_only_health_and_operator_routes(gateway_client: TestClient) -> None:
    operator = gateway_client.get("/operator/api/workbench")
    leads = gateway_client.get("/api/leads")
    ops = gateway_client.get("/ops/api/system")
    callback = gateway_client.post("/feishu/callback/llm-review")

    assert operator.status_code == 401
    assert leads.status_code == 404
    assert ops.status_code == 404
    assert callback.status_code == 404


def test_gateway_health_is_public(gateway_client: TestClient) -> None:
    response = gateway_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "operator-gateway"}


def test_gateway_workbench_requires_token(gateway_client: TestClient) -> None:
    missing = gateway_client.get("/operator/api/workbench")
    authorized = gateway_client.get(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer gateway-secret"},
    )

    assert missing.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["next_action"]["kind"] == "none"


def test_gateway_exposes_authenticated_lead_and_task_operator_routes(gateway_client: TestClient) -> None:
    headers = {"Authorization": "Bearer gateway-secret"}

    leads = gateway_client.get("/operator/api/leads", headers=headers)
    tasks = gateway_client.get("/operator/api/tasks", headers=headers)
    customers = gateway_client.get("/operator/api/customers", headers=headers)
    customer_sync_without_key = gateway_client.post("/operator/api/customers/sync", headers=headers, json={})
    queue_missing_token = gateway_client.get("/operator/api/review-queue")
    queue = gateway_client.get("/operator/api/review-queue", headers=headers)

    assert leads.status_code == 200
    assert leads.json()["items"] == []
    assert tasks.status_code == 200
    assert tasks.json()["templates"][0]["key"] == "screen_historical_leads"
    assert customers.status_code == 200
    assert customers.json()["items"] == []
    assert customer_sync_without_key.status_code == 422
    assert queue_missing_token.status_code == 401
    assert queue.status_code == 200
    assert queue.json()["progress"]["target"] == 0


def test_gateway_rejects_unsupported_methods(gateway_client: TestClient) -> None:
    response = gateway_client.post(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer gateway-secret"},
    )

    assert response.status_code == 405
