from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright

from collectors.xiaohongshu.browser import XiaohongshuBrowser, XiaohongshuBrowserConfig
from collectors.xiaohongshu.comment_reply import XiaohongshuCommentReplySender, inspect_comment_reply_selectors
from collectors.xiaohongshu import selectors
from collectors.xiaohongshu.exceptions import LoginRequiredError, XiaohongshuCommentReplyDefiniteFailure


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "xhs" / "comment_reply_page.html"
TARGET_ID = "xhs-comment-002"
TEXT = "可以先看孩子目前最薄弱的题型。"


class FakeResponse:
    def __init__(self, url: str, payload: dict[str, Any]) -> None:
        self.url = url
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeLocator:
    def __init__(self, page: FakePage, kind: str, *, target_id: str | None = None, count: int = 0) -> None:
        self.page = page
        self.kind = kind
        self.target_id = target_id
        self._count = count
        self.first = self

    def count(self) -> int:
        return self._count

    def is_visible(self, *, timeout: int) -> bool:
        assert timeout == self.page.config.page_timeout_ms
        return not (self.kind == "submit" and self.page.submit_hidden)

    def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout == self.page.config.page_timeout_ms

    def locator(self, selector: str) -> FakeLocator:
        assert self.target_id is not None, "global locator scoping is forbidden"
        if selector == self.page.reply_button_selector:
            return FakeLocator(self.page, "reply", target_id=self.target_id, count=1)
        if selector == self.page.editor_selector:
            count = self.page.editor_count if self.target_id == TARGET_ID and self.page.controls_are_available else 0
            return FakeLocator(self.page, "editor", target_id=self.target_id, count=count)
        if selector == self.page.submit_selector:
            count = self.page.submit_count_available if self.target_id == TARGET_ID and self.page.controls_are_available else 0
            return FakeLocator(self.page, "submit", target_id=self.target_id, count=count)
        if selector == self.page.visible_reply_selector:
            count = len(self.page.target_reply_texts) if self.target_id == TARGET_ID else 0
            return FakeLocator(self.page, "visible-replies", target_id=self.target_id, count=count)
        raise AssertionError(f"unexpected scoped selector: {selector}")

    def click(self, *, timeout: int) -> None:
        assert timeout == self.page.config.page_timeout_ms
        assert self._count == 1
        if self.kind == "reply":
            self.page.replied_comment_id = self.target_id
            return
        if self.kind != "submit":
            return
        self.page.submit_clicks += 1
        if self.page.submit_clicks > 1:
            raise AssertionError("sender clicked submit more than once")
        if self.page.submit_uncertain:
            raise PlaywrightTimeoutError("click response timed out")
        self.page.after_submit()

    def fill(self, text: str, *, timeout: int) -> None:
        assert self.kind == "editor"
        assert timeout == self.page.config.page_timeout_ms
        self.page.submitted_text = text

    def all_inner_texts(self) -> list[str]:
        assert self.kind == "visible-replies"
        return list(self.page.target_reply_texts)


