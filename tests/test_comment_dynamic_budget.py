from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import storage.models  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.worker.comment_collection import run_comment_task
from collectors import CollectedComment, CommentPage, MockPlatformAdapter, PageCursor
from intelligence.comment_budget import (
    BudgetDecisionAction,
    CommentBudgetConfig,
    CommentIdentity,
    evaluate_comment_budget,
)
from scheduler import TaskStatus, claim_next_task, create_task
from storage import ingest_content
from storage.database import Base


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_comment_batch_metrics_count_newness_duplicates_regions_and_institutions() -> None:
    state = evaluate_comment_budget(
        [
            _identity("c0", "u0", "福州 PET 机构 怎么选", region_text="福州"),
        ]
    ).state

    result = evaluate_comment_budget(
        [
            _identity("c1", "u1", "厦门 英语机构 求推荐", region_text="厦门"),
            _identity("c1", "u1", "厦门 英语机构 求推荐", region_text="厦门"),
            _identity("c2", "u2", ""),
        ],
        state=state,
    )

    assert result.metrics.batch_size == 3
    assert result.metrics.new_user_rate == pytest.approx(2 / 3)
    assert result.metrics.new_expression_rate == pytest.approx(1 / 3)
    assert result.metrics.valid_text_rate == pytest.approx(2 / 3)
    assert result.metrics.duplicate_rate == pytest.approx(1 / 3)
    assert result.metrics.new_region_count == 1
    assert result.metrics.new_institution_count == 1


def test_budget_continues_when_information_is_still_growing() -> None:
    result = evaluate_comment_budget(
        [
            _identity("c1", "u1", "福州 KET 二刷 要不要找老师", region_text="福州"),
            _identity("c2", "u2", "想问 PET 暑假班 价格"),
        ]
    )

    assert result.decision.action == BudgetDecisionAction.CONTINUE
    assert result.decision.reason == "information_still_growing"
    assert result.decision.next_batch_size == 30


def test_budget_stops_after_two_consecutive_low_information_batches() -> None:
    first = evaluate_comment_budget([_identity("c1", "u1", "嗯")])
    second = evaluate_comment_budget([_identity("c2", "u1", "嗯")], state=first.state)

    assert first.decision.action == BudgetDecisionAction.CONTINUE
    assert first.decision.low_information_streak == 1
    assert second.decision.action == BudgetDecisionAction.STOP
    assert second.decision.reason == "consecutive_low_information_batches"


def test_high_value_comment_section_relaxes_continue_threshold() -> None:
    first = evaluate_comment_budget([_identity("c1", "u1", "嗯")])
    normal = evaluate_comment_budget(
        [_identity("c2", "u1", "还有 PET 暑假班吗")],
        state=first.state,
    )
    high_value = evaluate_comment_budget(
        [_identity("c2", "u1", "还有 PET 暑假班吗")],
        state=first.state,
        high_value_source=True,
    )

    assert normal.decision.action == BudgetDecisionAction.STOP
    assert high_value.decision.action == BudgetDecisionAction.CONTINUE
    assert high_value.decision.reason == "high_value_source_expanded"


def test_budget_enforces_parent_and_total_comment_limits() -> None:
    parent_limited = evaluate_comment_budget(
        [_identity("c1", "u1", "福州机构求推荐")],
        state=_state_with_counts(parent_count=499, total_count=499),
        config=CommentBudgetConfig(max_parent_comments=500, max_total_comments=1000),
    )
    total_limited = evaluate_comment_budget(
        [_identity("c1", "u1", "福州机构求推荐", is_reply=True)],
        state=_state_with_counts(parent_count=100, total_count=999),
        config=CommentBudgetConfig(max_parent_comments=500, max_total_comments=1000),
    )

    assert parent_limited.decision.action == BudgetDecisionAction.MAXED_OUT
    assert parent_limited.decision.reason == "max_parent_comments_reached"
    assert total_limited.decision.action == BudgetDecisionAction.MAXED_OUT
    assert total_limited.decision.reason == "max_total_comments_reached"


