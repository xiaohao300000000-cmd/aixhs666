from __future__ import annotations

from collectors.base import CollectedContent, CollectedProfile, CommentPage, SearchPage
from collectors.xiaohongshu.browser import XiaohongshuBrowser, XiaohongshuBrowserConfig
from collectors.xiaohongshu.parsers import parse_comment_page, parse_content_detail, parse_profile, parse_search_page


class XiaohongshuAdapter:
    """Playwright-backed adapter for Xiaohongshu public pages."""

    def __init__(
        self,
        *,
        browser: XiaohongshuBrowser | None = None,
        browser_config: XiaohongshuBrowserConfig | None = None,
    ) -> None:
        self._browser = browser or XiaohongshuBrowser(browser_config)

    @property
    def platform(self) -> str:
        return "xhs"

    def close(self) -> None:
        self._browser.close()

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        capture = self._browser.fetch_search_page(query_text, cursor=cursor, limit=limit)
        return parse_search_page(query_text, capture.body_text, source_url=capture.url, cursor=cursor, limit=limit)

    def get_content(self, platform_content_id: str) -> CollectedContent:
        capture = self._browser.fetch_content_page(platform_content_id)
        return parse_content_detail(platform_content_id, capture.body_text, source_url=capture.url)

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        capture = self._browser.fetch_comments_page(platform_content_id, cursor=cursor, limit=limit)
        return parse_comment_page(platform_content_id, capture.body_text, source_url=capture.url, cursor=cursor, limit=limit)

    def get_profile(self, platform_user_id: str) -> CollectedProfile:
        capture = self._browser.fetch_profile_page(platform_user_id)
        return parse_profile(platform_user_id, capture.body_text, source_url=capture.url)
