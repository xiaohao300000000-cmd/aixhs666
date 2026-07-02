from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import storage.models  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from apps.worker.main import WorkerConfig, WorkerRunner
from collectors import MockPlatformAdapter
from scheduler import TaskStatus, create_task
from storage.database import Base, get_session
from storage.models import CollectionTask, Query, WorkerHeartbeat


@pytest.fixture()
def api_context(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    monkeypatch.setenv("OPS_TOKEN", "secret")
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


def test_ops_page_and_read_apis(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = api_context

    page = client.get("/ops")
    system = client.get("/ops/api/system")
    tasks = client.get("/ops/api/tasks")

    assert page.status_code == 200
    assert "AIXHS Ops" in page.text
    assert system.status_code == 200
    assert system.json()["api"]["status"] == "正常"
    assert tasks.status_code == 200


def test_ops_write_requires_token(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, _ = api_context

    rejected = client.post("/ops/api/tasks", json={"query_text": "KET 没过怎么办"})
    accepted = client.post(
        "/ops/api/tasks",
        headers={"X-Ops-Token": "secret"},
        json={"query_text": "KET 没过怎么办", "priority": 10},
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["created"] is True


def test_ops_task_creation_is_idempotent(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, SessionLocal = api_context
    payload = {"query_text": "PET 二刷", "priority": 20}

    first = client.post("/ops/api/tasks", headers={"X-Ops-Token": "secret"}, json=payload)
    second = client.post("/ops/api/tasks", headers={"X-Ops-Token": "secret"}, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    with SessionLocal() as session:
        assert session.query(CollectionTask).count() == 1


def test_ops_task_controls_validate_state(api_context: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, SessionLocal = api_context
    with SessionLocal() as session:
        task = create_task(session, task_type="search", platform="xhs")
        completed = create_task(session, task_type="search", platform="xhs")
        completed.status = TaskStatus.COMPLETED.value
        completed.finished_at = datetime(2026, 1, 1, tzinfo=UTC)
        session.commit()
        task_id = task.id
        completed_id = completed.id

    retry = client.post(f"/ops/api/tasks/{task_id}/retry", headers={"X-Ops-Token": "secret"})
    cancel_completed = client.post(f"/ops/api/tasks/{completed_id}/cancel", headers={"X-Ops-Token": "secret"})

    assert retry.status_code == 200
    assert retry.json()["status"] == TaskStatus.RETRY.value
    assert cancel_completed.status_code == 409


def test_worker_writes_heartbeat(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        query = Query(query_text="孩子英语跟不上", platform="xhs", query_type="seed", status="active")
        session.add(query)
        session.flush()
        create_task(session, task_type="search", platform="xhs", query_id=query.id)
        session.commit()

    runner = WorkerRunner(
        session_factory=factory,
        adapter=MockPlatformAdapter(),
        config=WorkerConfig(
            worker_id="worker-heartbeat",
            poll_interval_seconds=0,
            task_timeout_minutes=20,
            snapshot_root=tmp_path,
            once=True,
        ),
    )
    runner.run_once()

    with factory() as session:
        heartbeat = session.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == "worker-heartbeat"))
        assert heartbeat is not None
        assert heartbeat.status == "idle"
        assert heartbeat.completed_task_count == 1
        assert heartbeat.current_task_id is None
    Base.metadata.drop_all(engine)
    engine.dispose()
