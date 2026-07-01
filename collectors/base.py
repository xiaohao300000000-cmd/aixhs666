from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PageCursor:
    next_cursor: str | None = None
    has_more: bool = False


@dataclass(frozen=True, slots=True)
class CollectedSearchResult:
    platform: str
    platform_content_id: str
    platform_author_id: str | None
    content_type: str
    title: str | None
    body_text: str | None
    published_at: datetime | None
    url: str | None
    region_text: str | None
    like_count: int
    comment_count: int
    collect_count: int
    rank_position: int | None = None
    result_page: int | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    query_text: str
    items: tuple[CollectedSearchResult, ...]
    cursor: PageCursor


@dataclass(frozen=True, slots=True)
class CollectedContent:
    platform: str
    platform_content_id: str
    platform_author_id: str | None
    content_type: str
    title: str | None
    body_text: str | None
    published_at: datetime | None
    url: str | None
    region_text: str | None
    like_count: int
    comment_count: int
    collect_count: int
    tags: tuple[str, ...] = ()
    image_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectedComment:
    platform: str
    platform_comment_id: str
    platform_content_id: str
    platform_author_id: str | None
    parent_platform_comment_id: str | None
    body_text: str | None
    published_at: datetime | None
    like_count: int
    reply_count: int
    region_text: str | None = None


@dataclass(frozen=True, slots=True)
class CommentPage:
    platform_content_id: str
    items: tuple[CollectedComment, ...]
    cursor: PageCursor


@dataclass(frozen=True, slots=True)
class CollectedProfile:
    platform: str
    platform_user_id: str
    display_name: str | None
    profile_url: str | None
    bio: str | None
    region_text: str | None
    public_contact_text: str | None


class PlatformAdapter(Protocol):
    @property
    def platform(self) -> str:
        """Stable platform identifier used by storage models."""
        ...

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        """Return platform content hits for a query."""
        ...

    def get_content(self, platform_content_id: str) -> CollectedContent:
        """Return one content detail by platform content id."""
        ...

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        """Return comments for one platform content id."""
        ...

    def get_profile(self, platform_user_id: str) -> CollectedProfile:
        """Return one public user profile by platform user id."""
        ...