@dataclass
class FakePage:
    target_present: bool = True
    target_count: int = 1
    editor_count: int = 1
    submit_count_available: int = 1
    submit_hidden: bool = False
    submit_uncertain: bool = False
    emit_response: bool = True
    visible_new_reply: bool = False
    stale_page_success: bool = False
    captcha_required: bool = False
    login_required: bool = False
    reject_response: bool = False
    target_reply_texts: list[str] = field(default_factory=lambda: ["已有回复"])
    controls_after_reply_click: bool = False
    submitted_text: str | None = None
    replied_comment_id: str | None = None
    submit_clicks: int = 0
    closed: bool = False
    response_handlers: list[Any] = field(default_factory=list)
    config: Any = field(default_factory=lambda: type("Config", (), {"page_timeout_ms": 5000})())
    reply_button_selector: str = "[data-xhs-role='comment-reply-trigger']"
    editor_selector: str = "[data-xhs-role='comment-reply-editor']"
    submit_selector: str = "[data-xhs-role='comment-reply-submit']"
    visible_reply_selector: str = "[data-xhs-role='comment-reply-text']"

    @property
    def controls_are_available(self) -> bool:
        return not self.controls_after_reply_click or self.replied_comment_id == TARGET_ID

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        assert url == "https://www.xiaohongshu.com/explore/xhs-note-001?xsec_token=stored"
        assert wait_until == "domcontentloaded"
        assert timeout == self.config.page_timeout_ms

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        assert state == "networkidle"
        assert timeout == self.config.page_timeout_ms

    def wait_for_timeout(self, timeout: int) -> None:
        assert timeout == 700

    def on(self, event: str, callback: Any) -> None:
        assert event == "response"
        self.response_handlers.append(callback)

    def locator(self, selector: str) -> FakeLocator:
        if TARGET_ID in selector and selector.startswith('[data-comment-id='):
            return FakeLocator(self, "target", target_id=TARGET_ID, count=self.target_count if self.target_present else 0)
        if "xhs-comment-001" in selector and selector.startswith('[data-comment-id='):
            return FakeLocator(self, "target", target_id="xhs-comment-001", count=1)
        if TARGET_ID in selector:
            return FakeLocator(self, "target", target_id=TARGET_ID, count=0)
        raise AssertionError(f"unsafe global/unrelated selector used: {selector}")

    def content(self) -> str:
        suffix = "<div>回复成功 data-reply-id=stale</div>" if self.stale_page_success else ""
        if self.captcha_required:
            suffix += "<div>滑块验证</div>"
        return FIXTURE_PATH.read_text(encoding="utf-8") + suffix

    def after_submit(self) -> None:
        if self.emit_response:
            payload = (
                {"code": 1001, "msg": "操作频繁，请稍后再试"}
                if self.reject_response
                else {"code": 0, "data": {"comment_id": "xhs-reply-123"}}
            )
            response = FakeResponse("https://www.xiaohongshu.com/api/sns/web/v1/comment/post", payload)
            for callback in self.response_handlers:
                callback(response)
        if self.visible_new_reply:
            self.target_reply_texts.append(TEXT)

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.config = page.config
        self.closed = False

    def _new_page(self) -> FakePage:
        return self.page

    def _handle_login_or_expired(self, page: FakePage, html: str, *, artifact_name: str) -> None:
        del html, artifact_name
        if page.login_required:
            raise LoginRequiredError("manual login is required")

    def close(self) -> None:
        self.closed = True


def _reply(page: FakePage, *, target_url: str | None = "https://www.xiaohongshu.com/explore/xhs-note-001?xsec_token=stored"):
    return XiaohongshuCommentReplySender(browser_factory=lambda: FakeBrowser(page)).reply_to_comment(
        platform_content_id="xhs-note-001",
        platform_comment_id=TARGET_ID,
        target_url=target_url,
        text=TEXT,
    )


def test_sender_uses_canonical_stored_target_url_and_correlated_response() -> None:
    page = FakePage()
    result = _reply(page)
    assert result.outcome == "sent"
    assert result.platform_reply_id == "xhs-reply-123"
    assert page.replied_comment_id == TARGET_ID
    assert page.submitted_text == TEXT
    assert page.submit_clicks == 1


def test_sender_waits_for_editor_and_submit_after_clicking_reply() -> None:
    page = FakePage(controls_after_reply_click=True)

    result = _reply(page)

    assert result.outcome == "sent"
    assert page.replied_comment_id == TARGET_ID
    assert page.submit_clicks == 1


def test_selector_probe_expands_target_reply_without_filling_or_submitting() -> None:
    page = FakePage(controls_after_reply_click=True)

    report = inspect_comment_reply_selectors(
        page,
        platform_comment_id=TARGET_ID,
        expand_reply=True,
        timeout_ms=page.config.page_timeout_ms,
    )

    assert page.replied_comment_id == TARGET_ID
    assert page.submitted_text is None
    assert page.submit_clicks == 0
    assert any(selector.endswith(selectors.COMMENT_REPLY_EDITOR_SELECTOR) and count == 1 for selector, count in report.items())
    assert any(selector.endswith(selectors.COMMENT_REPLY_SUBMIT_SELECTOR) and count == 1 for selector, count in report.items())


def test_browser_config_uses_remote_comment_reply_cdp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMMENT_REPLY_BROWSER_MODE", "remote_cdp")
    monkeypatch.setenv("COMMENT_REPLY_CDP_URL", "http://100.124.24.8:19223")

    config = XiaohongshuBrowserConfig.from_env()

    assert config.browser_mode == "remote_cdp"
    assert config.cdp_url == "http://100.124.24.8:19223"


