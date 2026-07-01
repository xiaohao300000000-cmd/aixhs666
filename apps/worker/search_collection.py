from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from collectors import PlatformAdapter, SearchPage
from scheduler import TaskStatus, claim_next_task, complete_task, fail_task, mark_partial
from storage import ingest_search_results, save_json_snapshot
from storage.models import CollectionTask, Query


DEFAULT_SEARCH_LIMIT = 20


class SearchCollectionError(ValueError):
    """Raised when a search collection task is malformed."""


def run_next_search_task(
    session: Session,
    *,
    adapter: PlatformAdapter,
    worker_id: str,
    snapshot_root: str | Path = "snapshots",
    default_limit: int = DEFAULT_SEARCH_LIMIT,
) -> CollectionTask | None:
    task = claim_next_task(session, worker_id=worker_id)
    if task is None:
        return None

    if task.task_type != "search":
        fail_task(session, task.id, error=f"unsupported task type: {task.task_type}")
        raise SearchCollectionError(f"unsupported task type: {task.task_type}")

    return run_search_task(
        session,
        task=task,
        adapter=adapter,
        snapshot_root=snapshot_root,
        default_limit=default_limit,
    )


def run_search_task(
    session: Session,
    *,
    task: CollectionTask,
    adapter: PlatformAdapter,
    snapshot_root: str | Path = "snapshots",
    default_limit: int = DEFAULT_SEARCH_LIMIT,
) -> CollectionTask:
    try:
        _validate_task(task, adapter=adapter)
        query = _load_query(session, task)
        cursor = _input_cursor(task)
        limit = _input_limit(task, default_limit=default_limit)

        page = adapter.search(query.query_text, cursor=cursor, limit=limit)
        ingest_search_results(session, query, page.items)
        save_json_snapshot(
            session,
            entity_type="query",
            entity_id=query.id,
            snapshot_type="search_page",
            payload=_snapshot_payload(task=task, query=query, page=page, request_cursor=cursor, limit=limit),
            snapshot_root=snapshot_root,
        )

        task.cursor_json = _cursor_payload(page=page, query_text=query.query_text, limit=limit)
        if page.cursor.has_more:
            return mark_partial(session, task.id, cursor_json=task.cursor_json)
        return complete_task(session, task.id)
    except Exception as exc:
        if task.status == TaskStatus.RUNNING.value:
            fail_task(session, task.id, error=str(exc))
        raise


def _validate_task(task: CollectionTask, *, adapter: PlatformAdapter) -> None:
    if task.status != TaskStatus.RUNNING.value:
        raise SearchCollectionError(f"search task must be running, got {task.status}")
    if task.task_type != "search":
        raise SearchCollectionError(f"unsupported task type: {task.task_type}")
    if task.platform != adapter.platform:
        raise SearchCollectionError(f"task platform {task.platform} does not match adapter platform {adapter.platform}")
    if task.query_id is None:
        raise SearchCollectionError("search task requires query_id")


def _load_query(session: Session, task: CollectionTask) -> Query:
    query = session.get(Query, task.query_id)
    if query is None:
        raise SearchCollectionError(f"query {task.query_id} was not found")
    if query.platform != task.platform:
        raise SearchCollectionError(f"query platform {query.platform} does not match task platform {task.platform}")
    return query


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
        raise SearchCollectionError("search limit must be greater than 0")
    return limit


def _cursor_payload(*, page: SearchPage, query_text: str, limit: int) -> dict[str, Any]:
    return {
        "next_cursor": page.cursor.next_cursor,
        "has_more": page.cursor.has_more,
        "limit": limit,
        "query_text": query_text,
    }


def _snapshot_payload(
    *,
    task: CollectionTask,
    query: Query,
    page: SearchPage,
    request_cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    return {
        "task": {
            "platform": task.platform,
            "task_type": task.task_type,
        },
        "query": {
            "id": query.id,
            "query_text": query.query_text,
            "platform": query.platform,
        },
        "request": {
            "cursor": request_cursor,
            "limit": limit,
        },
        "response": page,
    }
