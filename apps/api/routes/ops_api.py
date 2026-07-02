from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query as QueryParam, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from apps.api.dashboard_metrics import build_database_dashboard_response
from collectors.mediacrawler.adapter import MediaCrawlerConfig
from collectors.xiaohongshu.browser import XiaohongshuBrowserConfig
from scheduler import (
    InvalidTaskTransition,
    TaskStatus,
    cancel_task,
    create_task,
    recover_timed_out_tasks,
    schedule_retry,
)
from storage.database import get_session
from storage.models import (
    CollectionEvent,
    CollectionTask,
    Comment,
    Content,
    DiscoveryRelation,
    PublicProfile,
    Query as StoredQuery,
    Snapshot,
    WorkerHeartbeat,
)

router = APIRouter(prefix="/ops/api", tags=["ops"])
SessionDep = Annotated[Session, Depends(get_session)]


class TaskCreatePayload(BaseModel):
    query_text: str | None = None
    query_id: int | None = None
    task_type: str = "search"
    platform: str = "xhs"
    target_id: str | None = None
    priority: int = 0
    limit: int = Field(default=20, ge=1, le=200)


class PriorityPayload(BaseModel):
    priority: int


class QueryCreatePayload(BaseModel):
    query_text: str
    platform: str = "xhs"
    query_type: str = "seed"
    priority: int = 0


class QueryPriorityPayload(BaseModel):
    priority: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_ops_token(x_ops_token: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("OPS_TOKEN", "")
    if expected and x_ops_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OPS_TOKEN")


WriteAuth = Annotated[None, Depends(_require_ops_token)]


@router.get("/system")
def system_status(session: SessionDep) -> dict[str, Any]:
    now = _utc_now()
    dashboard = build_database_dashboard_response(session)
    media_config = MediaCrawlerConfig.from_env()
    xhs_config = XiaohongshuBrowserConfig.from_env()
    media_profile_exists = media_config.persistent_profile_dir.exists()
    latest_success = session.scalar(
        select(CollectionTask.finished_at)
        .where(CollectionTask.status == TaskStatus.COMPLETED.value)
        .order_by(CollectionTask.finished_at.desc().nullslast())
        .limit(1)
    )
    latest_failure = session.scalar(
        select(CollectionTask.finished_at)
        .where(CollectionTask.status == TaskStatus.FAILED.value)
        .order_by(CollectionTask.finished_at.desc().nullslast())
        .limit(1)
    )
    online_workers = _online_worker_count(session, now=now)
    return {
        "generated_at": now.isoformat(),
        "api": _status("正常", "API process is responding"),
        "postgresql": _status("正常", "Database query succeeded"),
        "worker_online_count": online_workers,
        "mediacrawler": _status("正常" if media_config.home.exists() else "异常", str(media_config.home)),
        "playwright": _status("正常" if xhs_config.profile_dir.exists() else "警告", str(xhs_config.profile_dir)),
        "xiaohongshu_login": _status(
            "正常" if media_profile_exists else "警告",
            f"MediaCrawler persistent profile {'exists' if media_profile_exists else 'is missing'}: {media_config.persistent_profile_dir}",
        ),
        "feishu": _status("正常" if os.getenv("FEISHU_WEBHOOK_URL") else "未配置", "Webhook configured" if os.getenv("FEISHU_WEBHOOK_URL") else "No webhook"),
        "latest_successful_collection_at": latest_success.isoformat() if latest_success else None,
        "latest_failed_collection_at": latest_failure.isoformat() if latest_failure else None,
        "dashboard": dashboard,
    }


@router.get("/workers")
def workers(session: SessionDep) -> dict[str, Any]:
    now = _utc_now()
    rows = session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.worker_id.asc())).all()
    return {
        "items": [
            {
                "worker_id": row.worker_id,
                "online": _is_online(row, now=now),
                "status": row.status,
                "current_task_id": row.current_task_id,
                "started_at": _iso(row.started_at),
                "last_heartbeat_at": _iso(row.last_heartbeat_at),
                "completed_task_count": row.completed_task_count,
                "failed_task_count": row.failed_task_count,
                "last_error": row.last_error,
                "metadata": row.metadata_json or {},
            }
            for row in rows
        ]
    }