def test_browser_remote_cdp_reuses_existing_context(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    existing_context = type("Context", (), {"close": lambda self: None})()
    remote_browser = type("Browser", (), {"contexts": [existing_context], "close": lambda self: None})()

    class Chromium:
        def connect_over_cdp(self, url: str):
            calls.append(("connect_over_cdp", url))
            return remote_browser

        def launch_persistent_context(self, **kwargs):
            raise AssertionError("remote comment reply must not launch a local browser")

    playwright = type("Playwright", (), {"chromium": Chromium(), "webkit": object(), "stop": lambda self: None})()
    starter = type("Starter", (), {"start": lambda self: playwright})()
    monkeypatch.setattr("collectors.xiaohongshu.browser.sync_playwright", lambda: starter)
    config = XiaohongshuBrowserConfig(
        profile_dir=Path(".runtime/xhs-profile"),
        browser_engine="chromium",
        headless=False,
        snapshot_dir=Path(".runtime/snapshots"),
        screenshot_dir=Path(".runtime/screenshots"),
        page_timeout_ms=5000,
        manual_login_timeout_ms=5000,
        proxy_server=None,
        browser_mode="remote_cdp",
        cdp_url="http://100.124.24.8:19223",
    )

    browser = XiaohongshuBrowser(config)

    assert browser._ensure_context() is existing_context
    assert calls == [("connect_over_cdp", "http://100.124.24.8:19223")]


def test_sender_falls_back_to_constructed_url_only_when_target_url_absent() -> None:
    page = FakePage()
    page.goto = lambda url, **_: setattr(page, "visited_url", url)
    result = _reply(page, target_url=None)
    assert result.outcome == "sent"
    assert page.visited_url == "https://www.xiaohongshu.com/explore/xhs-note-001"


@pytest.mark.parametrize("target_url", ["https://evil.example/explore/xhs-note-001", "not-a-url"])
def test_sender_rejects_invalid_stored_target_url_before_submit(target_url: str) -> None:
    page = FakePage()
    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure, match="canonical target URL"):
        _reply(page, target_url=target_url)
    assert page.submit_clicks == 0


@pytest.mark.parametrize("attribute,value", [("target_present", False), ("target_count", 2), ("editor_count", 2), ("submit_count_available", 0)])
def test_sender_rejects_missing_or_ambiguous_target_controls_before_submit(attribute: str, value: int | bool) -> None:
    page = FakePage()
    setattr(page, attribute, value)
    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure):
        _reply(page)
    assert page.submit_clicks == 0


def test_sender_rejects_hidden_submit_before_click() -> None:
    page = FakePage(submit_hidden=True)
    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure, match="not visible"):
        _reply(page)
    assert page.submit_clicks == 0


def test_sender_ignores_stale_page_wide_success_without_correlated_evidence() -> None:
    page = FakePage(emit_response=False, stale_page_success=True)
    result = _reply(page)
    assert result.outcome == "result_unknown"
    assert page.submit_clicks == 1


def test_sender_accepts_new_matching_reply_only_inside_target_container() -> None:
    page = FakePage(emit_response=False, visible_new_reply=True)
    result = _reply(page)
    assert result.outcome == "sent"
    assert result.response_json == {"success_evidence": "visible_target_reply"}


def test_sender_returns_definite_failure_when_submit_is_missing_before_click() -> None:
    page = FakePage(submit_count_available=0)
    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure):
        _reply(page)
    assert page.submit_clicks == 0


def test_sender_returns_unknown_when_submit_click_may_have_dispatched() -> None:
    page = FakePage(submit_uncertain=True)
    result = _reply(page)
    assert result.outcome == "result_unknown"
    assert page.submit_clicks == 1


@pytest.mark.parametrize("attribute", ["captcha_required", "login_required"])
def test_sender_raises_exact_definite_failure_before_submit_for_login_or_captcha(attribute: str) -> None:
    page = FakePage()
    setattr(page, attribute, True)
    with pytest.raises(XiaohongshuCommentReplyDefiniteFailure):
        _reply(page)
    assert page.submit_clicks == 0


def test_sender_returns_failed_for_correlated_platform_rejection() -> None:
    page = FakePage(reject_response=True)
    result = _reply(page)
    assert result.outcome == "failed"
    assert result.error == "操作频繁，请稍后再试"
    assert page.submit_clicks == 1


