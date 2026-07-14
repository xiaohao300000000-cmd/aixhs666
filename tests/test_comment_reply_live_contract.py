from __future__ import annotations

import os

import pytest
from playwright.sync_api import Error as PlaywrightError

from collectors.xiaohongshu.browser import XiaohongshuBrowser
from collectors.xiaohongshu.comment_reply import XiaohongshuCommentReplySender, inspect_comment_reply_selectors
from collectors.xiaohongshu import selectors


LIVE_APPROVAL_PHRASE = "FEISHU_APPROVED_SINGLE_COMMENT_REPLY"


def _required_live_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(
            "live comment-reply acceptance is disabled; provide an explicit prepared target, text, and approval environment"
        )
    return value


@pytest.mark.live
def test_comment_reply_live_acceptance_requires_probe_and_explicit_feishu_approval() -> None:
    target_url = _required_live_env("XHS_COMMENT_REPLY_LIVE_TARGET_URL")
    target_comment_id = _required_live_env("XHS_COMMENT_REPLY_LIVE_TARGET_COMMENT_ID")
    target_content_id = _required_live_env("XHS_COMMENT_REPLY_LIVE_TARGET_CONTENT_ID")
    approved_text = _required_live_env("XHS_COMMENT_REPLY_LIVE_APPROVED_TEXT")
    approval = _required_live_env("XHS_COMMENT_REPLY_LIVE_FEISHU_APPROVAL")
    if approval != LIVE_APPROVAL_PHRASE or os.getenv("XHS_COMMENT_REPLY_LIVE_SEND") != "1":
        pytest.skip("real send requires the exact Feishu approval phrase and XHS_COMMENT_REPLY_LIVE_SEND=1")

    browser = XiaohongshuBrowser()
    page = None
    try:
        page = browser._new_page()
        page.goto(target_url, wait_until="domcontentloaded", timeout=browser.config.page_timeout_ms)
        report = inspect_comment_reply_selectors(
            page,
            platform_comment_id=target_comment_id,
            expand_reply=True,
            timeout_ms=browser.config.page_timeout_ms,
        )
    except PlaywrightError as exc:
        pytest.fail(f"selector probe could not complete before live send: {exc}")
    finally:
        if page is not None:
            page.close()
        browser.close()

    assert sum(
        count
        for selector, count in report.items()
        if ">>" not in selector and selector in {
            template.format(platform_comment_id=target_comment_id)
            for template in selectors.COMMENT_TARGET_CONTAINER_TEMPLATES
        }
    ) == 1
    assert any(selector.endswith(selectors.COMMENT_REPLY_TRIGGER_SELECTOR) and count == 1 for selector, count in report.items())
    assert any(selector.endswith(selectors.COMMENT_REPLY_EDITOR_SELECTOR) and count == 1 for selector, count in report.items())
    assert any(selector.endswith(selectors.COMMENT_REPLY_SUBMIT_SELECTOR) and count == 1 for selector, count in report.items())

    result = XiaohongshuCommentReplySender().reply_to_comment(
        platform_comment_id=target_comment_id,
        platform_content_id=target_content_id,
        target_url=target_url,
        text=approved_text,
    )

    assert result.outcome == "sent", (
        f"live acceptance ended as {result.outcome!r}; inspect XHS manually and do not blindly retry, "
        f"especially when outcome is result_unknown. error={result.error!r}"
    )
