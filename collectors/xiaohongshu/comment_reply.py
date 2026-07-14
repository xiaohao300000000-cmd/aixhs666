from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from collectors.xiaohongshu import selectors
from collectors.xiaohongshu.browser import XiaohongshuBrowser, XiaohongshuBrowserConfig
from collectors.xiaohongshu.exceptions import XiaohongshuCommentReplyDefiniteFailure
from integrations.feishu.comment_replies import CommentReplySendResult, CommentReplySender


class XiaohongshuCommentReplySender(CommentReplySender):
    """Reply once after explicit live selector acceptance; otherwise fail closed."""

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
        target_url: str | None,
        text: str,
    ) -> CommentReplySendResult:
        browser = self._browser_factory()
        page: Any | None = None
        click_started = False
        captured_responses: list[dict[str, Any]] = []
        try:
            url = _target_url(target_url, platform_content_id)
            page = browser._new_page()
            page.on("response", lambda response: _capture_reply_response(response, captured_responses, click_started))
            page.goto(url, wait_until="domcontentloaded", timeout=browser.config.page_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=browser.config.page_timeout_ms)
            except PlaywrightTimeoutError:
                pass

            html = page.content()
            browser._handle_login_or_expired(page, html, artifact_name=f"comment-reply-{platform_comment_id}")
            _raise_for_captcha(html)
            target = _target_container(page, platform_comment_id)
            trigger = target.locator(selectors.COMMENT_REPLY_TRIGGER_SELECTOR)
            _require_one(trigger, "target reply trigger")
            trigger.first.click(timeout=browser.config.page_timeout_ms)

            editor = target.locator(selectors.COMMENT_REPLY_EDITOR_SELECTOR)
            editor.first.wait_for(state="visible", timeout=browser.config.page_timeout_ms)
            _require_one(editor, "target reply editor")
            submit = target.locator(selectors.COMMENT_REPLY_SUBMIT_SELECTOR)
            submit.first.wait_for(state="visible", timeout=browser.config.page_timeout_ms)
            _require_one(submit, "target reply submit control")
            if not submit.first.is_visible(timeout=browser.config.page_timeout_ms):
                raise XiaohongshuCommentReplyDefiniteFailure("target reply submit control is not visible")

            editor.first.fill(text, timeout=browser.config.page_timeout_ms)
            previous_target_replies = Counter(target.locator(selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR).all_inner_texts())

            # From this point a Playwright click failure may mean submission reached XHS.
            click_started = True
            submit.first.click(timeout=browser.config.page_timeout_ms)
            try:
                page.wait_for_timeout(700)
            except PlaywrightTimeoutError:
                return _unknown("reply submission completed without conclusive evidence")

            response_result = _reply_response_result(captured_responses)
            if response_result is not None:
                return response_result
            current_target_replies = Counter(target.locator(selectors.COMMENT_REPLY_VISIBLE_TEXT_SELECTOR).all_inner_texts())
            if current_target_replies[text] > previous_target_replies[text]:
                return CommentReplySendResult(
                    outcome="sent",
                    response_json={"success_evidence": "visible_target_reply"},
                )
            return _unknown("reply submission completed without correlated success evidence")
        except XiaohongshuCommentReplyDefiniteFailure:
            raise
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            if click_started:
                return _unknown(_sanitize_error(exc))
            raise XiaohongshuCommentReplyDefiniteFailure(
                f"Xiaohongshu reply was not submitted: {_sanitize_error(exc)}"
            ) from exc
        except Exception as exc:
            if click_started:
                return _unknown(_sanitize_error(exc))
            raise XiaohongshuCommentReplyDefiniteFailure(
                f"Xiaohongshu reply was not submitted: {_sanitize_error(exc)}"
            ) from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
            try:
                browser.close()
            except Exception:
                pass


def _target_url(target_url: str | None, platform_content_id: str) -> str:
    if target_url is None or not target_url.strip():
        return selectors.CONTENT_URL_TEMPLATE.format(platform_content_id=platform_content_id)
    normalized = target_url.strip()
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not hostname or (hostname != "xiaohongshu.com" and not hostname.endswith(".xiaohongshu.com")):
        raise XiaohongshuCommentReplyDefiniteFailure("stored canonical target URL is not an https Xiaohongshu URL")
    return normalized


