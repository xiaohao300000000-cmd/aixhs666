from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import storage.models  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from scheduler import TaskStatus, create_task
from storage.database import Base, get_session
from storage.models import CollectionTask, Content, DiscoveryRelation, Query


@pytest.fixture()
def api_context() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with SessionLocal() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client, SessionLocal
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_query(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = {
        "query_text": "社区养老服务",
        "platform": "xhs",
        "query_type": "seed",
    }
    payload.update(overrides)
    response = client.post("/queries", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_query_defaults_and_read_detail(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = api_context

    created = create_query(client)

    assert created["query_text"] == "社区养老服务"
    assert created["platform"] == "xhs"
    assert created["query_type"] == "seed"
    assert created["status"] == "active"
    assert created["priority"] == 0
    assert created["run_count"] == 0

    detail_response = client.get(f"/queries/{created['id']}")

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == created["id"]

    missing_response = client.get("/queries/9999")

    assert missing_response.status_code == 404


def test_list_queries_filters_by_platform_status_and_type(
    api_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_context
    active_seed = create_query(client, query_text="上海养老", platform="xhs", query_type="seed")
    paused_generated = create_query(
        client,
        query_text="广州养老",
        platform="xhs",
        query_type="generated",
        status="paused",
    )
    other_platform = create_query(client, query_text="机构护理", platform="douyin", query_type="seed")

    platform_response = client.get("/queries", params={"platform": "xhs"})
    status_response = client.get("/queries", params={"status": "active"})
    type_response = client.get("/queries", params={"query_type": "generated"})
    combined_response = client.get(
        "/queries",
        params={"platform": "xhs", "status": "active", "query_type": "seed"},
    )

    assert [item["id"] for item in platform_response.json()] == [active_seed["id"], paused_generated["id"]]
    assert [item["id"] for item in status_response.json()] == [active_seed["id"], other_platform["id"]]
    assert [item["id"] for item in type_response.json()] == [paused_generated["id"]]
    assert [item["id"] for item in combined_response.json()] == [active_seed["id"]]


def test_update_query_and_start_stop(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = api_context
    created = create_query(client)

    update_response = client.patch(
        f"/queries/{created['id']}",
        json={
            "query_text": "社区养老餐厅",
            "query_type": "problem",
            "status": "paused",
            "priority": 7,
            "source": "manual",
            "next_run_at": "2026-01-02T03:04:05+00:00",
        },
    )

    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["query_text"] == "社区养老餐厅"
    assert updated["query_type"] == "problem"
    assert updated["status"] == "paused"
    assert updated["priority"] == 7
    assert updated["source"] == "manual"
    assert updated["next_run_at"].startswith("2026-01-02T03:04:05")

    started = client.post(f"/queries/{created['id']}/start")
    stopped = client.post(f"/queries/{created['id']}/stop")

    assert started.status_code == 200
    assert started.json()["status"] == "active"
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "paused"

    detail = client.get(f"/queries/{created['id']}")
    assert detail.json()["query_text"] == "社区养老餐厅"
    assert detail.json()["status"] == "paused"


def test_manual_run_creates_pending_search_task(
    api_context: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, SessionLocal = api_context
    created = create_query(client, query_text="长期护理险", priority=9)

    response = client.post(f"/queries/{created['id']}/run")

    assert response.status_code == 201
    task = response.json()
    assert task["task_type"] == "search"
    assert task["platform"] == "xhs"
    assert task["target_id"] == "长期护理险"
    assert task["query_id"] == created["id"]
    assert task["priority"] == 9
    assert task["status"] == TaskStatus.PENDING.value
    assert task["payload_json"]["query_text"] == "长期护理险"
    assert task["payload_json"]["query_type"] == "seed"

    with SessionLocal() as session:
        stored_task = session.get(CollectionTask, task["id"])
        assert stored_task is not None
        assert stored_task.query_id == created["id"]
        assert stored_task.status == TaskStatus.PENDING.value


def test_query_stats_returns_basic_counts(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, SessionLocal = api_context
    created = create_query(client, next_run_at="2026-01-03T00:00:00+00:00")

    with SessionLocal() as session:
        stored_query = session.get(Query, created["id"])
        assert stored_query is not None
        stored_query.run_count = 3
        stored_query.last_run_at = datetime(2026, 1, 2, 8, 30, tzinfo=UTC)
        content = Content(platform="xhs", platform_content_id="note-1", content_type="note")
        session.add(content)
        session.flush()
        session.add(
            DiscoveryRelation(
                query_id=created["id"],
                content_id=content.id,
                rank_position=1,
                result_page=1,
                discovery_method="search",
            )
        )
        create_task(session, task_type="search", platform="xhs", query_id=created["id"])
        create_task(session, task_type="search", platform="xhs", query_id=created["id"])
        session.commit()

    response = client.get(f"/queries/{created['id']}/stats")

    assert response.status_code == 200
    stats = response.json()
    assert stats["query_id"] == created["id"]
    assert stats["run_count"] == 3
    assert stats["last_run_at"].startswith("2026-01-02T08:30:00")
    assert stats["next_run_at"].startswith("2026-01-03T00:00:00")
    assert stats["discovery_count"] == 1
    assert stats["task_count"] == 2
