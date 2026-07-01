from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

from collectors.base import (
    CollectedComment,
    CollectedContent,
    CollectedProfile,
    CollectedSearchResult,
    CommentPage,
    PageCursor,
    SearchPage,
)


T = TypeVar("T")


class MockPlatformAdapter:
    """Deterministic in-memory adapter for collector boundary tests."""

    def __init__(self, *, platform: str = "xhs") -> None:
        self._platform = platform
        self._profiles = _build_profiles(platform)
        self._contents = _build_contents(platform)
        self._comments_by_content = _build_comments(platform)
        self._search_index = {
            "ai-study": ("note-ai-001", "note-ai-002"),
            "admissions": ("note-ai-001",),
            "regional-school": ("note-ai-002",),
        }

    @property
    def platform(self) -> str:
        return self._platform

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        content_ids = self._search_index.get(query_text.strip().casefold(), ())
        items, page_cursor, offset = _paginate(content_ids, cursor=cursor, limit=limit)
        result_page = (offset // limit) + 1
        results = tuple(
            self._to_search_result(
                self._contents[content_id],
                rank_position=offset + index + 1,
                result_page=result_page,
            )
            for index, content_id in enumerate(items)
        )
        return SearchPage(query_text=query_text, items=results, cursor=page_cursor)

    def get_content(self, platform_content_id: str) -> CollectedContent:
        try:
            return self._contents[platform_content_id]
        except KeyError as exc:
            raise KeyError(f"unknown mock content id: {platform_content_id}") from exc

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        comments = self._comments_by_content.get(platform_content_id)
        if comments is None:
            raise KeyError(f"unknown mock content id: {platform_content_id}")

        items, page_cursor, _offset = _paginate(comments, cursor=cursor, limit=limit)
        return CommentPage(platform_content_id=platform_content_id, items=items, cursor=page_cursor)

    def get_profile(self, platform_user_id: str) -> CollectedProfile:
        try:
            return self._profiles[platform_user_id]
        except KeyError as exc:
            raise KeyError(f"unknown mock profile id: {platform_user_id}") from exc

    def _to_search_result(
        self,
        content: CollectedContent,
        *,
        rank_position: int,
        result_page: int,
    ) -> CollectedSearchResult:
        return CollectedSearchResult(
            platform=content.platform,
            platform_content_id=content.platform_content_id,
            platform_author_id=content.platform_author_id,
            content_type=content.content_type,
            title=content.title,
            body_text=content.body_text,
            published_at=content.published_at,
            url=content.url,
            region_text=content.region_text,
            like_count=content.like_count,
            comment_count=content.comment_count,
            collect_count=content.collect_count,
            rank_position=rank_position,
            result_page=result_page,
        )


def _paginate(items: tuple[T, ...], *, cursor: str | None, limit: int) -> tuple[tuple[T, ...], PageCursor, int]:
    if limit < 1:
        raise ValueError("limit must be greater than 0")

    offset = 0 if cursor is None else _parse_cursor(cursor)
    selected = items[offset : offset + limit]
    next_offset = offset + limit
    has_more = next_offset < len(items)
    next_cursor = str(next_offset) if has_more else None
    return selected, PageCursor(next_cursor=next_cursor, has_more=has_more), offset


def _parse_cursor(cursor: str) -> int:
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise ValueError(f"invalid cursor: {cursor}") from exc

    if offset < 0:
        raise ValueError("cursor must be greater than or equal to 0")
    return offset


def _build_profiles(platform: str) -> dict[str, CollectedProfile]:
    profiles = (
        CollectedProfile(
            platform=platform,
            platform_user_id="user-author-001",
            display_name="AI Admissions Lab",
            profile_url="https://mock.xhs.local/users/user-author-001",
            bio="Mock profile for admissions content.",
            region_text="Shanghai",
            public_contact_text="contact@example.invalid",
        ),
        CollectedProfile(
            platform=platform,
            platform_user_id="user-parent-001",
            display_name="Parent Researcher",
            profile_url="https://mock.xhs.local/users/user-parent-001",
            bio="Tracks school application experiences.",
            region_text="Beijing",
            public_contact_text=None,
        ),
        CollectedProfile(
            platform=platform,
            platform_user_id="user-student-001",
            display_name="Student Planner",
            profile_url="https://mock.xhs.local/users/user-student-001",
            bio="Planning cross-region school visits.",
            region_text="Guangzhou",
            public_contact_text=None,
        ),
    )
    return {profile.platform_user_id: profile for profile in profiles}


def _build_contents(platform: str) -> dict[str, CollectedContent]:
    contents = (
        CollectedContent(
            platform=platform,
            platform_content_id="note-ai-001",
            platform_author_id="user-author-001",
            content_type="note",
            title="AI study planning checklist",
            body_text="A mock note about preparing applications with AI background projects.",
            published_at=datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
            url="https://mock.xhs.local/notes/note-ai-001",
            region_text="Shanghai",
            like_count=128,
            comment_count=2,
            collect_count=46,
            tags=("AI", "admissions", "planning"),
            image_urls=("https://mock.xhs.local/images/note-ai-001-cover.jpg",),
        ),
        CollectedContent(
            platform=platform,
            platform_content_id="note-ai-002",
            platform_author_id="user-author-001",
            content_type="note",
            title="Regional school visit notes",
            body_text="A mock note comparing school visit questions across regions.",
            published_at=datetime(2026, 1, 6, 15, 45, tzinfo=UTC),
            url="https://mock.xhs.local/notes/note-ai-002",
            region_text="Guangzhou",
            like_count=73,
            comment_count=0,
            collect_count=21,
            tags=("school-visit", "regional-school"),
            image_urls=("https://mock.xhs.local/images/note-ai-002-cover.jpg",),
        ),
    )
    return {content.platform_content_id: content for content in contents}


def _build_comments(platform: str) -> dict[str, tuple[CollectedComment, ...]]:
    return {
        "note-ai-001": (
            CollectedComment(
                platform=platform,
                platform_comment_id="comment-ai-001",
                platform_content_id="note-ai-001",
                platform_author_id="user-parent-001",
                parent_platform_comment_id=None,
                body_text="Which project evidence should be prepared first?",
                published_at=datetime(2026, 1, 5, 10, 15, tzinfo=UTC),
                like_count=9,
                reply_count=1,
                region_text="Beijing",
            ),
            CollectedComment(
                platform=platform,
                platform_comment_id="comment-ai-002",
                platform_content_id="note-ai-001",
                platform_author_id="user-student-001",
                parent_platform_comment_id="comment-ai-001",
                body_text="A portfolio summary and teacher confirmation helped us.",
                published_at=datetime(2026, 1, 5, 11, 5, tzinfo=UTC),
                like_count=4,
                reply_count=0,
                region_text="Guangzhou",
            ),
        ),
        "note-ai-002": (),
    }
