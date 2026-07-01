from __future__ import annotations

from pathlib import Path

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.worker.search_collection import run_next_search_task, run_search_task
from collectors import MockPlatformAdapter
from scheduler import TaskStatus, claim_next_task, create_task
from storage.database import Base
from storage.models import CollectionTask, Content, DiscoveryRelation, Query, Snapshot


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_search_task_collects_results_saves_snapshot_and_completes(session: Session, tmp_path: Path) -> None:
    query = _query(session, "admissions")
    task = create_task(session, task_type="search", platform="xhs", query_id=query.id, payload_json={"limit": 20})

    result = run_next_search_task(
        session,
        adapter=MockPlatformAdapter(),
        worker_id="worker-t07",
        snapshot_root=tmp_path,
    )

    assert result is task
    assert task.status == TaskStatus.COMPLETED.value
    assert task.cursor_json == {
        "next_cursor": None,
        "has_more": False,
        "limit": 20,
        "query_text": "admissions",
    }

    contents = session.scalars(select(Content)).all()
    assert [content.platform_content_id for content in contents] == ["note-ai-001"]

    relations = session.scalars(select(DiscoveryRelation)).all()
    assert len(relations) == 1
    assert relations[0].query_id == query.id
    assert relations[0].content_id == contents[0].id
    assert relations[0].discovery_method == "search"

    snapshot = session.scalar(select(Snapshot))
    assert snapshot is not None
    assert snapshot.entity_type == "query"
    assert snapshot.entity_id == query.id
    assert snapshot.snapshot_type == "search_page"
    assert Path(snapshot.object_storage_path).exists()
    assert '"platform_content_id":"note-ai-001"' in Path(snapshot.object_storage_path).read_text(encoding="utf-8")


def test_search_task_marks_partial_and_keeps_next_cursor(session: Session, tmp_path: Path) -> None:
    query = _query(session, "ai-study")
    task = create_task(session, task_type="search", platform="xhs", query_id=query.id, payload_json={"limit": 1})

    claim_next_task(session, worker_id="worker-t07")
    run_search_task(session, task=task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    assert task.status == TaskStatus.PARTIAL.value
    assert task.cursor_json == {
        "next_cursor": "1",
        "has_more": True,
        "limit": 1,
        "query_text": "ai-study",
    }
    assert session.scalars(select(Content)).all()[0].platform_content_id == "note-ai-001"


def test_repeated_search_execution_is_idempotent_for_contents_and_discoveries(
    session: Session,
    tmp_path: Path,
) -> None:
    query = _query(session, "ai-study")
    first_task = create_task(session, task_type="search", platform="xhs", query_id=query.id)
    second_task = create_task(session, task_type="search", platform="xhs", query_id=query.id)

    claim_next_task(session, worker_id="worker-a")
    run_search_task(session, task=first_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)
    claim_next_task(session, worker_id="worker-b")
    run_search_task(session, task=second_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    contents = session.scalars(select(Content).order_by(Content.platform_content_id)).all()
    relations = session.scalars(select(DiscoveryRelation).order_by(DiscoveryRelation.content_id)).all()

    assert [content.platform_content_id for content in contents] == ["note-ai-001", "note-ai-002"]
    assert len(relations) == 2
    assert {relation.query_id for relation in relations} == {query.id}


def test_adapter_error_moves_task_to_retry_and_records_error(session: Session, tmp_path: Path) -> None:
    query = _query(session, "ai-study")
    task = create_task(session, task_type="search", platform="xhs", query_id=query.id, max_attempts=2)
    adapter = FailingSearchAdapter()

    claim_next_task(session, worker_id="worker-t07")
    with pytest.raises(RuntimeError, match="adapter unavailable"):
        run_search_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.RETRY.value
    assert task.attempt_count == 1
    assert task.last_error == "adapter unavailable"


def test_snapshot_hash_is_stable_for_same_search_page(session: Session, tmp_path: Path) -> None:
    query = _query(session, "admissions")
    first_task = create_task(session, task_type="search", platform="xhs", query_id=query.id)
    second_task = create_task(session, task_type="search", platform="xhs", query_id=query.id)

    claim_next_task(session, worker_id="worker-a")
    run_search_task(session, task=first_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)
    claim_next_task(session, worker_id="worker-b")
    run_search_task(session, task=second_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    snapshots = session.scalars(select(Snapshot).order_by(Snapshot.id)).all()
    assert len(snapshots) == 2
    assert snapshots[0].content_hash == snapshots[1].content_hash
    assert snapshots[0].object_storage_path == snapshots[1].object_storage_path


class FailingSearchAdapter(MockPlatformAdapter):
    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20):  # type: ignore[no-untyped-def]
        raise RuntimeError("adapter unavailable")


def _query(session: Session, query_text: str) -> Query:
    query = Query(
        query_text=query_text,
        platform="xhs",
        query_type="seed",
        status="active",
        source="test",
    )
    session.add(query)
    session.flush()
    return query
