from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from collectors import CollectedComment, CommentPage, PlatformAdapter
from scheduler import TaskStatus, claim_next_task, complete_task, fail_task, mark_partial
from storage import ingest_comment, save_json_snapshot
from storage.models import CollectionTask, Content


COMMENT_TASK_TYPES = frozenset({"comments", "collect_comments", "comment_collection"})
DEFAULT_COMMENT_LIMIT = 20


class CommentCollectionError(ValueError):
    """Raised when a comment collection task is malformed."""


def run_next_comment_task(
    session: Session,
    *,
    adapter: PlatformAdapter,
    worker_id: str,
    snapshot_root: str | Path = "snapshots",
    default_limit: int = DEFAULT_COMMENT_LIMIT,
) -> CollectionTask | None:
    task = claim_next_task(session, worker_id=worker_id)
    if task is None:
        return None

    if task.task_type not in COMMENT_TASK_TYPES:
        fail_task(session, task.id, error=f"unsupported task type: {task.task_type}")
        raise CommentCollectionError(f"unsupported task type: {task.task_type}")

    return run_comment_task(
        session,
        task=task,
        adapter=adapter,
        snapshot_root=snapshot_root,
        default_limit=default_limit,
    )


def run_comment_task(
    session: Session,
    *,
    task: CollectionTask,
    adapter: PlatformAdapter,
    snapshot_root: str | Path = "snapshots",
    default_limit: int = DEFAULT_COMMENT_LIMIT,
) -> CollectionTask:
    try:
        _validate_task(task, adapter=adapter)
        platform_content_id = _platform_content_id(task)
        content = _load_content(session, task.platform, platform_content_id)
        cursor = _input_cursor(task)
        limit = _input_limit(task, default_limit=default_limit)

        page = adapter.list_comments(platform_content_id, cursor=cursor, limit=limit)
        _validate_page(page, task=task, platform_content_id=platform_content_id)
        for comment in _parent_first(page.items):
            ingest_comment(session, comment)

        save_json_snapshot(
            session,
            entity_type="content",
            entity_id=content.id,
            snapshot_type="comments_page",
            payload=_snapshot_payload(
                task=task,
                page=page,
                request_cursor=cursor,
                limit=limit,
            ),
            snapshot_root=snapshot_root,
        )

        task.cursor_json = _cursor_payload(page=page, limit=limit)
        if page.cursor.has_more:
            return mark_partial(session, task.id, cursor_json=task.cursor_json)
        return complete_task(session, task.id)
    except Exception as exc:
        if task.status == TaskStatus.RUNNING.value:
            fail_task(session, task.id, error=str(exc))
        raise


def _validate_task(task: CollectionTask, *, adapter: PlatformAdapter) -> None:
    if task.status != TaskStatus.RUNNING.value:
        raise CommentCollectionError(f"comment task must be running, got {task.status}")
    if task.task_type not in COMMENT_TASK_TYPES:
        raise CommentCollectionError(f"unsupported task type: {task.task_type}")
    if task.platform != adapter.platform:
        raise CommentCollectionError(f"task platform {task.platform} does not match adapter platform {adapter.platform}")
    _platform_content_id(task)


def _platform_content_id(task: CollectionTask) -> str:
    if task.target_id:
        return task.target_id

    payload_json = task.payload_json or {}
    platform_content_id = payload_json.get("platform_content_id")
    if platform_content_id:
        return str(platform_content_id)

    cursor_json = task.cursor_json or {}
    cursor_platform_content_id = cursor_json.get("platform_content_id")
    if cursor_platform_content_id:
        return str(cursor_platform_content_id)

    raise CommentCollectionError("comment task requires target_id or payload_json.platform_content_id")


def _load_content(session: Session, platform: str, platform_content_id: str) -> Content:
    content = session.scalar(
        select(Content).where(
            Content.platform == platform,
            Content.platform_content_id == platform_content_id,
        )
    )
    if content is None:
        raise CommentCollectionError(f"content {platform}:{platform_content_id} must exist before collecting comments")
    if content.id is None:
        session.add(content)
        session.flush()
    return content


def _input_cursor(task: CollectionTask) -> str | None:
    cursor_json = task.cursor_json or {}
    cursor = cursor_json.get("next_cursor")
    if cursor is None:
        return None
    return str(cursor)


def _input_limit(task: CollectionTask, *, default_limit: int) -> int:
    payload_json = task.payload_json or {}
    cursor_json = task.cursor_json or {}
    raw_limit = payload_json.get("limit", cursor_json.get("limit", default_limit))
    limit = int(raw_limit)
    if limit < 1:
        raise CommentCollectionError("comment limit must be greater than 0")
    return limit


def _validate_page(page: CommentPage, *, task: CollectionTask, platform_content_id: str) -> None:
    if page.platform_content_id != platform_content_id:
        raise CommentCollectionError(
            f"adapter returned comments for {page.platform_content_id} when {platform_content_id} was requested"
        )
    for comment in page.items:
        if comment.platform != task.platform:
            raise CommentCollectionError(
                f"comment platform {comment.platform} does not match task platform {task.platform}"
            )
        if comment.platform_content_id != platform_content_id:
            raise CommentCollectionError(
                f"comment {comment.platform_comment_id} belongs to {comment.platform_content_id}, "
                f"expected {platform_content_id}"
            )


def _parent_first(comments: tuple[CollectedComment, ...]) -> list[CollectedComment]:
    by_id = {comment.platform_comment_id: comment for comment in comments}
    ordered: list[CollectedComment] = []
    visited: set[str] = set()

    def visit(comment: CollectedComment) -> None:
        if comment.platform_comment_id in visited:
            return
        if comment.parent_platform_comment_id is not None:
            parent = by_id.get(comment.parent_platform_comment_id)
            if parent is not None:
                visit(parent)
        ordered.append(comment)
        visited.add(comment.platform_comment_id)

    for comment in comments:
        visit(comment)
    return ordered


def _cursor_payload(*, page: CommentPage, limit: int) -> dict[str, Any]:
    return {
        "next_cursor": page.cursor.next_cursor,
        "has_more": page.cursor.has_more,
        "limit": limit,
        "platform_content_id": page.platform_content_id,
    }


def _snapshot_payload(
    *,
    task: CollectionTask,
    page: CommentPage,
    request_cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "task": {
            "platform": task.platform,
            "task_type": task.task_type,
            "target_id": task.target_id,
        },
        "request": {
            "platform_content_id": page.platform_content_id,
            "cursor": request_cursor,
            "limit": limit,
        },
        "response": page,
    }
