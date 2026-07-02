from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.main import WorkerConfig, WorkerRunner, build_parser
from collectors import MockPlatformAdapter
from scheduler import TaskStatus, claim_next_task, create_task
from storage.database import Base
from storage.models import CollectionTask, Content, DiscoveryRelation, PublicProfile, Query, Snapshot


def test_worker_once_processes_search_task_and_commits(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        query = _query(session, "admissions")
        create_task(session, task_type="search", platform="xhs", query_id=query.id)
        session.commit()

    runner = _runner(factory, tmp_path)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        assert session.scalar(select(Content).where(Content.platform_content_id == "note-ai-001")) is not None
        assert session.scalar(select(DiscoveryRelation)) is not None


def test_worker_resumes_partial_search_task(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        query = _query(session, "ai-study")
        create_task(session, task_type="search", platform="xhs", query_id=query.id, payload_json={"limit": 1})
        session.commit()

    runner = _runner(factory, tmp_path)
    first = runner.run_once()
    second = runner.run_once()

    assert first is not None
    assert second is not None
    with factory() as session:
        task = session.get(CollectionTask, first.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        content_ids = list(session.scalars(select(Content.platform_content_id).order_by(Content.platform_content_id)))
        assert content_ids == ["note-ai-001", "note-ai-002"]


def test_worker_handles_unsupported_task_without_exiting(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        unsupported = create_task(
            session,
            task_type="unsupported",
            platform="xhs",
            priority=10,
            max_attempts=1,
        )
        query = _query(session, "admissions")
        create_task(session, task_type="search", platform="xhs", query_id=query.id, priority=0)
        session.commit()

    runner = _runner(factory, tmp_path)
    failed = runner.run_once()
    processed = runner.run_once()

    assert failed is not None
    assert processed is not None
    with factory() as session:
        failed_task = session.get(CollectionTask, unsupported.id)
        assert failed_task is not None
        assert failed_task.status == TaskStatus.FAILED.value
        assert failed_task.last_error == "unsupported task type: unsupported"
        search_task = session.get(CollectionTask, processed.id)
        assert search_task is not None
        assert search_task.status == TaskStatus.COMPLETED.value


def test_worker_recovers_timed_out_task_before_claiming(tmp_path: Path) -> None:
    factory = _session_factory()
    old_now = datetime(2026, 1, 1, tzinfo=UTC)
    with factory() as session:
        query = _query(session, "admissions")
        task = create_task(session, task_type="search", platform="xhs", query_id=query.id, now=old_now)
        claim_next_task(session, worker_id="stale-worker", now=old_now)
        task.started_at = old_now - timedelta(hours=2)
        session.commit()

    runner = _runner(factory, tmp_path, task_timeout_minutes=30)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        assert task.last_error is None


def test_worker_processes_profile_task(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        create_task(session, task_type="profile", platform="xhs", target_id="user-author-001")
        session.commit()

    runner = _runner(factory, tmp_path)
    result = runner.run_once()

    assert result is not None
    with factory() as session:
        task = session.get(CollectionTask, result.id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED.value
        profile = session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "user-author-001"))
        assert profile is not None
        assert profile.display_name == "AI Admissions Lab"
        snapshot = session.scalar(select(Snapshot).where(Snapshot.entity_type == "profile"))
        assert snapshot is not None
        assert Path(snapshot.object_storage_path).exists()


def test_worker_cli_parser_supports_once_and_worker_id() -> None:
    args = build_parser().parse_args(["--once", "--worker-id", "worker-test", "--poll-interval", "0.1"])

    assert args.once is True
    assert args.worker_id == "worker-test"
    assert args.poll_interval == 0.1


def _runner(
    factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    task_timeout_minutes: int = 20,
) -> WorkerRunner:
    config = WorkerConfig(
        worker_id="worker-test",
        poll_interval_seconds=0,
        task_timeout_minutes=task_timeout_minutes,
        snapshot_root=tmp_path,
        once=True,
    )
    return WorkerRunner(
        session_factory=factory,
        adapter=MockPlatformAdapter(),
        config=config,
        sleep=lambda _seconds: None,
    )


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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
