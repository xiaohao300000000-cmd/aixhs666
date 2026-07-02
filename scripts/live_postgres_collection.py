from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import storage.models  # noqa: F401
from scheduler import create_task
from sqlalchemy import func, select

from storage.database import SessionLocal
from storage.models import CollectionTask, Comment, Content, DiscoveryRelation, PublicProfile, Query, Snapshot


SEED_QUERIES = (
    "KET 没过怎么办",
    "PET 二刷",
    "孩子英语跟不上",
    "福州少儿英语机构",
    "英语培训机构避雷",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed and report live PostgreSQL collection runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_search = subparsers.add_parser("seed-search", help="Create seed queries and search tasks.")
    seed_search.add_argument("--limit", type=int, default=20)
    seed_search.add_argument("--priority", type=int, default=100)

    seed_comments = subparsers.add_parser("seed-comments", help="Create comment tasks for collected contents.")
    seed_comments.add_argument("--limit", type=int, default=3)
    seed_comments.add_argument("--priority", type=int, default=80)

    report = subparsers.add_parser("report", help="Write a sanitized live collection report.")
    report.add_argument("--output", default="orchestration/e2e/live_postgres_result.json")

    args = parser.parse_args()
    if args.command == "seed-search":
        payload = seed_search_tasks(limit=args.limit, priority=args.priority)
    elif args.command == "seed-comments":
        payload = seed_comment_tasks(limit=args.limit, priority=args.priority)
    else:
        payload = write_report(Path(args.output))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def seed_search_tasks(*, limit: int, priority: int) -> dict[str, Any]:
    created_task_ids: list[int] = []
    query_ids: list[int] = []
    with SessionLocal() as session:
        for query_text in SEED_QUERIES:
            query = _get_or_create_query(session, query_text)
            query_ids.append(query.id)
            task = create_task(
                session,
                task_type="search",
                platform="xhs",
                query_id=query.id,
                priority=priority,
                payload_json={"limit": limit, "source": "live_postgres_collection"},
                max_attempts=3,
            )
            created_task_ids.append(task.id)
        session.commit()
    return {"query_ids": query_ids, "created_search_task_ids": created_task_ids}


def seed_comment_tasks(*, limit: int, priority: int) -> dict[str, Any]:
    created_task_ids: list[int] = []
    with SessionLocal() as session:
        content_ids = list(session.scalars(select(Content.platform_content_id).where(Content.platform == "xhs")))
        existing = set(
            session.execute(
                select(CollectionTask.target_id, CollectionTask.status).where(
                    CollectionTask.task_type.in_(("comments", "collect_comments", "comment_collection")),
                    CollectionTask.platform == "xhs",
                )
            )
        )
        for platform_content_id in content_ids:
            if (platform_content_id, "pending") in existing or (platform_content_id, "running") in existing:
                continue
            task = create_task(
                session,
                task_type="comments",
                platform="xhs",
                target_id=platform_content_id,
                priority=priority,
                payload_json={"limit": limit, "source": "live_postgres_collection"},
                max_attempts=3,
            )
            created_task_ids.append(task.id)
        session.commit()
    return {"created_comment_task_ids": created_task_ids, "content_count": len(content_ids)}


def write_report(output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        status_counts = Counter(
            dict(session.execute(select(CollectionTask.status, func.count(CollectionTask.id)).group_by(CollectionTask.status)).all())
        )
        task_type_counts = Counter(
            dict(session.execute(select(CollectionTask.task_type, func.count(CollectionTask.id)).group_by(CollectionTask.task_type)).all())
        )
        duplicate_content_count = _duplicate_count(session, Content.platform_content_id)
        duplicate_comment_count = _duplicate_count(session, Comment.platform_comment_id)
        duplicate_profile_count = _duplicate_count(session, PublicProfile.platform_user_id)
        duplicate_relation_count = _duplicate_relation_count(session)
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "environment": "local_postgresql_homebrew",
            "counts": {
                "queries": session.scalar(select(func.count(Query.id))) or 0,
                "search_tasks": task_type_counts.get("search", 0),
                "comment_tasks": sum(task_type_counts.get(name, 0) for name in ("comments", "collect_comments", "comment_collection")),
                "contents": session.scalar(select(func.count(Content.id))) or 0,
                "comments": session.scalar(select(func.count(Comment.id))) or 0,
                "public_profiles": session.scalar(select(func.count(PublicProfile.id))) or 0,
                "discovery_relations": session.scalar(select(func.count(DiscoveryRelation.id))) or 0,
                "snapshots": session.scalar(select(func.count(Snapshot.id))) or 0,
                "collection_events": _collection_event_count(session),
                "duplicate_contents": duplicate_content_count,
                "duplicate_comments": duplicate_comment_count,
                "duplicate_public_profiles": duplicate_profile_count,
                "duplicate_discovery_relations": duplicate_relation_count,
            },
            "task_status": {
                "pending": status_counts.get("pending", 0),
                "running": status_counts.get("running", 0),
                "partial": status_counts.get("partial", 0),
                "retry": status_counts.get("retry", 0),
                "completed": status_counts.get("completed", 0),
                "failed": status_counts.get("failed", 0),
                "cancelled": status_counts.get("cancelled", 0),
            },
        }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def _get_or_create_query(session, query_text: str) -> Query:
    query = session.scalar(select(Query).where(Query.platform == "xhs", Query.query_text == query_text))
    if query is None:
        query = Query(
            query_text=query_text,
            platform="xhs",
            query_type="seed",
            status="active",
            priority=100,
            source="live_postgres_collection",
        )
        session.add(query)
        session.flush()
    return query


def _duplicate_count(session, column) -> int:
    subquery = select(column).group_by(column).having(func.count() > 1).subquery()
    return session.scalar(select(func.count()).select_from(subquery)) or 0


def _duplicate_relation_count(session) -> int:
    subquery = (
        select(DiscoveryRelation.query_id, DiscoveryRelation.content_id)
        .group_by(DiscoveryRelation.query_id, DiscoveryRelation.content_id)
        .having(func.count() > 1)
        .subquery()
    )
    return session.scalar(select(func.count()).select_from(subquery)) or 0


def _collection_event_count(session) -> int:
    from storage.models import CollectionEvent

    return session.scalar(select(func.count(CollectionEvent.id))) or 0


if __name__ == "__main__":
    main()
