from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scheduler import create_task
from storage.database import get_session
from storage.models import CollectionTask, DiscoveryRelation, Query as StoredQuery

router = APIRouter(prefix="/queries", tags=["queries"])

SessionDep = Annotated[Session, Depends(get_session)]


class QueryCreate(BaseModel):
    query_text: str
    platform: str
    query_type: str
    status: str = "active"
    priority: int = 0
    source: str | None = None
    semantic_cluster_id: int | None = None
    next_run_at: datetime | None = None


class QueryUpdate(BaseModel):
    query_text: str | None = None
    query_type: str | None = None
    status: str | None = None
    priority: int | None = None
    source: str | None = None
    next_run_at: datetime | None = None


class QueryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    query_text: str
    platform: str
    query_type: str
    status: str
    priority: int
    source: str | None
    semantic_cluster_id: int | None
    run_count: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CollectionTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    platform: str
    target_id: str | None
    query_id: int | None
    priority: int
    status: str
    scheduled_at: datetime
    payload_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class QueryStats(BaseModel):
    query_id: int
    run_count: int
    last_run_at: datetime | None
    next_run_at: datetime | None
    discovery_count: int
    task_count: int


def _get_query_or_404(session: Session, query_id: int) -> StoredQuery:
    stored_query = session.get(StoredQuery, query_id)
    if stored_query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    return stored_query


@router.post("", response_model=QueryRead, status_code=status.HTTP_201_CREATED)
def create_query(payload: QueryCreate, session: SessionDep) -> StoredQuery:
    stored_query = StoredQuery(**payload.model_dump())
    session.add(stored_query)
    session.commit()
    session.refresh(stored_query)
    return stored_query


@router.get("", response_model=list[QueryRead])
def list_queries(
    session: SessionDep,
    platform: Annotated[str | None, QueryParam()] = None,
    status_filter: Annotated[str | None, QueryParam(alias="status")] = None,
    query_type: Annotated[str | None, QueryParam()] = None,
) -> list[StoredQuery]:
    statement = select(StoredQuery).order_by(StoredQuery.id.asc())
    if platform is not None:
        statement = statement.where(StoredQuery.platform == platform)
    if status_filter is not None:
        statement = statement.where(StoredQuery.status == status_filter)
    if query_type is not None:
        statement = statement.where(StoredQuery.query_type == query_type)
    return list(session.scalars(statement).all())


@router.get("/{query_id}", response_model=QueryRead)
def get_query(query_id: int, session: SessionDep) -> StoredQuery:
    return _get_query_or_404(session, query_id)


@router.patch("/{query_id}", response_model=QueryRead)
def update_query(query_id: int, payload: QueryUpdate, session: SessionDep) -> StoredQuery:
    stored_query = _get_query_or_404(session, query_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(stored_query, field, value)

    session.commit()
    session.refresh(stored_query)
    return stored_query


@router.post("/{query_id}/start", response_model=QueryRead)
def start_query(query_id: int, session: SessionDep) -> StoredQuery:
    stored_query = _get_query_or_404(session, query_id)
    stored_query.status = "active"
    session.commit()
    session.refresh(stored_query)
    return stored_query


@router.post("/{query_id}/stop", response_model=QueryRead)
def stop_query(query_id: int, session: SessionDep) -> StoredQuery:
    stored_query = _get_query_or_404(session, query_id)
    stored_query.status = "paused"
    session.commit()
    session.refresh(stored_query)
    return stored_query


@router.post("/{query_id}/run", response_model=CollectionTaskRead, status_code=status.HTTP_201_CREATED)
def run_query(query_id: int, session: SessionDep) -> CollectionTask:
    stored_query = _get_query_or_404(session, query_id)
    task = create_task(
        session,
        task_type="search",
        platform=stored_query.platform,
        target_id=stored_query.query_text,
        query_id=stored_query.id,
        priority=stored_query.priority,
        payload_json={
            "query_id": stored_query.id,
            "query_text": stored_query.query_text,
            "query_type": stored_query.query_type,
        },
    )
    session.commit()
    session.refresh(task)
    return task


@router.get("/{query_id}/stats", response_model=QueryStats)
def get_query_stats(query_id: int, session: SessionDep) -> QueryStats:
    stored_query = _get_query_or_404(session, query_id)
    discovery_count = session.scalar(
        select(func.count(DiscoveryRelation.id)).where(DiscoveryRelation.query_id == query_id)
    )
    task_count = session.scalar(select(func.count(CollectionTask.id)).where(CollectionTask.query_id == query_id))

    return QueryStats(
        query_id=stored_query.id,
        run_count=stored_query.run_count,
        last_run_at=stored_query.last_run_at,
        next_run_at=stored_query.next_run_at,
        discovery_count=discovery_count or 0,
        task_count=task_count or 0,
    )
