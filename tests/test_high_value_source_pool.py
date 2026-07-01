from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.worker.source_pool import build_source_candidates_from_context, generate_high_value_sources
from collectors import CollectedComment, CollectedContent
from intelligence.source_pool import (
    HighValueSourcePool,
    SourceType,
    build_competitor_account_candidate,
    build_seed_account_candidate,
)


NOW = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)


def test_source_pool_creates_all_required_source_types() -> None:
    pool = HighValueSourcePool(now=NOW)

    content = pool.upsert(
        build_source_candidates_from_context(
            content=_content(),
            comments=(_comment("comment-1", "福州 PET 二刷求推荐机构，有没有试听课？", "user-parent-1"),),
        )[0]
    )
    account = pool.upsert(
        build_seed_account_candidate(
            platform="xhs",
            platform_user_id="seed-teacher-1",
            reason="seed account: exam information publisher",
            observed_at=NOW,
        )
    )
    competitor = pool.upsert(
        build_competitor_account_candidate(
            platform="xhs",
            platform_user_id="competitor-1",
            reason="competitor account: local English training brand",
            metadata={"brand": "local English"},
            observed_at=NOW,
        )
    )
    generated = generate_high_value_sources(
        pool=pool,
        content=_content(comment_count=42),
        comments=(
            _comment("comment-1", "福州 PET 二刷求推荐机构，有没有试听课？", "user-parent-1"),
            _comment("comment-2", "这家价格多少钱？", "user-parent-2"),
        ),
    )

    assert content.source_type == SourceType.CONTENT
    assert account.source_type == SourceType.SEED_ACCOUNT
    assert competitor.source_type == SourceType.COMPETITOR_ACCOUNT
    assert {source.source_type for source in generated} >= {
        SourceType.CONTENT,
        SourceType.ACCOUNT,
        SourceType.COMMENT_SECTION,
    }
    assert len(pool) == 7
    assert pool.get(SourceType.ACCOUNT, "xhs", "user-parent-1") is not None
    assert pool.get(SourceType.ACCOUNT, "xhs", "user-parent-2") is not None


def test_upsert_is_idempotent_and_merges_score_reason_and_metadata() -> None:
    pool = HighValueSourcePool(now=NOW)
    first = build_seed_account_candidate(
        platform="xhs",
        platform_user_id="seed-teacher-1",
        reason="seed account: exam information publisher",
        score=0.55,
        metadata={"origin": "manual_seed"},
        observed_at=NOW,
    )
    second = build_seed_account_candidate(
        platform="xhs",
        platform_user_id="seed-teacher-1",
        reason="seed account: produces parent questions",
        score=0.9,
        metadata={"owner": "ops"},
        observed_at=NOW + timedelta(hours=1),
    )

    pool.upsert(first)
    updated = pool.upsert(second)

    assert len(pool) == 1
    assert updated.score == 0.9
    assert updated.reason == "seed account: exam information publisher; seed account: produces parent questions"
    assert updated.metadata == {"origin": "manual_seed", "owner": "ops"}
    assert updated.tracking_interval == timedelta(hours=6)
    assert updated.next_check_at == NOW + timedelta(hours=7)


def test_tracking_interval_and_next_check_are_score_based() -> None:
    pool = HighValueSourcePool(now=NOW)
    high = pool.upsert(
        build_competitor_account_candidate(
            platform="xhs",
            platform_user_id="competitor-1",
            reason="competitor account",
            score=0.95,
            observed_at=NOW,
        )
    )
    low = pool.upsert(
        build_seed_account_candidate(
            platform="xhs",
            platform_user_id="seed-low",
            reason="low confidence seed",
            score=0.2,
            observed_at=NOW,
        )
    )

    assert high.tracking_interval == timedelta(hours=6)
    assert high.next_check_at == NOW + timedelta(hours=6)
    assert low.tracking_interval == timedelta(days=7)
    assert low.next_check_at == NOW + timedelta(days=7)
    assert pool.due_sources(at=NOW + timedelta(hours=6)) == [high]


def test_worker_builds_candidates_from_content_and_comment_signals() -> None:
    candidates = build_source_candidates_from_context(
        content=_content(comment_count=30),
        comments=(
            _comment("comment-1", "孩子 PET 压线没过，福州本地机构求推荐", "user-parent-1"),
            _comment("comment-2", "想问试听和价格", "user-parent-2"),
        ),
    )

    by_type = {candidate.source_type for candidate in candidates}
    assert by_type == {SourceType.CONTENT, SourceType.ACCOUNT, SourceType.COMMENT_SECTION}
    content = next(candidate for candidate in candidates if candidate.source_type == SourceType.CONTENT)
    assert content.platform == "xhs"
    assert content.source_id == "note-pet-001"
    assert content.score > 0.7
    assert "explicit_local_demand" in content.metadata["reason_signals"]
    assert "price_question" in content.metadata["reason_signals"]


def test_worker_generates_commenter_accounts_for_high_value_commenters() -> None:
    pool = HighValueSourcePool(now=NOW)

    sources = generate_high_value_sources(
        pool=pool,
        content=_content(body_text="普通 KET 经验分享", comment_count=5),
        comments=(
            _comment("comment-1", "厦门附近有没有机构试听？", "user-parent-1"),
            _comment("comment-2", "路过看看", "user-parent-2"),
        ),
    )

    commenter_source = pool.get(SourceType.ACCOUNT, "xhs", "user-parent-1")
    assert commenter_source is not None
    assert commenter_source.metadata["source_comment_id"] == "comment-1"
    assert all(source.reason for source in sources)
    assert all(source.metadata for source in sources)


def _content(
    *,
    body_text: str = "五年级 PET 二刷，福州本地机构哪家好？想先试听再看价格。",
    comment_count: int = 12,
) -> CollectedContent:
    return CollectedContent(
        platform="xhs",
        platform_content_id="note-pet-001",
        platform_author_id="author-1",
        content_type="note",
        title="PET 二刷求推荐",
        body_text=body_text,
        published_at=NOW,
        url="https://example.test/note-pet-001",
        region_text="福州",
        like_count=20,
        comment_count=comment_count,
        collect_count=4,
    )


def _comment(platform_comment_id: str, body_text: str, platform_author_id: str) -> CollectedComment:
    return CollectedComment(
        platform="xhs",
        platform_comment_id=platform_comment_id,
        platform_content_id="note-pet-001",
        platform_author_id=platform_author_id,
        parent_platform_comment_id=None,
        body_text=body_text,
        published_at=NOW,
        like_count=2,
        reply_count=0,
        region_text=None,
    )