def test_fixture_selector_contract_executes_with_real_playwright_and_never_touches_unrelated_controls() -> None:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.set_content(FIXTURE_PATH.read_text(encoding="utf-8"))
                target = page.locator(selectors.COMMENT_TARGET_CONTAINER_TEMPLATES[0].format(platform_comment_id=TARGET_ID))
                unrelated = page.locator(selectors.COMMENT_TARGET_CONTAINER_TEMPLATES[0].format(platform_comment_id="xhs-comment-001"))
                assert target.count() == 1
                assert target.locator(selectors.COMMENT_REPLY_TRIGGER_SELECTOR).count() == 1
                assert target.locator(selectors.COMMENT_REPLY_EDITOR_SELECTOR).count() == 1
                assert target.locator(selectors.COMMENT_REPLY_SUBMIT_SELECTOR).count() == 1
                assert unrelated.locator(selectors.COMMENT_REPLY_EDITOR_SELECTOR).count() == 0
                assert unrelated.locator(selectors.COMMENT_REPLY_SUBMIT_SELECTOR).count() == 0

                page.evaluate(
                    """({targetId, trigger, editor, submit, text}) => {
                        const target = document.querySelector(`[data-comment-id="${targetId}"]`);
                        target.querySelector(trigger).addEventListener("click", () => { target.dataset.clicked = "true"; });
                        target.querySelector(submit).addEventListener("click", () => {
                            const reply = document.createElement("div");
                            reply.setAttribute("data-xhs-role", "comment-reply-text");
                            reply.textContent = target.querySelector(editor).value;
                            target.appendChild(reply);
                        });
                    }""",
                    {"targetId": TARGET_ID, "trigger": selectors.COMMENT_REPLY_TRIGGER_SELECTOR, "editor": selectors.COMMENT_REPLY_EDITOR_SELECTOR, "submit": selectors.COMMENT_REPLY_SUBMIT_SELECTOR, "text": selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR},
                )
                target.locator(selectors.COMMENT_REPLY_TRIGGER_SELECTOR).click()
                target.locator(selectors.COMMENT_REPLY_EDITOR_SELECTOR).fill(TEXT)
                target.locator(selectors.COMMENT_REPLY_SUBMIT_SELECTOR).click()
                assert target.get_attribute("data-clicked") == "true"
                assert target.locator(selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR).all_inner_texts() == ["已有回复", TEXT]
                assert unrelated.locator(selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR).all_inner_texts() == []
            finally:
                browser.close()
    except PlaywrightError as exc:
        pytest.skip(f"Playwright Chromium executable unavailable: {exc}")


def test_production_selector_list_excludes_disabled_speculative_alternatives() -> None:
    production_selectors = (
        *selectors.COMMENT_TARGET_CONTAINER_TEMPLATES,
        selectors.COMMENT_REPLY_TRIGGER_SELECTOR,
        selectors.COMMENT_REPLY_EDITOR_SELECTOR,
        selectors.COMMENT_REPLY_SUBMIT_SELECTOR,
        selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR,
    )
    assert not set(production_selectors) & set(selectors.DISABLED_SPECULATIVE_COMMENT_REPLY_SELECTORS)


def test_live_selector_probe_is_opt_in_and_never_submits() -> None:
    target_url = os.getenv("XHS_COMMENT_REPLY_SELECTOR_PROBE_URL")
    target_id = os.getenv("XHS_COMMENT_REPLY_SELECTOR_PROBE_COMMENT_ID")
    if not target_url or not target_id:
        pytest.skip("set XHS_COMMENT_REPLY_SELECTOR_PROBE_URL and XHS_COMMENT_REPLY_SELECTOR_PROBE_COMMENT_ID to inspect live selectors")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=30_000)
                report = inspect_comment_reply_selectors(page, platform_comment_id=target_id, expand_reply=True)
            finally:
                browser.close()
    except PlaywrightError as exc:
        pytest.skip(f"Playwright Chromium executable unavailable: {exc}")
    print(f"inspection-only XHS selector report: {report}")
    assert all(selector not in selectors.DISABLED_SPECULATIVE_COMMENT_REPLY_SELECTORS for selector in report)
    assert report
