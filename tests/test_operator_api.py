from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
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
