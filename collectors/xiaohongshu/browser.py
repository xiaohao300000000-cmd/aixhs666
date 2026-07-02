from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import BrowserContext, Error as PlaywrightError, Page, Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright

from collectors.xiaohongshu import selectors
from collectors.xiaohongshu.exceptions import LoginRequiredError, PageExpiredError, PageTimeoutError, XiaohongshuNetworkError


@dataclass(frozen=True, slots=True)
class BrowserCapture:
    body_text: str
    url: str
    json_payloads: tuple[dict[str, Any], ...]
    html_path: Path | None
    json_path: Path | None


@dataclass(frozen=True, slots=True)
class XiaohongshuBrowserConfig:
    profile_dir: Path
    headless: bool
    snapshot_dir: Path
    screenshot_dir: Path
    page_timeout_ms: int
    manual_login_timeout_ms: int
    proxy_server: str | None

    @classmethod
    def from_env(cls) -> "XiaohongshuBrowserConfig":
        return cls(
            profile_dir=Path(os.getenv("XHS_BROWSER_PROFILE_DIR", ".runtime/xhs-profile")),
            headless=_env_bool("XHS_HEADLESS", default=False),
            snapshot_dir=Path(os.getenv("XHS_SNAPSHOT_DIR", ".runtime/snapshots")),
            screenshot_dir=Path(os.getenv("XHS_SCREENSHOT_DIR", ".runtime/screenshots")),
            page_timeout_ms=int(os.getenv("XHS_PAGE_TIMEOUT_MS", "30000")),
            manual_login_timeout_ms=int(os.getenv("XHS_MANUAL_LOGIN_TIMEOUT_MS", "120000")),
            proxy_server=_empty_to_none(os.getenv("XHS_PROXY_SERVER")),
        )


