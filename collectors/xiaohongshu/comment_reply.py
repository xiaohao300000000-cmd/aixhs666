from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from collectors.xiaohongshu import selectors
from collectors.xiaohongshu.browser import XiaohongshuBrowser, XiaohongshuBrowserConfig
from collectors.xiaohongshu.exceptions import XiaohongshuCommentReplyDefiniteFailure
from integrations.feishu.comment_replies import CommentReplyPreSubmitError, CommentReplySendResult, CommentReplySender


_REPLY_ID_RE = re.compile(r"reply[_-]?id[=:\\s]+[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)


class XiaohongshuCommentReplySender(CommentReplySender):
    """Reply once to one exact Xiaohongshu comment through a persistent profile."""

    def __init__(
        self,
        config: XiaohongshuBrowserConfig | None = None,
        *,
        browser_factory: Callable[[], XiaohongshuBrowser] | None = None,
    ) -> None:
        self._browser_factory = browser_factory or (lambda: XiaohongshuBrowser(config))

    def reply_to_comment(
        self,
        *,
        platform_comment_id: str,
        platform_content_id: str,
        text: str,
    ) -> CommentReplySendResult:
        browser = self._browser_factory()
        page: Any | None = None
        submitted = False
        try:
            page = browser._new_page()
            url = selectors.CONTENT_URL_TEMPLATE.format(platform_content_id=platform_content_id)
            page.goto(url, wait_until="domcontentloaded", timeout=browser.config.page_timeout_ms)
            try:
                page.wait_for_timeout(600)
            except PlaywrightTimeoutError:
                pass

            html = page.content()
            _raise_for_pre_submit_blocker(html)
            _click_target_reply(page, platform_comment_id)
            _fill_reply_editor(page, text)
            _raise_for_pre_submit_blocker(page.content())

            submitted = True
            _click_submit(page)
            try:
                page.wait_for_timeout(900)
            except PlaywrightTimeoutError as exc:
                return _unknown(str(exc))

            evidence = page.content()
            rejection = _platform_rejection(evidence)
            if rejection:
                return CommentReplySendResult(outcome="failed", error=rejection)
            reply_id = _success_reply_id(evidence)
            if reply_id is not None:
                return CommentReplySendResult(
                    outcome="sent",
                    platform_reply_id=reply_id,
                    response_json={"success_evidence": "visible_reply"},
                )
            if _visible_success(evidence):
                return CommentReplySendResult(
                    outcome="sent",
                    response_json={"success_evidence": "visible_success"},
                )
            return _unknown("Xiaohongshu did not provide conclusive reply success evidence")
        except XiaohongshuCommentReplyDefiniteFailure:
            raise
        except CommentReplyPreSubmitError:
            raise
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            if submitted:
                return _unknown(str(exc))
            raise XiaohongshuCommentReplyDefiniteFailure(f"Xiaohongshu reply was not submitted: {exc}") from exc
        except Exception as exc:
            if submitted:
                return _unknown(str(exc))
            raise XiaohongshuCommentReplyDefiniteFailure(f"Xiaohongshu reply was not submitted: {exc}") from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            browser.close()


def _click_target_reply(page: Any, platform_comment_id: str) -> None:
    escaped_id = _css_attribute_value(platform_comment_id)
    candidates = (
        page.locator(f'[data-comment-id="{escaped_id}"] {selectors.COMMENT_REPLY_BUTTONS[0]}'),
        page.locator(f'[data-comment-id="{escaped_id}"] {selectors.COMMENT_REPLY_BUTTONS[1]}'),
        page.locator(f'[data-comment-id="{escaped_id}"] {selectors.COMMENT_REPLY_BUTTONS[2]}'),
        page.locator(f'[data-comment-id="{escaped_id}"] [role="button"]'),
    )
    for locator in candidates:
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            return
        except (PlaywrightError, PlaywrightTimeoutError):
            continue
    raise XiaohongshuCommentReplyDefiniteFailure(
        f"target comment {platform_comment_id!r} is missing or cannot be replied to"
    )


def _fill_reply_editor(page: Any, text: str) -> None:
    for selector in selectors.COMMENT_REPLY_EDITORS:
        locator = page.locator(selector).first
        try:
            locator.click(timeout=5000)
            try:
                locator.fill(text, timeout=5000)
            except PlaywrightError:
                page.keyboard.insert_text(text)
            return
        except (PlaywrightError, PlaywrightTimeoutError):
            continue
    raise XiaohongshuCommentReplyDefiniteFailure("Xiaohongshu reply editor is unavailable")


def _click_submit(page: Any) -> None:
    for selector in selectors.COMMENT_REPLY_SUBMITS:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        locator.first.click(timeout=5000)
        return
    for label in ("发布", "发送", "回复"):
        locator = page.get_by_role("button", name=label)
        if locator.count() == 0:
            continue
        locator.first.click(timeout=5000)
        return
    raise XiaohongshuCommentReplyDefiniteFailure("Xiaohongshu reply submit control is unavailable")


def _raise_for_pre_submit_blocker(html: str) -> None:
    if any(marker in html for marker in selectors.COMMENT_REPLY_LOGIN_OR_CAPTCHA_MARKERS):
        raise XiaohongshuCommentReplyDefiniteFailure("Xiaohongshu login or captcha is required before replying")


def _platform_rejection(html: str) -> str | None:
    for marker in selectors.COMMENT_REPLY_REJECTION_MARKERS:
        if marker in html:
            return marker
    return None


def _visible_success(html: str) -> bool:
    return any(marker in html for marker in selectors.COMMENT_REPLY_SUCCESS_MARKERS)


def _success_reply_id(html: str) -> str | None:
    match = _REPLY_ID_RE.search(html)
    return match.group(1) if match else None


def _unknown(error: str) -> CommentReplySendResult:
    return CommentReplySendResult(outcome="result_unknown", error=error)


def _css_attribute_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
