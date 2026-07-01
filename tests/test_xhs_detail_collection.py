from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.worker.detail_collection import DetailCollectionError, run_detail_task, run_next_detail_task
from collectors import CollectedContent, MockPlatformAdapter
from scheduler import TaskStatus, claim_next_task, create_task
from storage import ingest_content
from storage.database import Base
from storage.models import CollectionTask, Content, PublicProfile, Snapshot


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_detail_task_collects_l1_fields_saves_snapshot_and_completes(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = MockPlatformAdapter()
    seed = replace(adapter.get_content("note-ai-001"), body_text=None, like_count=0, tags=(), image_urls=())
    ingest_content(session, seed)
    task = create_task(session, task_type="collect_content", platform="xhs", target_id="note-ai-001")

    result = run_next_detail_task(
        session,
        adapter=adapter,
        worker_id="worker-t08",
        snapshot_root=tmp_path,
    )

    assert result is task
    assert task.status == TaskStatus.COMPLETED.value

    content = session.scalar(select(Content).where(Content.platform_content_id == "note-ai-001"))
    assert content is not None
    assert content.body_text == "A mock note about preparing applications with AI background projects."
    assert content.published_at is not None
    assert content.region_text == "Shanghai"
    assert content.like_count == 128
    assert content.comment_count == 2
    assert content.collect_count == 46

    author = session.scalar(select(PublicProfile).where(PublicProfile.platform_user_id == "user-author-001"))
    assert author is not None
    assert author.display_name == "AI Admissions Lab"
    assert content.author_profile_id == author.id

    snapshot = session.scalar(select(Snapshot))
    assert snapshot is not None
    assert snapshot.entity_type == "content"
    assert snapshot.entity_id == content.id
    assert snapshot.snapshot_type == "content_detail"
    snapshot_body = Path(snapshot.object_storage_path).read_text(encoding="utf-8")
    assert '"tags":["AI","admissions","planning"]' in snapshot_body
    assert '"image_urls":["https://mock.xhs.local/images/note-ai-001-cover.jpg"]' in snapshot_body
    assert '"display_name":"AI Admissions Lab"' in snapshot_body


def test_detail_task_can_read_platform_content_id_from_payload(session: Session, tmp_path: Path) -> None:
    task = create_task(
        session,
        task_type="collect_content",
        platform="xhs",
        payload_json={"platform_content_id": "note-ai-002"},
    )

    claim_next_task(session, worker_id="worker-t08")
    run_detail_task(session, task=task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    content = session.scalar(select(Content).where(Content.platform_content_id == "note-ai-002"))
    assert content is not None
    assert content.body_text == "A mock note comparing school visit questions across regions."
    assert task.status == TaskStatus.COMPLETED.value


def test_repeated_detail_execution_is_idempotent_for_content_and_profile(
    session: Session,
    tmp_path: Path,
) -> None:
    first_task = create_task(session, task_type="collect_content", platform="xhs", target_id="note-ai-001")
    second_task = create_task(session, task_type="collect_content", platform="xhs", target_id="note-ai-001")

    claim_next_task(session, worker_id="worker-a")
    run_detail_task(session, task=first_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)
    claim_next_task(session, worker_id="worker-b")
    run_detail_task(session, task=second_task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    contents = session.scalars(select(Content)).all()
    profiles = session.scalars(select(PublicProfile)).all()
    snapshots = session.scalars(select(Snapshot).order_by(Snapshot.id)).all()

    assert [content.platform_content_id for content in contents] == ["note-ai-001"]
    assert [profile.platform_user_id for profile in profiles] == ["user-author-001"]
    assert len(snapshots) == 2
    assert snapshots[0].content_hash == snapshots[1].content_hash
    assert snapshots[0].object_storage_path == snapshots[1].object_storage_path


def test_detail_adapter_error_moves_task_to_retry_and_records_error(session: Session, tmp_path: Path) -> None:
    task = create_task(
        session,
        task_type="collect_content",
        platform="xhs",
        target_id="note-ai-001",
        max_attempts=2,
    )

    claim_next_task(session, worker_id="worker-t08")
    with pytest.raises(RuntimeError, match="detail unavailable"):
        run_detail_task(session, task=task, adapter=FailingDetailAdapter(), snapshot_root=tmp_path)

    assert task.status == TaskStatus.RETRY.value
    assert task.attempt_count == 1
    assert task.last_error == "detail unavailable"


def test_detail_task_requires_platform_content_id(session: Session, tmp_path: Path) -> None:
    task = create_task(session, task_type="collect_content", platform="xhs")

    claim_next_task(session, worker_id="worker-t08")
    with pytest.raises(DetailCollectionError, match="requires target_id"):
        run_detail_task(session, task=task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    assert task.status == TaskStatus.RETRY.value


class FailingDetailAdapter(MockPlatformAdapter):
    def get_content(self, platform_content_id: str) -> CollectedContent:
        raise RuntimeError("detail unavailable")