@router.get("/tasks")
def list_tasks(
    session: SessionDep,
    status_filter: Annotated[str | None, QueryParam(alias="status")] = None,
    task_type: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    statement = select(CollectionTask, StoredQuery.query_text).outerjoin(StoredQuery, StoredQuery.id == CollectionTask.query_id)
    count_statement = select(func.count(CollectionTask.id)).select_from(CollectionTask).outerjoin(StoredQuery, StoredQuery.id == CollectionTask.query_id)
    filters = []
    if status_filter:
        filters.append(CollectionTask.status == status_filter)
    if task_type:
        filters.append(CollectionTask.task_type == task_type)
    if q:
        like = f"%{q}%"
        filters.append(or_(StoredQuery.query_text.like(like), CollectionTask.target_id.like(like)))
    for item in filters:
        statement = statement.where(item)
        count_statement = count_statement.where(item)
    rows = session.execute(
        statement.order_by(CollectionTask.priority.desc(), CollectionTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "total": session.scalar(count_statement) or 0,
        "page": page,
        "page_size": page_size,
        "items": [_task_dict(task, query_text=query_text) for task, query_text in rows],
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: int, session: SessionDep) -> dict[str, Any]:
    task = _get_task(session, task_id)
    query_text = task.query.query_text if task.query else None
    return _task_dict(task, query_text=query_text, include_payload=True)


@router.post("/tasks")
def create_ops_task(payload: TaskCreatePayload, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    query = None
    if payload.query_id is not None:
        query = session.get(StoredQuery, payload.query_id)
        if query is None:
            raise HTTPException(status_code=404, detail="Query not found")
    elif payload.query_text:
        query = _get_or_create_query(session, payload)
    existing = _find_duplicate_open_task(session, payload=payload, query=query)
    if existing is not None:
        return {"created": False, "task": _task_dict(existing, query_text=query.query_text if query else None)}
    task = create_task(
        session,
        task_type=payload.task_type,
        platform=payload.platform,
        target_id=payload.target_id or (query.query_text if query else None),
        query_id=query.id if query else None,
        priority=payload.priority,
        payload_json={"limit": payload.limit, "source": "ops_console"},
    )
    session.commit()
    session.refresh(task)
    return {"created": True, "task": _task_dict(task, query_text=query.query_text if query else None)}


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    return _transition(session, task_id, lambda task: schedule_retry(session, task.id, error="manual retry from ops"))


@router.post("/tasks/{task_id}/resume")
def resume_task(task_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    task = _get_task(session, task_id)
    if task.status != TaskStatus.PARTIAL.value:
        raise HTTPException(status_code=409, detail=f"Cannot resume task from status {task.status}")
    task.status = TaskStatus.RETRY.value
    task.scheduled_at = _utc_now()
    task.worker_id = None
    task.started_at = None
    task.finished_at = None
    session.commit()
    session.refresh(task)
    return _task_dict(task, query_text=task.query.query_text if task.query else None)


@router.post("/tasks/{task_id}/cancel")
def cancel_ops_task(task_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    return _transition(session, task_id, lambda task: cancel_task(session, task.id, reason="manual cancel from ops"))


@router.post("/tasks/{task_id}/run-once")
def run_once_task(task_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    task = _get_task(session, task_id)
    if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"Cannot run task from status {task.status}")
    task.status = TaskStatus.RETRY.value
    task.scheduled_at = _utc_now()
    task.worker_id = None
    task.started_at = None
    task.finished_at = None
    task.last_error = "manual run-once requested from ops"
    session.commit()
    session.refresh(task)
    return _task_dict(task, query_text=task.query.query_text if task.query else None)


@router.post("/tasks/{task_id}/priority")
def set_priority(task_id: int, payload: PriorityPayload, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    task = _get_task(session, task_id)
    task.priority = payload.priority
    session.commit()
    session.refresh(task)
    return _task_dict(task, query_text=task.query.query_text if task.query else None)


@router.get("/queries")
def ops_queries(session: SessionDep) -> dict[str, Any]:
    rows = session.scalars(select(StoredQuery).order_by(StoredQuery.priority.desc(), StoredQuery.id.asc())).all()
    items = []
    for query in rows:
        task_count = session.scalar(select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query.id)) or 0
        failed = session.scalar(
            select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query.id, CollectionTask.status == TaskStatus.FAILED.value)
        ) or 0
        completed = session.scalar(
            select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query.id, CollectionTask.status == TaskStatus.COMPLETED.value)
        ) or 0
        items.append(
            {
                "id": query.id,
                "query_text": query.query_text,
                "platform": query.platform,
                "query_type": query.query_type,
                "status": query.status,
                "priority": query.priority,
                "last_run_at": _iso(query.last_run_at),
                "success_rate": completed / task_count if task_count else None,
                "failure_rate": failed / task_count if task_count else None,
                "output_count": session.scalar(select(func.count(DiscoveryRelation.id)).where(DiscoveryRelation.query_id == query.id)) or 0,
            }
        )
    return {"items": items}


@router.post("/queries")
def create_ops_query(payload: QueryCreatePayload, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    existing = session.scalar(select(StoredQuery).where(StoredQuery.platform == payload.platform, StoredQuery.query_text == payload.query_text))
    if existing is not None:
        return {"created": False, "query": _query_dict(existing)}
    query = StoredQuery(**payload.model_dump(), status="active", source="ops_console")
    session.add(query)
    session.commit()
    session.refresh(query)
    return {"created": True, "query": _query_dict(query)}


@router.post("/queries/{query_id}/enable")
def enable_query(query_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    query = _get_query(session, query_id)
    query.status = "active"
    session.commit()
    return _query_dict(query)


@router.post("/queries/{query_id}/disable")
def disable_query(query_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    query = _get_query(session, query_id)
    query.status = "paused"
    session.commit()
    return _query_dict(query)


@router.post("/queries/{query_id}/priority")
def set_query_priority(query_id: int, payload: QueryPriorityPayload, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    query = _get_query(session, query_id)
    query.priority = payload.priority
    session.commit()
    return _query_dict(query)


@router.post("/queries/{query_id}/tasks")
def create_query_task(query_id: int, session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    query = _get_query(session, query_id)
    existing = _find_duplicate_open_task(session, payload=TaskCreatePayload(query_id=query.id, priority=query.priority), query=query)
    if existing:
        return {"created": False, "task": _task_dict(existing, query_text=query.query_text)}
    task = create_task(
        session,
        task_type="search",
        platform=query.platform,
        target_id=query.query_text,
        query_id=query.id,
        priority=query.priority,
        payload_json={"limit": 20, "source": "ops_console"},
    )
    session.commit()
    session.refresh(task)
    return {"created": True, "task": _task_dict(task, query_text=query.query_text)}


@router.get("/recent")
def recent_results(session: SessionDep) -> dict[str, Any]:
    contents = session.scalars(select(Content).order_by(Content.last_seen_at.desc()).limit(30)).all()
    comments = session.scalars(select(Comment).order_by(Comment.last_seen_at.desc()).limit(30)).all()
    profiles = session.scalars(select(PublicProfile).order_by(PublicProfile.last_seen_at.desc()).limit(30)).all()
    return {
        "contents": [_content_dict(item) for item in contents],
        "comments": [_comment_dict(item) for item in comments],
        "profiles": [_profile_dict(item) for item in profiles],
    }


@router.get("/errors")
def errors(session: SessionDep) -> dict[str, Any]:
    tasks = session.scalars(
        select(CollectionTask)
        .where(CollectionTask.last_error.is_not(None))
        .order_by(func.coalesce(CollectionTask.finished_at, CollectionTask.started_at, CollectionTask.updated_at).desc())
        .limit(50)
    ).all()
    snapshots = session.scalars(select(Snapshot).order_by(Snapshot.captured_at.desc()).limit(50)).all()
    return {
        "items": [
            {
                "task_id": task.id,
                "worker_id": task.worker_id,
                "error_type": task.status,
                "error_summary": (task.last_error or "")[:180],
                "full_error": task.last_error,
                "time": _iso(task.finished_at or task.started_at or task.updated_at),
                "retry_count": task.attempt_count,
                "snapshot_paths": [snapshot.object_storage_path for snapshot in snapshots[:5]],
                "mediacrawler_log_dir": os.getenv("MEDIACRAWLER_LOG_DIR", ".runtime/mediacrawler-logs"),
            }
            for task in tasks
        ]
    }


@router.get("/snapshots/{snapshot_id}")
def open_snapshot(snapshot_id: int, session: SessionDep) -> FileResponse:
    snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    path = Path(snapshot.object_storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Snapshot file not found")
    return FileResponse(path)


@router.get("/browser")
def browser_status() -> dict[str, Any]:
    media_config = MediaCrawlerConfig.from_env()
    xhs_config = XiaohongshuBrowserConfig.from_env()
    media_profile_exists = media_config.persistent_profile_dir.exists()
    return {
        "backend": os.getenv("WORKER_ADAPTER", "xiaohongshu"),
        "mediacrawler_available": media_config.home.exists() and media_config.python_executable.exists(),
        "playwright_profile_dir": str(xhs_config.profile_dir),
        "headless": xhs_config.headless,
        "login_status": "正常" if media_profile_exists else "警告",
        "last_login_check_at": None,
        "mediacrawler_recent_run_dir": _latest_path(media_config.output_root),
        "mediacrawler_persistent_profile_dir": str(media_config.persistent_profile_dir),
        "mediacrawler_persistent_profile_exists": media_profile_exists,
    }


@router.post("/browser/check-login")
def check_login(_: WriteAuth) -> dict[str, Any]:
    return {"status": "未配置", "message": "Manual login check is not automated in V0."}


@router.post("/browser/open-login")
def open_login(_: WriteAuth) -> dict[str, Any]:
    return {"status": "manual_required", "message": "Start a non-headless collector locally and complete QR login manually."}


@router.post("/worker/pause")
def pause_workers(session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    session.add(CollectionEvent(event_type="worker_pause_requested", entity_type="worker", entity_id=0, event_data={"source": "ops"}))
    session.commit()
    return {"status": "recorded"}


@router.post("/worker/resume")
def resume_workers(session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    session.add(CollectionEvent(event_type="worker_resume_requested", entity_type="worker", entity_id=0, event_data={"source": "ops"}))
    session.commit()
    return {"status": "recorded"}


@router.post("/worker/recover-timeouts")
def recover_timeouts(session: SessionDep, _: WriteAuth) -> dict[str, Any]:
    recovered = recover_timed_out_tasks(
        session,
        timeout_after=timedelta(minutes=int(os.getenv("WORKER_TASK_TIMEOUT_MINUTES", "20"))),
        error_message="manual timeout recovery from ops",
    )
    session.commit()
    return {"recovered_task_ids": [task.id for task in recovered]}


def _task_dict(task: CollectionTask, *, query_text: str | None, include_payload: bool = False) -> dict[str, Any]:
    payload = {
        "task_id": task.id,
        "task_type": task.task_type,
        "query": query_text,
        "target_id": task.target_id,
        "status": task.status,
        "priority": task.priority,
        "attempt_count": task.attempt_count,
        "worker_id": task.worker_id,
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "last_error": task.last_error,
    }
    if include_payload:
        payload["payload_json"] = task.payload_json
        payload["cursor_json"] = task.cursor_json
    return payload


def _query_dict(query: StoredQuery) -> dict[str, Any]:
    return {"id": query.id, "query_text": query.query_text, "platform": query.platform, "status": query.status, "priority": query.priority}


def _content_dict(item: Content) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "body_summary": (item.body_text or "")[:160],
        "author": item.author_profile.display_name if item.author_profile else None,
        "published_at": _iso(item.published_at),
        "like_count": item.like_count,
        "comment_count": item.comment_count,
        "collect_count": item.collect_count,
        "source_queries": [relation.query.query_text for relation in item.discovery_relations if relation.query],
        "first_seen_at": _iso(item.first_seen_at),
        "last_seen_at": _iso(item.last_seen_at),
        "url": item.url,
    }


def _comment_dict(item: Comment) -> dict[str, Any]:
    return {
        "id": item.id,
        "body_text": item.body_text,
        "content_title": item.content.title if item.content else None,
        "author": item.author_profile.display_name if item.author_profile else None,
        "region_text": item.author_profile.region_text if item.author_profile else None,
        "like_count": item.like_count,
        "reply_count": item.reply_count,
        "published_at": _iso(item.published_at),
    }


def _profile_dict(item: PublicProfile) -> dict[str, Any]:
    contact = item.public_contact_text or ""
    return {
        "id": item.id,
        "display_name": item.display_name,
        "platform_user_id": item.platform_user_id,
        "region_text": item.region_text,
        "bio": item.bio,
        "public_contact_text_masked": _mask_contact(contact),
        "public_contact_text": contact,
        "profile_url": item.profile_url,
        "first_seen_at": _iso(item.first_seen_at),
    }


def _transition(session: Session, task_id: int, action) -> dict[str, Any]:
    task = _get_task(session, task_id)
    try:
        task = action(task)
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(task)
    return _task_dict(task, query_text=task.query.query_text if task.query else None)


def _get_task(session: Session, task_id: int) -> CollectionTask:
    task = session.get(CollectionTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _get_query(session: Session, query_id: int) -> StoredQuery:
    query = session.get(StoredQuery, query_id)
    if query is None:
        raise HTTPException(status_code=404, detail="Query not found")
    return query


def _get_or_create_query(session: Session, payload: TaskCreatePayload) -> StoredQuery:
    query = session.scalar(select(StoredQuery).where(StoredQuery.platform == payload.platform, StoredQuery.query_text == payload.query_text))
    if query is None:
        query = StoredQuery(
            query_text=payload.query_text or "",
            platform=payload.platform,
            query_type="seed",
            status="active",
            priority=payload.priority,
            source="ops_console",
        )
        session.add(query)
        session.flush()
    return query


def _find_duplicate_open_task(session: Session, *, payload: TaskCreatePayload, query: StoredQuery | None) -> CollectionTask | None:
    statuses = (TaskStatus.PENDING.value, TaskStatus.RUNNING.value, TaskStatus.RETRY.value, TaskStatus.PARTIAL.value)
    statement = select(CollectionTask).where(CollectionTask.task_type == payload.task_type, CollectionTask.platform == payload.platform, CollectionTask.status.in_(statuses))
    if query is not None:
        statement = statement.where(CollectionTask.query_id == query.id)
    elif payload.target_id:
        statement = statement.where(CollectionTask.target_id == payload.target_id)
    return session.scalar(statement.order_by(CollectionTask.id.desc()).limit(1))


def _status(status_text: str, message: str) -> dict[str, str]:
    return {"status": status_text, "message": message}


def _online_worker_count(session: Session, *, now: datetime) -> int:
    return sum(1 for row in session.scalars(select(WorkerHeartbeat)).all() if _is_online(row, now=now))


def _is_online(row: WorkerHeartbeat, *, now: datetime) -> bool:
    last = row.last_heartbeat_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return now - last <= timedelta(seconds=30)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_path(root: Path) -> str | None:
    if not root.exists():
        return None
    paths = sorted((item for item in root.iterdir()), key=lambda item: item.stat().st_mtime, reverse=True)
    return str(paths[0]) if paths else None


def _mask_contact(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"
