from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.worker.resume import start_partial_task
from collectors import CollectedComment, CommentPage, PlatformAdapter
from intelligence.comment_budget import (
    BudgetDecisionAction,
    CommentBudgetConfig,
    CommentBudgetState,
    build_comment_identity,
    evaluate_comment_budget,
    summarize_comment_batch,
)
from scheduler import TaskStatus, claim_next_task, complete_task, fail_task, mark_partial
from storage import ingest_comment, save_json_snapshot
from storage.models import CollectionTask, Comment, Content


COMMENT_TASK_TYPES = frozenset({"comments", "collect_comments", "comment_collection"})
DEFAULT_COMMENT_LIMIT = 20
DYNAMIC_COMMENT_BUDGET_KEY = "comment_budget"


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


def resume_partial_comment_task(
    session: Session,
    *,
    task_id: int,
    adapter: PlatformAdapter,
    worker_id: str,
    snapshot_root: str | Path = "snapshots",
    default_limit: int = DEFAULT_COMMENT_LIMIT,
) -> CollectionTask:
    task = start_partial_task(
        session,
        task_id=task_id,
        worker_id=worker_id,
        allowed_task_types=COMMENT_TASK_TYPES,
    )
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
        budget_enabled = _dynamic_budget_enabled(task)
        budget_config = _budget_config(task) if budget_enabled else None
        budget_state = _budget_state(session, task=task, content_id=content.id) if budget_enabled else None
        if budget_enabled and budget_config is not None and budget_state is not None:
            if _budget_is_maxed_out(budget_state, config=budget_config):
                task.cursor_json = _maxed_out_cursor_payload(task=task, budget_state=budget_state, config=budget_config)
                return complete_task(session, task.id)
            limit = _bounded_budget_limit(limit, state=budget_state, config=budget_config)
        if budget_enabled and not _has_explicit_limit(task):
            limit = budget_config.batch_size
            if budget_state is not None:
                limit = _bounded_budget_limit(limit, state=budget_state, config=budget_config)

        page = adapter.list_comments(platform_content_id, cursor=cursor, limit=limit)
        _validate_page(page, task=task, platform_content_id=platform_content_id)
        budget_evaluation = None
        if budget_enabled:
            budget_evaluation = evaluate_comment_budget(
                (build_comment_identity(comment) for comment in page.items),
                state=budget_state,
                config=budget_config,
                high_value_source=_is_high_value_source(task),
            )
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

        task.cursor_json = _cursor_payload(
            page=page,
            limit=limit,
            budget_state=budget_evaluation.state if budget_evaluation else None,
            budget_decision=budget_evaluation.decision.to_dict() if budget_evaluation else None,
        )
        if budget_evaluation is not None and budget_evaluation.decision.action != BudgetDecisionAction.CONTINUE:
            return complete_task(session, task.id)
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


def _has_explicit_limit(task: CollectionTask) -> bool:
    payload_json = task.payload_json or {}
    cursor_json = task.cursor_json or {}
    return "limit" in payload_json or "limit" in cursor_json


def _dynamic_budget_enabled(task: CollectionTask) -> bool:
    payload_json = task.payload_json or {}
    cursor_json = task.cursor_json or {}
    return bool(payload_json.get("dynamic_budget") or payload_json.get("comment_budget") or cursor_json.get(DYNAMIC_COMMENT_BUDGET_KEY))


def _is_high_value_source(task: CollectionTask) -> bool:
    payload_json = task.payload_json or {}
    return bool(payload_json.get("high_value_source") or payload_json.get("high_value_comment_section"))