def _target_container(page: Any, platform_comment_id: str) -> Any:
    escaped_id = _css_attribute_value(platform_comment_id)
    matches = [page.locator(template.format(platform_comment_id=escaped_id)) for template in selectors.COMMENT_TARGET_CONTAINER_TEMPLATES]
    total_matches = sum(locator.count() for locator in matches)
    if total_matches != 1:
        raise XiaohongshuCommentReplyDefiniteFailure(
            f"exact target comment {platform_comment_id!r} is missing or ambiguous"
        )
    return next(locator.first for locator in matches if locator.count() == 1)


def inspect_comment_reply_selectors(
    page: Any,
    *,
    platform_comment_id: str,
    expand_reply: bool = False,
    timeout_ms: int = 30_000,
) -> dict[str, int]:
    """Inspect only; real platform acceptance is required before live sending."""
    escaped_id = _css_attribute_value(platform_comment_id)
    report: dict[str, int] = {}
    for template in selectors.COMMENT_TARGET_CONTAINER_TEMPLATES:
        selector = template.format(platform_comment_id=escaped_id)
        container = page.locator(selector)
        report[selector] = container.count()
        if container.count() == 1:
            trigger = container.locator(selectors.COMMENT_REPLY_TRIGGER_SELECTOR)
            report[f"{selector} >> {selectors.COMMENT_REPLY_TRIGGER_SELECTOR}"] = trigger.count()
            if expand_reply and trigger.count() == 1:
                trigger.first.click(timeout=timeout_ms)
            report[f"{selector} >> {selectors.COMMENT_REPLY_EDITOR_SELECTOR}"] = container.locator(
                selectors.COMMENT_REPLY_EDITOR_SELECTOR
            ).count()
            report[f"{selector} >> {selectors.COMMENT_REPLY_SUBMIT_SELECTOR}"] = container.locator(
                selectors.COMMENT_REPLY_SUBMIT_SELECTOR
            ).count()
    return report


def _require_one(locator: Any, description: str) -> None:
    if locator.count() != 1:
        raise XiaohongshuCommentReplyDefiniteFailure(f"{description} is missing or ambiguous")


def _raise_for_captcha(html: str) -> None:
    captcha_markers = tuple(marker for marker in selectors.COMMENT_REPLY_LOGIN_OR_CAPTCHA_MARKERS if marker not in selectors.SEARCH.login_markers)
    if any(marker in html for marker in captcha_markers):
        raise XiaohongshuCommentReplyDefiniteFailure("Xiaohongshu captcha is required before replying")


def _capture_reply_response(response: Any, captured: list[dict[str, Any]], click_started: bool) -> None:
    if not click_started:
        return
    response_url = str(getattr(response, "url", ""))
    if not any(marker in response_url for marker in selectors.COMMENT_REPLY_RESPONSE_URL_MARKERS):
        return
    try:
        payload = response.json()
    except Exception:
        return
    if isinstance(payload, dict):
        captured.append({"url": response_url, "payload": payload})


def _reply_response_result(captured: list[dict[str, Any]]) -> CommentReplySendResult | None:
    for item in captured:
        payload = item["payload"]
        success = payload.get("success") is True or payload.get("code") in {0, "0"}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        reply_id = _first_string(data, ("comment_id", "commentId", "id"))
        if success and reply_id:
            return CommentReplySendResult(
                outcome="sent",
                platform_reply_id=reply_id,
                response_json=item,
            )
        if not success:
            return CommentReplySendResult(outcome="failed", response_json=item, error=_platform_error(payload))
    return None


def _first_string(values: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _platform_error(payload: dict[str, Any]) -> str:
    for key in ("msg", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _sanitize_error(value)
    return "Xiaohongshu rejected the comment reply"


def _unknown(error: str) -> CommentReplySendResult:
    return CommentReplySendResult(outcome="result_unknown", error=_sanitize_error(error))


def _sanitize_error(error: object) -> str:
    return " ".join(str(error).split())[:500] or "Xiaohongshu reply error"


def _css_attribute_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