class XiaohongshuBrowser:
    def __init__(self, config: XiaohongshuBrowserConfig | None = None) -> None:
        self.config = config or XiaohongshuBrowserConfig.from_env()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def fetch_search_page(self, query_text: str, *, cursor: str | None, limit: int) -> BrowserCapture:
        params = {"keyword": query_text}
        if cursor:
            params["cursor"] = cursor
        url = f"{selectors.SEARCH_URL}?{urlencode(params)}"
        return self._goto_and_capture(
            url,
            artifact_name=f"search-{_safe_name(query_text)}",
            scroll_limit=2,
            wait_response_marker="/api/sns/web/v2/search/notes",
        )

    def fetch_content_page(self, platform_content_id: str) -> BrowserCapture:
        url = selectors.CONTENT_URL_TEMPLATE.format(platform_content_id=platform_content_id)
        return self._goto_and_capture(url, artifact_name=f"content-{_safe_name(platform_content_id)}", scroll_limit=1)

    def fetch_comments_page(self, platform_content_id: str, *, cursor: str | None, limit: int) -> BrowserCapture:
        del cursor, limit
        url = selectors.CONTENT_URL_TEMPLATE.format(platform_content_id=platform_content_id)
        return self._goto_and_capture(url, artifact_name=f"comments-{_safe_name(platform_content_id)}", scroll_limit=4)

    def fetch_profile_page(self, platform_user_id: str) -> BrowserCapture:
        url = selectors.PROFILE_URL_TEMPLATE.format(platform_user_id=platform_user_id)
        return self._goto_and_capture(url, artifact_name=f"profile-{_safe_name(platform_user_id)}", scroll_limit=1)

    def _goto_and_capture(
        self,
        url: str,
        *,
        artifact_name: str,
        scroll_limit: int,
        wait_response_marker: str | None = None,
    ) -> BrowserCapture:
        page = self._new_page()
        json_payloads: list[dict[str, Any]] = []

        def capture_response(response: Any) -> None:
            response_url = getattr(response, "url", "")
            if not any(marker in response_url for marker in selectors.XHS_RESPONSE_URL_MARKERS):
                return
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict):
                json_payloads.append({"url": response_url, "payload": payload})

        page.on("response", capture_response)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.config.page_timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(self.config.page_timeout_ms, 10000))
                except PlaywrightTimeoutError:
                    pass
                if wait_response_marker and not any(wait_response_marker in item["url"] for item in json_payloads):
                    _wait_for_captured_response(page, json_payloads, wait_response_marker, timeout_ms=self.config.page_timeout_ms)
            except PlaywrightTimeoutError as exc:
                screenshot = self._save_screenshot(page, artifact_name)
                raise PageTimeoutError(f"Xiaohongshu page timed out: {url}; screenshot={screenshot}") from exc
            except PlaywrightError as exc:
                screenshot = self._save_screenshot(page, artifact_name)
                raise XiaohongshuNetworkError(
                    f"Xiaohongshu navigation failed on the current network: {url}; "
                    f"error={exc}; screenshot={screenshot}"
                ) from exc

            for _ in range(max(scroll_limit, 0)):
                page.mouse.wheel(0, 1200)
                page.wait_for_timeout(800)

            html = page.content()
            self._handle_login_or_expired(page, html, artifact_name=artifact_name)
            html_path, json_path = self._save_capture(artifact_name=artifact_name, html=html, json_payloads=json_payloads)
            body_text = _merge_capture_text(html, json_payloads)
            return BrowserCapture(
                body_text=body_text,
                url=page.url,
                json_payloads=tuple(json_payloads),
                html_path=html_path,
                json_path=json_path,
            )
        finally:
            page.close()

    def _new_page(self) -> Page:
        context = self._ensure_context()
        page = context.new_page()
        page.set_default_timeout(self.config.page_timeout_ms)
        return page

    def _ensure_context(self) -> BrowserContext:
        if self._context is not None:
            return self._context

        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        self.config.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.config.profile_dir),
            headless=self.config.headless,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            proxy={"server": self.config.proxy_server} if self.config.proxy_server else None,
        )
        return self._context

    def _handle_login_or_expired(self, page: Page, html: str, *, artifact_name: str) -> None:
        if any(marker in html for marker in selectors.SEARCH.expired_markers):
            screenshot = self._save_screenshot(page, artifact_name)
            raise PageExpiredError(f"Xiaohongshu page is expired or unavailable: {page.url}; screenshot={screenshot}")
        if not any(marker in html for marker in selectors.SEARCH.login_markers):
            return
        if not self.config.headless:
            page.wait_for_timeout(1000)
            try:
                page.wait_for_function(
                    "(markers) => !markers.some((marker) => document.body.innerText.includes(marker))",
                    arg=list(selectors.SEARCH.login_markers),
                    timeout=self.config.manual_login_timeout_ms,
                )
            except PlaywrightTimeoutError as exc:
                screenshot = self._save_screenshot(page, artifact_name)
                raise LoginRequiredError(
                    "Xiaohongshu login is required. Complete manual login in the persistent browser profile "
                    f"and retry. screenshot={screenshot}"
                ) from exc
            return
        screenshot = self._save_screenshot(page, artifact_name)
        raise LoginRequiredError(
            "Xiaohongshu login is required. Set XHS_HEADLESS=false and complete manual login. "
            f"screenshot={screenshot}"
        )

    def _save_capture(
        self,
        *,
        artifact_name: str,
        html: str,
        json_payloads: list[dict[str, Any]],
    ) -> tuple[Path, Path | None]:
        html_path = self.config.snapshot_dir / f"{artifact_name}.html"
        html_path.write_text(html, encoding="utf-8")
        json_path = None
        if json_payloads:
            json_path = self.config.snapshot_dir / f"{artifact_name}.json"
            json_path.write_text(json.dumps(json_payloads, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return html_path, json_path

    def _save_screenshot(self, page: Page, artifact_name: str) -> Path:
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.config.screenshot_dir / f"{artifact_name}.png"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=5000)
        except Exception as exc:
            fallback_path = self.config.screenshot_dir / f"{artifact_name}.screenshot-error.txt"
            fallback_path.write_text(str(exc), encoding="utf-8")
            return fallback_path
        return screenshot_path


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _wait_for_captured_response(
    page: Page,
    json_payloads: list[dict[str, Any]],
    marker: str,
    *,
    timeout_ms: int,
) -> None:
    remaining_ms = max(timeout_ms, 0)
    while remaining_ms > 0 and not any(marker in item["url"] for item in json_payloads):
        wait_ms = min(250, remaining_ms)
        page.wait_for_timeout(wait_ms)
        remaining_ms -= wait_ms


def _merge_capture_text(html: str, json_payloads: list[dict[str, Any]]) -> str:
    if not json_payloads:
        return html
    return html + "\n" + json.dumps(json_payloads, ensure_ascii=False)


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)[:80] or "xhs"
