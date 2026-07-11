from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from collectors.xiaohongshu.comment_reply import XiaohongshuCommentReplySender
from collectors.xiaohongshu.exceptions import XiaohongshuCommentReplyDefiniteFailure
from integrations.feishu.comment_replies import CommentReplyPreSubmitError


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "xhs" / "comment_reply_page.html"


class FakeLocator:
    def __init__(self, page: FakePage, selector: str, *, visible: bool = True) -> None:
        self.page = page
        self.selector = selector
        self.visible = visible
        self.first = self

    def count(self) -> int:
        if "xhs-comment-002" in self.selector:
            return 1 if self.page.target_present else 0
        if "xhs-comment-001" in self.selector:
            return 1
        return 1 if self.visible else 0

    def click(self, *, timeout: int) -> None:
        del timeout
        if self.count() == 0:
            raise PlaywrightError("locator not found")
        if "reply-button" in self.selector:
            self.page.replied_comment_id = "xhs-comment-002" if "xhs-comment-002" in self.selector else "xhs-comment-001"
        elif "submit" in self.selector or "发布" in self.selector:
            self.page.submit_count += 1
            if self.page.reject_on_submit:
                self.page.platform_rejection = "操作频繁，请稍后再试"
            if self.page.timeout_after_submit:
                raise PlaywrightTimeoutError("submit response timed out")
            if self.page.crash_after_submit:
                raise PlaywrightError("page crashed")
            if self.page.success_after_submit:
                self.page.success_reply_id = "xhs-reply-123"

    def fill(self, text: str, *, timeout: int) -> None:
        del timeout
        self.page.submitted_text = text

    def inner_text(self, *, timeout: int) -> str:
        del timeout
        if self.page.platform_rejection:
            return self.page.platform_rejection
        if self.page.success_reply_id:
            return f"回复成功 data-reply-id={self.page.success_reply_id}"
        return ""


class FakeKeyboard:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def insert_text(self, text: str) -> None:
        self.page.submitted_text = text


@dataclass
class FakePage:
    target_present: bool = True
    login_required: bool = False
    captcha_required: bool = False
    reject_on_submit: bool = False
    timeout_after_submit: bool = False
    crash_after_submit: bool = False
    success_after_submit: bool = True
    replied_comment_id: str | None = None
    submitted_text: str | None = None
    success_reply_id: str | None = None
    platform_rejection: str | None = None
    submit_count: int = 0
    closed: bool = False

    def __post_init__(self) -> None:
        self.keyboard = FakeKeyboard(self)

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        del url, wait_until, timeout

    def content(self) -> str:
        html = FIXTURE_PATH.read_text(encoding="utf-8")
        if self.login_required:
            return html + '<div class="login-container">登录</div>'
        if self.captcha_required:
            return html + '<div>验证码</div>'
        if self.platform_rejection:
            return html + f"<div>{self.platform_rejection}</div>"
        if self.success_reply_id:
            return html + f'<div>回复成功 data-reply-id={self.success_reply_id}</div>'
        return html

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def get_by_role(self, role: str, *, name: str) -> FakeLocator:
        return FakeLocator(self, f"{role}:{name}", visible=name == "发布")

    def get_by_text(self, text: str, *, exact: bool = False) -> FakeLocator:
        del exact
        return FakeLocator(self, f"text:{text}")

    def wait_for_timeout(self, timeout: int) -> None:
        del timeout

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.config = type("Config", (), {"page_timeout_ms": 5000})()
        self.closed = False

    def _new_page(self) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_browser_page() -> FakePage:
    return FakePage()


def _sender(page: FakePage) -> XiaohongshuCommentReplySender:
    return XiaohongshuCommentReplySender(browser_factory=lambda: FakeBrowser(page))


def _reply(sender: XiaohongshuCommentReplySender):
    return sender.reply_to_comment(
        platform_content_id="xhs-note-001",
        platform_comment_id="xhs-comment-002",
        text="可以先看孩子目前最薄弱的题型。",
    )


def test_sender_replies_to_exact_comment(fake_browser_page: FakePage) -> None:
    result = _reply(_sender(fake_browser_page))

    assert result.outcome == "sent"
    assert result.platform_reply_id == "xhs-reply-123"
    assert fake_browser_page.replied_comment_id == "xhs-comment-002"
    assert fake_browser_page.submitted_text == "可以先看孩子目前最薄弱的题型。"
    assert fake_browser_page.submit_count == 1
    assert fake_browser_page.closed is True


def test_sender_returns_unknown_after_submit_timeout(fake_browser_page: FakePage) -> None:
    fake_browser_page.timeout_after_submit = True

    result = _reply(_sender(fake_browser_page))

    assert result.outcome == "result_unknown"
    assert fake_browser_page.submit_count == 1


def test_sender_returns_unknown_after_submit_crash(fake_browser_page: FakePage) -> None:
    fake_browser_page.crash_after_submit = True

    result = _reply(_sender(fake_browser_page))

    assert result.outcome == "result_unknown"
    assert fake_browser_page.submit_count == 1


@pytest.mark.parametrize("attribute", ["login_required", "captcha_required"])
def test_sender_raises_definite_failure_before_submit_for_login_or_captcha(fake_browser_page: FakePage, attribute: str) -> None:
    setattr(fake_browser_page, attribute, True)

    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure):
        _reply(_sender(fake_browser_page))

    assert fake_browser_page.submit_count == 0


def test_sender_raises_definite_failure_when_target_comment_is_missing(fake_browser_page: FakePage) -> None:
    fake_browser_page.target_present = False

    with pytest.raises(CommentReplyPreSubmitError, match="target comment"):
        _reply(_sender(fake_browser_page))

    assert fake_browser_page.submit_count == 0


def test_sender_returns_failed_for_explicit_platform_rejection(fake_browser_page: FakePage) -> None:
    fake_browser_page.reject_on_submit = True
    fake_browser_page.success_after_submit = False

    result = _reply(_sender(fake_browser_page))

    assert result.outcome == "failed"
    assert result.error == "操作频繁，请稍后再试"
    assert fake_browser_page.submit_count == 1
