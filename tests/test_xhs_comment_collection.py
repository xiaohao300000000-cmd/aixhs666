from __future__ import annotations

from pathlib import Path

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.worker.comment_collection import CommentCollectionError, run_comment_task, run_next_comment_task
from collectors import CommentPage, MockPlatformAdapter
from scheduler import TaskStatus, claim_next_task, create_task
from storage import ingest_content
from storage.database import Base
from storage.models import CollectionTask, Comment, PublicProfile, Snapshot


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_comment_task_collects_l2_comments_profiles_snapshot_and_completes(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = MockPlatformAdapter()
    _seed_content(session, adapter)
    task = create_task(session, task_type="comments", platform="xhs", target_id="note-ai-001")

    result = run_next_comment_task(
        session,
        adapter=adapter,
        worker_id="worker-t09",
        snapshot_root=tmp_path,
    )

    assert result is task
    assert task.status == TaskStatus.COMPLETED.value
    assert task.cursor_json == {
        "next_cursor": None,
        "has_more": False,
        "limit": 20,
        "platform_content_id": "note-ai-001",
    }

    comments = session.scalars(select(Comment).order_by(Comment.platform_comment_id)).all()
    assert [comment.platform_comment_id for comment in comments] == ["comment-ai-001", "comment-ai-002"]
    assert comments[0].body_text == "Which project evidence should be prepared first?"
    assert comments[0].parent_comment_id is None
    assert comments[1].parent_comment_id == comments[0].id

    profiles = session.scalars(select(PublicProfile).order_by(PublicProfile.platform_user_id)).all()
    assert [profile.platform_user_id for profile in profiles] == [
        "user-author-001",
        "user-parent-001",
        "user-student-001",
    ]

    snapshot = session.scalar(select(Snapshot))
    assert snapshot is not None
    assert snapshot.entity_type == "content"
    assert snapshot.entity_id == comments[0].content_id
    assert snapshot.snapshot_type == "comments_page"
    assert Path(snapshot.object_storage_path).exists()
    snapshot_body = Path(snapshot.object_storage_path).read_text(encoding="utf-8")
    assert '"platform_comment_id":"comment-ai-001"' in snapshot_body
    assert '"snapshot_type"' not in snapshot_body


def test_comment_task_marks_partial_and_keeps_comment_cursor(session: Session, tmp_path: Path) -> None:
    adapter = MockPlatformAdapter()
    _seed_content(session, adapter)
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"limit": 1},
    )

    claim_next_task(session, worker_id="worker-t09")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.PARTIAL.value
    assert task.cursor_json == {
        "next_cursor": "1",
        "has_more": True,
        "limit": 1,
        "platform_content_id": "note-ai-001",
    }
    comments = session.scalars(select(Comment)).all()
    assert [comment.platform_comment_id for comment in comments] == ["comment-ai-001"]


def test_comment_task_can_read_platform_content_id_from_payload(session: Session, tmp_path: Path) -> None:
    adapter = MockPlatformAdapter()
    _seed_content(session, adapter)
    task = create_task(
        session,
        task_type="collect_comments",
        platform="xhs",
        payload_json={"platform_content_id": "note-ai-001"},
    )

    claim_next_task(session, worker_id="worker-t09")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.COMPLETED.value
    assert session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-001")) is not None


def test_repeated_comment_execution_is_idempotent_for_comments_and_profiles(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = MockPlatformAdapter()
    _seed_content(session, adapter)
    first_task = create_task(session, task_type="comments", platform="xhs", target_id="note-ai-001")
    second_task = create_task(session, task_type="comments", platform="xhs", target_id="note-ai-001")

    claim_next_task(session, worker_id="worker-a")
    run_comment_task(session, task=first_task, adapter=adapter, snapshot_root=tmp_path)
    claim_next_task(session, worker_id="worker-b")
    run_comment_task(session, task=second_task, adapter=adapter, snapshot_root=tmp_path)

    comments = session.scalars(select(Comment).order_by(Comment.platform_comment_id)).all()
    profiles = session.scalars(select(PublicProfile).order_by(PublicProfile.platform_user_id)).all()
    snapshots = session.scalars(select(Snapshot).order_by(Snapshot.id)).all()

    assert [comment.platform_comment_id for comment in comments] == ["comment-ai-001", "comment-ai-002"]
    assert [profile.platform_user_id for profile in profiles] == [
        "user-author-001",
        "user-parent-001",
        "user-student-001",
    ]
    assert len(snapshots) == 2
    assert snapshots[0].content_hash == snapshots[1].content_hash
    assert snapshots[0].object_storage_path == snapshots[1].object_storage_path


def test_comment_task_builds_reply_relationship_when_reply_precedes_parent(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = ReversedCommentAdapter()
    _seed_content(session, adapter)
    task = create_task(session, task_type="comments", platform="xhs", target_id="note-ai-001")

    claim_next_task(session, worker_id="worker-t09")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    parent = session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-001"))
    reply = session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-002"))
    assert parent is not None
    assert reply is not None
    assert reply.parent_comment_id == parent.id


def test_comment_adapter_error_moves_task_to_retry_and_records_error(session: Session, tmp_path: Path) -> None:
    adapter = FailingCommentAdapter()
    _seed_content(session, adapter)
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        max_attempts=2,
    )

    claim_next_task(session, worker_id="worker-t09")
    with pytest.raises(RuntimeError, match="comments unavailable"):
        run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.RETRY.value
    assert task.attempt_count == 1
    assert task.last_error == "comments unavailable"


def test_comment_task_requires_existing_content(session: Session, tmp_path: Path) -> None:
    task = create_task(session, task_type="comments", platform="xhs", target_id="note-ai-001")

    claim_next_task(session, worker_id="worker-t09")
    with pytest.raises(CommentCollectionError, match="must exist before collecting comments"):
        run_comment_task(session, task=task, adapter=MockPlatformAdapter(), snapshot_root=tmp_path)

    assert task.status == TaskStatus.RETRY.value


class ReversedCommentAdapter(MockPlatformAdapter):
    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        page = super().list_comments(platform_content_id, cursor=cursor, limit=limit)
        return CommentPage(
            platform_content_id=page.platform_content_id,
            items=tuple(reversed(page.items)),
            cursor=page.cursor,
        )


class FailingCommentAdapter(MockPlatformAdapter):
    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        raise RuntimeError("comments unavailable")


def _seed_content(session: Session, adapter: MockPlatformAdapter) -> None:
    ingest_content(session, adapter.get_content("note-ai-001"))
