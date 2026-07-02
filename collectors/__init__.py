"""Platform data collection boundary."""

from collectors.base import (
    CollectedComment,
    CollectedContent,
    CollectedProfile,
    CollectedSearchResult,
    CommentPage,
    PageCursor,
    PlatformAdapter,
    SearchPage,
)
from collectors.mock import MockPlatformAdapter
from collectors.xiaohongshu import XiaohongshuAdapter

__all__ = [
    "CollectedComment",
    "CollectedContent",
    "CollectedProfile",
    "CollectedSearchResult",
    "CommentPage",
    "MockPlatformAdapter",
    "PageCursor",
    "PlatformAdapter",
    "SearchPage",
    "XiaohongshuAdapter",
]
