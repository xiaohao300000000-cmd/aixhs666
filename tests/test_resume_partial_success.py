from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import apps.worker.search_collection as search_collection
from apps.worker.comment_collection import resume_partial_comment_task, run_comment_task
from apps.worker.search_collection import resume_partial_search_task, run_search_task
from collectors import CommentPage, MockPlatformAdapter, SearchPage
from scheduler import TaskStatus, claim_next_task, create_task
from storage import ingest_content
from storage.database import Base
from storage.models import CollectionTask, Comment, Content, DiscoveryRelation, Query


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_resume_partial_search_task_continues_from_saved_cursor(
    session: Session,
    tmp_path: Path,
) -> None:
    query = _query(session, "ai-study")
    task = create_task(session, task_type="search", platform="xhs", query_id=query.id, payload_json={"limit": 1})

    first_adapter = TrackingSearchAdapter()
    claim_next_task(session, worker_id="worker-first")
    run_search_task(session, task=task, adapter=first_adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.PARTIAL.value
    assert first_adapter.search_calls == [("ai-study", None, 1)]
    assert claim_next_task(session, worker_id="worker-claim") is None

    resume_adapter = TrackingSearchAdapter()
    resume_partial_search_task(
        session,
        task_id=task.id,
        adapter=resume_adapter,
        worker_id="worker-resume",
        snapshot_root=tmp_path,
    )

    assert resume_adapter.search_calls == [("ai-study", "1", 1)]
    assert task.status == TaskStatus.COMPLETED.value
    assert task.cursor_json == {
        "next_cursor": None,
        "has_more": False,
        "limit": 1,
        "query_text": "ai-study",
    }
    assert _content_ids(session) == ["note-ai-001", "note-ai-002"]
    assert _discovery_count(session) == 2


def test_resume_partial_comment_task_continues_from_saved_cursor(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = TrackingCommentAdapter()
    _seed_content(session, adapter)
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"limit": 1},
    )

    claim_next_task(session, worker_id="worker-first")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert task.status == TaskStatus.PARTIAL.value
    assert adapter.comment_calls == [("note-ai-001", None, 1)]
    assert claim_next_task(session, worker_id="worker-claim") is None

    resume_adapter = TrackingCommentAdapter()
    resume_partial_comment_task(
        session,
        task_id=task.id,
        adapter=resume_adapter,
        worker_id="worker-resume",
        snapshot_root=tmp_path,
    )

    assert resume_adapter.comment_calls == [("note-ai-001", "1", 1)]
    assert task.status == TaskStatus.COMPLETED.value
    assert task.cursor_json == {
        "next_cursor": None,
        "has_more": False,
        "limit": 1,
        "platform_content_id": "note-ai-001",
    }
    assert _comment_ids(session) == ["comment-ai-001", "comment-ai-002"]
    reply = session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-002"))
    parent = session.scalar(select(Comment).where(Comment.platform_comment_id == "comment-ai-001"))
    assert reply is not None
    assert parent is not None
    assert reply.parent_comment_id == parent.id