def _budget_config(task: CollectionTask) -> CommentBudgetConfig:
    payload_json = task.payload_json or {}
    raw_config = payload_json.get("budget_config") or {}
    if not isinstance(raw_config, dict):
        raise CommentCollectionError("budget_config must be an object")
    default_config = CommentBudgetConfig()
    return CommentBudgetConfig(
        batch_size=int(raw_config.get("batch_size", default_config.batch_size)),
        max_parent_comments=int(raw_config.get("max_parent_comments", default_config.max_parent_comments)),
        max_total_comments=int(raw_config.get("max_total_comments", default_config.max_total_comments)),
        low_information_batches_to_stop=int(
            raw_config.get(
                "low_information_batches_to_stop",
                default_config.low_information_batches_to_stop,
            )
        ),
        min_new_user_rate=float(raw_config.get("min_new_user_rate", default_config.min_new_user_rate)),
        min_new_expression_rate=float(
            raw_config.get("min_new_expression_rate", default_config.min_new_expression_rate)
        ),
        min_valid_text_rate=float(raw_config.get("min_valid_text_rate", default_config.min_valid_text_rate)),
        max_duplicate_rate=float(raw_config.get("max_duplicate_rate", default_config.max_duplicate_rate)),
        min_information_score=float(raw_config.get("min_information_score", default_config.min_information_score)),
        high_value_min_information_score=float(
            raw_config.get("high_value_min_information_score", default_config.high_value_min_information_score)
        ),
    )


def _budget_state(session: Session, *, task: CollectionTask, content_id: int) -> CommentBudgetState:
    cursor_state = CommentBudgetState.from_dict((task.cursor_json or {}).get(DYNAMIC_COMMENT_BUDGET_KEY))
    if cursor_state.total_comment_count > 0 or cursor_state.metrics_history:
        return cursor_state

    existing_comments = session.scalars(select(Comment).where(Comment.content_id == content_id)).all()
    _, state = summarize_comment_batch(build_comment_identity(comment) for comment in existing_comments)
    return CommentBudgetState(
        seen_comment_ids=state.seen_comment_ids,
        seen_author_ids=state.seen_author_ids,
        seen_expressions=state.seen_expressions,
        seen_regions=state.seen_regions,
        seen_institutions=state.seen_institutions,
        parent_comment_count=state.parent_comment_count,
        total_comment_count=state.total_comment_count,
        low_information_streak=0,
        metrics_history=(),
    )


def _budget_is_maxed_out(state: CommentBudgetState, *, config: CommentBudgetConfig) -> bool:
    return state.parent_comment_count >= config.max_parent_comments or state.total_comment_count >= config.max_total_comments


def _bounded_budget_limit(limit: int, *, state: CommentBudgetState, config: CommentBudgetConfig) -> int:
    remaining_parent = config.max_parent_comments - state.parent_comment_count
    remaining_total = config.max_total_comments - state.total_comment_count
    return max(min(limit, remaining_parent, remaining_total), 0)


def _maxed_out_cursor_payload(
    *,
    task: CollectionTask,
    budget_state: CommentBudgetState,
    config: CommentBudgetConfig,
) -> dict[str, Any]:
    cursor_json = dict(task.cursor_json or {})
    cursor_json[DYNAMIC_COMMENT_BUDGET_KEY] = budget_state.to_dict()
    reason = (
        "max_parent_comments_reached"
        if budget_state.parent_comment_count >= config.max_parent_comments
        else "max_total_comments_reached"
    )
    cursor_json["comment_budget_decision"] = {
        "action": BudgetDecisionAction.MAXED_OUT.value,
        "reason": reason,
        "next_batch_size": 0,
        "low_information_streak": budget_state.low_information_streak,
    }
    return cursor_json


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


def _cursor_payload(
    *,
    page: CommentPage,
    limit: int,
    budget_state: CommentBudgetState | None = None,
    budget_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "next_cursor": page.cursor.next_cursor,
        "has_more": page.cursor.has_more,
        "limit": limit,
        "platform_content_id": page.platform_content_id,
    }
    if budget_state is not None:
        payload[DYNAMIC_COMMENT_BUDGET_KEY] = budget_state.to_dict()
    if budget_decision is not None:
        payload["comment_budget_decision"] = budget_decision
    return payload


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
