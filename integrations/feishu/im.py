from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from integrations.feishu.client import mask_secret


@dataclass(frozen=True, slots=True)
class FeishuIMSettings:
    enabled: bool
    app_id: str | None
    app_secret: str | None
    review_chat_id: str | None
    timeout_seconds: float = 10
    max_retries: int = 2
    transport: str = "openapi"
    lark_cli_bin: str = "lark-cli"
    lark_cli_as: str = "user"

    @classmethod
    def from_env(cls) -> "FeishuIMSettings":
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", default=False),
            app_id=_empty_to_none(os.getenv("FEISHU_APP_ID")),
            app_secret=_empty_to_none(os.getenv("FEISHU_APP_SECRET")),
            review_chat_id=_empty_to_none(os.getenv("FEISHU_LLM_REVIEW_CHAT_ID")),
            timeout_seconds=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "10")),
            max_retries=int(os.getenv("FEISHU_MAX_RETRIES", "2")),
            transport=os.getenv("FEISHU_IM_TRANSPORT", "openapi").strip() or "openapi",
            lark_cli_bin=os.getenv("FEISHU_LARK_CLI_BIN", "lark-cli"),
            lark_cli_as=os.getenv("FEISHU_LARK_CLI_AS", "user"),
        )


class FeishuIMError(RuntimeError):
    pass


CommandRunner = Callable[[list[str], str | None], str]


class FeishuIMClient:
    def __init__(
        self,
        *,
        settings: FeishuIMSettings | None = None,
        http_client: httpx.Client | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.settings = settings or FeishuIMSettings.from_env()
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._tenant_token: str | None = None
        self._command_runner = command_runner or self._run_command

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        if not self._ready():
            raise FeishuIMError("Feishu IM is not configured")
        if self.settings.transport == "lark_cli":
            return self._lark_cli_send_interactive_card(chat_id=chat_id, card=card)
        response = self._request(
            "POST",
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            json_body={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            },
            operation="send interactive card",
        )
        message = response.get("data", {}).get("message", {})
        message_id = message.get("message_id") or response.get("data", {}).get("message_id")
        returned_chat_id = message.get("chat_id") or chat_id
        if not message_id:
            raise FeishuIMError(f"Feishu send interactive card returned no message_id: {_mask_response(response, self.settings)}")
        return {"message_id": str(message_id), "chat_id": str(returned_chat_id)}

    def update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        if not self._ready():
            raise FeishuIMError("Feishu IM is not configured")
        if self.settings.transport == "lark_cli":
            return self._lark_cli_update_interactive_card(token=token, card=card)
        return self._request(
            "POST",
            "https://open.feishu.cn/open-apis/interactive/v1/card/update",
            json_body={"token": token, "card": card},
            operation="update interactive card",
        )

    def patch_interactive_message(self, *, message_id: str, card: dict[str, Any]) -> dict[str, Any]:
        if not self._ready():
            raise FeishuIMError("Feishu IM is not configured")
        content = json.dumps(card, ensure_ascii=False, separators=(",", ":"))
        if self.settings.transport == "lark_cli":
            return self._run_lark_cli_json([
                self.settings.lark_cli_bin, "api", "PATCH", f"/open-apis/im/v1/messages/{message_id}",
                "--as", self.settings.lark_cli_as, "--data", json.dumps({"content": content}, ensure_ascii=False, separators=(",", ":")),
            ], "patch interactive message")
        return self._request("PATCH", f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}", json_body={"content": content}, operation="patch interactive message")

    def _ready(self) -> bool:
        if self.settings.transport == "lark_cli":
            return bool(self.settings.enabled and self.settings.lark_cli_bin)
        return bool(self.settings.enabled and self.settings.app_id and self.settings.app_secret)

    def _lark_cli_send_interactive_card(self, *, chat_id: str, card: dict[str, Any]) -> dict[str, str]:
        args = [
            self.settings.lark_cli_bin,
            "im",
            "+messages-send",
            "--chat-id",
            chat_id,
            "--msg-type",
            "interactive",
            "--content",
            json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            "--as",
            self.settings.lark_cli_as,
            "--json",
        ]
        data = self._run_lark_cli_json(args, "send interactive card")
        message = data.get("data", {}).get("message", {})
        message_id = message.get("message_id") or data.get("data", {}).get("message_id")
        returned_chat_id = message.get("chat_id") or chat_id
        if not message_id:
            raise FeishuIMError(f"Feishu lark-cli send returned no message_id: {_mask_response(data, self.settings)}")
        return {"message_id": str(message_id), "chat_id": str(returned_chat_id)}

    def _lark_cli_update_interactive_card(self, *, token: str, card: dict[str, Any]) -> dict[str, Any]:
        args = [
            self.settings.lark_cli_bin,
            "api",
            "POST",
            "/open-apis/interactive/v1/card/update",
            "--as",
            "bot",
            "--data",
            json.dumps({"token": token, "card": card}, ensure_ascii=False, separators=(",", ":")),
        ]
        return self._run_lark_cli_json(args, "update interactive card")

    def _run_lark_cli_json(self, args: list[str], operation: str) -> dict[str, Any]:
        try:
            output = self._command_runner(args, None)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FeishuIMError(f"Feishu lark-cli {operation} failed: {exc}") from exc
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise FeishuIMError(f"Feishu lark-cli {operation} returned non-JSON output") from exc
        if not isinstance(data, dict):
            raise FeishuIMError(f"Feishu lark-cli {operation} returned invalid JSON output")
        if data.get("ok") is False or data.get("code") not in (None, 0):
            raise FeishuIMError(f"Feishu lark-cli {operation} failed: {_mask_response(data, self.settings)}")
        return data

    def _run_command(self, args: list[str], stdin: str | None = None) -> str:
        env = {
            **os.environ,
            "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
            "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
        }
        completed = subprocess.run(
            args,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.settings.timeout_seconds,
            env=env,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
            raise subprocess.CalledProcessError(completed.returncode, args, output=completed.stdout, stderr=detail)
        return completed.stdout

    def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: str | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                    timeout=self.settings.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = f"Feishu IM {operation} request failed: {exc.__class__.__name__}"
                if attempt >= self.settings.max_retries:
                    raise FeishuIMError(last_error) from exc
                time.sleep(min(0.25 * (attempt + 1), 1.0))
                continue
            data = _json(response)
            if response.status_code < 300 and data.get("code", 0) == 0:
                return data
            last_error = f"Feishu IM {operation} failed: {_mask_response(data, self.settings)}"
            if response.status_code < 500 or attempt >= self.settings.max_retries:
                raise FeishuIMError(last_error)
            time.sleep(min(0.25 * (attempt + 1), 1.0))
        raise FeishuIMError(last_error or f"Feishu IM {operation} failed")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tenant_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _tenant_access_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        try:
            response = self._client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret},
                timeout=self.settings.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise FeishuIMError(f"Feishu token request failed: {exc.__class__.__name__}") from exc
        data = _json(response)
        token = data.get("tenant_access_token")
        if response.status_code >= 300 or not token:
            raise FeishuIMError(f"Feishu token request failed: {_mask_response(data, self.settings)}")
        self._tenant_token = str(token)
        return self._tenant_token


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise FeishuIMError("Feishu returned non-JSON response") from exc
    return data if isinstance(data, dict) else {}


def _mask_response(data: dict[str, Any], settings: FeishuIMSettings) -> str:
    text = json.dumps(data, ensure_ascii=False)
    for value in (settings.app_id, settings.app_secret, settings.review_chat_id):
        if value:
            text = text.replace(value, mask_secret(value))
    return text


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