def test_worker_persists_dynamic_budget_state_and_uses_default_batch_size(session: Session, tmp_path: Path) -> None:
    adapter = DynamicCommentAdapter()
    ingest_content(session, adapter.get_content("note-ai-001"))
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"dynamic_budget": True},
    )

    claim_next_task(session, worker_id="worker-t12")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert adapter.requested_limits == [30]
    assert task.status == TaskStatus.PARTIAL.value
    assert task.cursor_json is not None
    assert task.cursor_json["comment_budget"]["total_comment_count"] == 2
    assert task.cursor_json["comment_budget_decision"]["action"] == "continue"
    assert task.cursor_json["comment_budget_decision"]["next_batch_size"] == 30


def test_worker_bounds_request_limit_by_remaining_dynamic_budget(session: Session, tmp_path: Path) -> None:
    adapter = DynamicCommentAdapter()
    ingest_content(session, adapter.get_content("note-ai-001"))
    task = create_task(
        session,
        task_type="comments",
        platform="xhs",
        target_id="note-ai-001",
        payload_json={"dynamic_budget": True},
        cursor_json={
            "next_cursor": "near-limit",
            "has_more": True,
            "platform_content_id": "note-ai-001",
            "comment_budget": {
                "parent_comment_count": 499,
                "total_comment_count": 499,
                "seen_comment_ids": [],
                "seen_author_ids": [],
                "seen_expressions": [],
                "seen_regions": [],
                "seen_institutions": [],
                "low_information_streak": 0,
                "metrics_history": [],
            },
        },
    )

    claim_next_task(session, worker_id="worker-t12")
    run_comment_task(session, task=task, adapter=adapter, snapshot_root=tmp_path)

    assert adapter.requested_limits == [1]
    assert task.status == TaskStatus.COMPLETED.value
    assert task.cursor_json is not None
    assert task.cursor_json["comment_budget_decision"]["action"] == "maxed_out"
    assert task.cursor_json["comment_budget_decision"]["reason"] == "max_parent_comments_reached"


class DynamicCommentAdapter(MockPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.requested_limits: list[int] = []

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        self.requested_limits.append(limit)
        items = (
            CollectedComment(
                platform="xhs",
                platform_comment_id="dynamic-comment-001",
                platform_content_id=platform_content_id,
                platform_author_id="user-dynamic-001",
                parent_platform_comment_id=None,
                body_text="福州 PET 二刷 暑假机构求推荐",
                published_at=datetime.now(timezone.utc),
                like_count=0,
                reply_count=0,
                region_text="福州",
            ),
            CollectedComment(
                platform="xhs",
                platform_comment_id="dynamic-comment-002",
                platform_content_id=platform_content_id,
                platform_author_id="user-dynamic-002",
                parent_platform_comment_id=None,
                body_text="厦门 英语老师 哪家适合五年级",
                published_at=datetime.now(timezone.utc),
                like_count=0,
                reply_count=0,
                region_text="厦门",
            ),
        )
        return CommentPage(
            platform_content_id=platform_content_id,
            items=items[:limit],
            cursor=PageCursor(next_cursor="next-page", has_more=True),
        )


def _identity(
    comment_id: str,
    author_id: str,
    text: str,
    *,
    region_text: str | None = None,
    is_reply: bool = False,
) -> CommentIdentity:
    return CommentIdentity(
        comment_id=comment_id,
        author_id=author_id,
        text=text,
        region_text=region_text,
        is_reply=is_reply,
    )


def _state_with_counts(*, parent_count: int, total_count: int):
    comments = [
        _identity(
            f"seed-{index}",
            f"user-{index}",
            f"seed text {index}",
            is_reply=index >= parent_count,
        )
        for index in range(total_count)
    ]
    return evaluate_comment_budget(comments).state
