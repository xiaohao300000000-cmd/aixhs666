from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class FeishuSettings:
    enabled: bool
    webhook_url: str | None
    app_id: str | None
    app_secret: str | None
    verification_token: str | None
    encrypt_key: str | None
    timeout_seconds: float = 10
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "FeishuSettings":
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", default=False),
            webhook_url=_empty_to_none(os.getenv("FEISHU_WEBHOOK_URL")),
            app_id=_empty_to_none(os.getenv("FEISHU_APP_ID")),
            app_secret=_empty_to_none(os.getenv("FEISHU_APP_SECRET")),
            verification_token=_empty_to_none(os.getenv("FEISHU_VERIFICATION_TOKEN")),
            encrypt_key=_empty_to_none(os.getenv("FEISHU_ENCRYPT_KEY")),
            timeout_seconds=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "10")),
            max_retries=int(os.getenv("FEISHU_MAX_RETRIES", "2")),
        )


@dataclass(frozen=True, slots=True)
class FeishuSendResult:
    sent: bool
    dry_run: bool
    status_code: int | None
    response_json: dict[str, Any] | None = None
    error: str | None = None


class FeishuAPIError(RuntimeError):
    """Raised when Feishu transport returns a non-retryable error."""


class FeishuClient:
    def __init__(
        self,
        *,
        settings: FeishuSettings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or FeishuSettings.from_env()
        self._client = http_client
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def send_webhook(self, payload: dict[str, Any], *, dry_run: bool | None = None) -> FeishuSendResult:
        effective_dry_run = (not self.settings.enabled) if dry_run is None else dry_run
        if effective_dry_run:
            return FeishuSendResult(sent=False, dry_run=True, status_code=None, response_json={"payload": payload})

        if not self.settings.webhook_url:
            return FeishuSendResult(sent=False, dry_run=True, status_code=None, error="FEISHU_WEBHOOK_URL is not set")

        last_error: str | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._http_client().post(
                    self.settings.webhook_url,
                    json=payload,
                    timeout=self.settings.timeout_seconds,
                )
                response_json = _response_json(response)
                if 200 <= response.status_code < 300:
                    return FeishuSendResult(
                        sent=True,
                        dry_run=False,
                        status_code=response.status_code,
                        response_json=response_json,
                    )
                last_error = _transport_error(response.status_code, response_json, self.settings.webhook_url)
                if response.status_code < 500 or attempt >= self.settings.max_retries:
                    raise FeishuAPIError(last_error)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"Feishu request failed for {mask_secret(self.settings.webhook_url)}: {exc.__class__.__name__}"
                if attempt >= self.settings.max_retries:
                    return FeishuSendResult(sent=False, dry_run=False, status_code=None, error=last_error)
            time.sleep(min(0.25 * (attempt + 1), 1.0))

        return FeishuSendResult(sent=False, dry_run=False, status_code=None, error=last_error)

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client()
        return self._client


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}...{value[-4:]}"


def _transport_error(status_code: int, response_json: dict[str, Any] | None, url: str) -> str:
    message = response_json.get("msg") if response_json else None
    if not message and response_json:
        message = response_json.get("message") or response_json.get("error")
    return f"Feishu webhook returned HTTP {status_code} for {mask_secret(url)}: {message or 'unknown error'}"


def _response_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


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