def test_search_partial_success_failure_keeps_cursor_and_retry_is_idempotent(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = _query(session, "ai-study")
    task = create_task(
        session,
        task_type="search",
        platform="xhs",
        query_id=query.id,
        payload_json={"limit": 1},
        max_attempts=3,
    )

    claim_next_task(session, worker_id="worker-first")
    run_search_task(session, task=task, adapter=TrackingSearchAdapter(), snapshot_root=tmp_path)
    saved_cursor = dict(task.cursor_json or {})

    def fail_after_ingest(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("snapshot storage unavailable")

    monkeypatch.setattr(search_collection, "save_json_snapshot", fail_after_ingest)
    failing_adapter = TrackingSearchAdapter()
    with pytest.raises(RuntimeError, match="snapshot storage unavailable"):
        resume_partial_search_task(
            session,
            task_id=task.id,
            adapter=failing_adapter,
            worker_id="worker-resume",
            snapshot_root=tmp_path,
        )

    assert failing_adapter.search_calls == [("ai-study", "1", 1)]
    assert task.status == TaskStatus.RETRY.value
    assert task.cursor_json == saved_cursor
    assert task.last_error == "snapshot storage unavailable"
    assert _content_ids(session) == ["note-ai-001", "note-ai-002"]
    assert _discovery_count(session) == 2

    monkeypatch.undo()
    retry_adapter = TrackingSearchAdapter()
    retry_task = claim_next_task(session, worker_id="worker-retry")
    assert retry_task is task
    run_search_task(session, task=task, adapter=retry_adapter, snapshot_root=tmp_path)

    assert retry_adapter.search_calls == [("ai-study", "1", 1)]
    assert task.status == TaskStatus.COMPLETED.value
    assert _content_ids(session) == ["note-ai-001", "note-ai-002"]
    assert _discovery_count(session) == 2


def test_comment_partial_resume_retry_is_idempotent_and_completes(
    session: Session,
    tmp_path: Path,
) -> None:
    adapter = TrackingCommentAdapter()
    _seed_content(session, adapter)
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"limit": 1},
        max_attempts=3,
    )

    claim_next_task(session, worker_id="worker-first")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)
    saved_cursor = dict(task.cursor_json or {})

    failing_adapter = FailingCommentOnCursorAdapter(fail_cursor="1")
    with pytest.raises(RuntimeError, match="comments page unavailable"):
        resume_partial_comment_task(
            session,
            task_id=task.id,
            adapter=failing_adapter,
            worker_id="worker-resume",
            snapshot_root=tmp_path,
        )

    assert failing_adapter.comment_calls == [("note-ai-001", "1", 1)]
    assert task.status == TaskStatus.RETRY.value
    assert task.cursor_json == saved_cursor
    assert _comment_ids(session) == ["comment-ai-001"]

    retry_adapter = TrackingCommentAdapter()
    retry_task = claim_next_task(session, worker_id="worker-retry")
    assert retry_task is task
    run_comment_task(session, task=task, adapter=retry_adapter, snapshot_root=tmp_path)
    run_again_task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"limit": 20},
    )
    claim_next_task(session, worker_id="worker-repeat")
    run_comment_task(session, task=run_again_task, adapter=TrackingCommentAdapter(), snapshot_root=tmp_path)

    assert retry_adapter.comment_calls == [("note-ai-001", "1", 1)]
    assert task.status == TaskStatus.COMPLETED.value
    assert _comment_ids(session) == ["comment-ai-001", "comment-ai-002"]


class TrackingSearchAdapter(MockPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.search_calls: list[tuple[str, str | None, int]] = []

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        self.search_calls.append((query_text, cursor, limit))
        return super().search(query_text, cursor=cursor, limit=limit)


class TrackingCommentAdapter(MockPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.comment_calls: list[tuple[str, str | None, int]] = []

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        self.comment_calls.append((platform_content_id, cursor, limit))
        return super().list_comments(platform_content_id, cursor=cursor, limit=limit)


class FailingCommentOnCursorAdapter(TrackingCommentAdapter):
    def __init__(self, *, fail_cursor: str) -> None:
        super().__init__()
        self.fail_cursor = fail_cursor

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        self.comment_calls.append((platform_content_id, cursor, limit))
        if cursor == self.fail_cursor:
            raise RuntimeError("comments page unavailable")
        return MockPlatformAdapter.list_comments(self, platform_content_id, cursor=cursor, limit=limit)


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


def _seed_content(session: Session, adapter: MockPlatformAdapter) -> None:
    ingest_content(session, adapter.get_content("note-ai-001"))


def _content_ids(session: Session) -> list[str]:
    return list(session.scalars(select(Content.platform_content_id).order_by(Content.platform_content_id)))


def _comment_ids(session: Session) -> list[str]:
    return list(session.scalars(select(Comment.platform_comment_id).order_by(Comment.platform_comment_id)))


def _discovery_count(session: Session) -> int:
    return len(session.scalars(select(DiscoveryRelation)).all())
