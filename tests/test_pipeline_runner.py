from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import storage.models  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from apps.cli import main as cli_main
from collectors import MockPlatformAdapter
from services.pipeline_runner import PipelineRunner
from storage.database import Base, get_session
from storage.models import Comment, Content, PipelineRun, PublicProfile, Query


@pytest.fixture()
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
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


def test_pipeline_runner_mock_full_cycle(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path)

    payload = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    result = payload["result_data"]
    assert payload["status"] == "completed"
    assert result["queries"] == {"requested": 1, "completed": 1, "failed": 0}
    assert result["collection"]["contents_found"] == 1
    assert result["collection"]["new_contents"] == 1
    assert result["collection"]["new_comments"] == 2
    assert result["collection"]["new_profiles"] == 3
    assert result["processing"]["processed_contents"] >= 3
    assert result["processing"]["demand_events_created"] >= 1
    assert result["intelligence"]["clusters_created_or_updated"] >= 1
    assert result["intelligence"]["candidate_queries_created"] >= 1
    assert result["intelligence"]["query_scores_updated"] == 1
    assert result["insight"]["content_insights"] is not None
    with factory() as session:
        run = session.get(PipelineRun, payload["run_id"])
        assert run is not None
        assert run.status == "completed"
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2
        assert session.query(PublicProfile).count() == 3


def test_pipeline_runner_is_idempotent_for_repeated_query(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path)

    first = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")
    second = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test")

    assert first["result_data"]["collection"]["new_contents"] == 1
    assert second["result_data"]["collection"]["new_contents"] == 0
    assert second["result_data"]["collection"]["existing_contents"] == 1
    assert second["result_data"]["collection"]["new_comments"] == 0
    with factory() as session:
        assert session.query(PipelineRun).count() == 2
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2
        relation_count = session.scalar(select(func.count()).select_from(Content).join(Content.discovery_relations))
        assert relation_count == 1


def test_pipeline_runner_records_failure_and_retry_continues(factory: sessionmaker[Session], tmp_path: Path) -> None:
    query_id = _seed_query(factory, "admissions")
    runner = _runner(factory, tmp_path)

    failed = runner.run_cycle(query_ids=[query_id], collection_limit=20, requested_by="test", fail_stage="clustering")
    retried = runner.retry_run(failed["run_id"], requested_by="test-retry")

    assert failed["status"] == "failed"
    assert failed["progress_data"]["collection"] == "completed"
    assert failed["progress_data"]["clustering"] == "running"
    assert "simulated failure at stage: clustering" in failed["error_message"]
    assert retried["run_id"] == failed["run_id"]
    assert retried["status"] == "completed"
    assert retried["result_data"]["collection"]["new_contents"] == 0
    with factory() as session:
        assert session.query(Content).count() == 1
        assert session.query(Comment).count() == 2


def test_pipeline_api_and_cli_use_same_runner_shape(
    factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query_id = _seed_query(factory, "admissions")
    monkeypatch.setenv("WORKER_ADAPTER", "mock")
    monkeypatch.setenv("OPS_TOKEN", "secret")

    def override_get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        response = client.post(
            "/ops/api/pipeline/runs",
            headers={"X-Ops-Token": "secret"},
            json={"query_ids": [query_id], "collection_limit": 20, "requested_by": "api"},
        )
        status = client.get("/ops/api/runtime/status")
        latest = client.get("/ops/api/insights/latest")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    api_payload = response.json()
    assert api_payload["result_data"]["queries"]["requested"] == 1
    assert status.status_code == 200
    assert latest.status_code == 200

    import apps.cli as cli

    monkeypatch.setattr(cli, "SessionLocal", factory)
    assert cli_main(["--json", "run-status", str(api_payload["run_id"])]) == 0
    cli_payload = capsys.readouterr().out
    assert f'"run_id": {api_payload["run_id"]}' in cli_payload


def _runner(factory: sessionmaker[Session], tmp_path: Path) -> PipelineRunner:
    return PipelineRunner(
        session_factory=factory,
        adapter_factory=lambda: MockPlatformAdapter(),
        snapshot_root=tmp_path,
    )


def _seed_query(factory: sessionmaker[Session], query_text: str) -> int:
    with factory() as session:
        query = Query(
            query_text=query_text,
            platform="xhs",
            query_type="seed",
            status="active",
            priority=10,
            source="test",
        )
        session.add(query)
        session.commit()
        return query.id
