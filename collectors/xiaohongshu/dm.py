from __future__ import annotations

from typing import Any

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from collectors.xiaohongshu.browser import XiaohongshuBrowser, XiaohongshuBrowserConfig


class XiaohongshuDirectMessageSender:
    def __init__(self, config: XiaohongshuBrowserConfig | None = None) -> None:
        self._browser = XiaohongshuBrowser(config)

    def close(self) -> None:
        self._browser.close()

    def send_message(self, *, profile_url: str, text: str) -> dict[str, str]:
        page = self._browser._new_page()
        artifact_name = "xhs-dm-send"
        try:
            page.goto(profile_url, wait_until="domcontentloaded", timeout=self._browser.config.page_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(self._browser.config.page_timeout_ms, 10000))
            except PlaywrightTimeoutError:
                pass
            html = page.content()
            self._browser._handle_login_or_expired(page, html, artifact_name=artifact_name)

            _click_first(page, ("私信", "发消息", "聊天"))
            page.wait_for_timeout(800)
            _fill_message_box(page, text)
            _click_first(page, ("发送",))
            page.wait_for_timeout(1000)
            return {"status": "sent", "profile_url": profile_url}
        except Exception as exc:
            screenshot = self._browser._save_screenshot(page, artifact_name)
            raise RuntimeError(f"Xiaohongshu direct message send failed: {exc}; screenshot={screenshot}") from exc
        finally:
            page.close()


def _click_first(page: Any, labels: tuple[str, ...]) -> None:
    last_error: Exception | None = None
    for label in labels:
        for locator in (
            page.get_by_role("button", name=label),
            page.get_by_text(label, exact=True),
            page.locator(f"text={label}"),
        ):
            try:
                locator.first.click(timeout=5000)
                return
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                last_error = exc
                continue
    raise RuntimeError(f"could not click any of: {', '.join(labels)}") from last_error


def _fill_message_box(page: Any, text: str) -> None:
    candidates = (
        page.locator("textarea"),
        page.locator("input[type='text']"),
        page.locator("[contenteditable='true']"),
    )
    last_error: Exception | None = None
    for locator in candidates:
        try:
            target = locator.first
            target.click(timeout=5000)
            try:
                target.fill(text, timeout=5000)
            except PlaywrightError:
                page.keyboard.insert_text(text)
            return
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            last_error = exc
            continue
    raise RuntimeError("could not find Xiaohongshu message input") from last_error
