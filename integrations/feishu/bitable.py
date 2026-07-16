from __future__ import annotations

import os
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

import httpx


@dataclass(frozen=True, slots=True)
class FeishuBitableSettings:
    enabled: bool
    app_id: str | None
    app_secret: str | None
    app_token: str | None
    table_id: str | None
    timeout_seconds: float = 10
    page_size: int = 100
    transport: str = "openapi"
    lark_cli_bin: str = "lark-cli"
    lark_cli_as: str = "user"

    @classmethod
    def from_env(cls) -> "FeishuBitableSettings":
        transport = os.getenv("FEISHU_BITABLE_TRANSPORT", "openapi").strip() or "openapi"
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", default=False)
            and not _env_bool("FEISHU_SYNC_DRY_RUN", default=False),
            app_id=_empty_to_none(os.getenv("FEISHU_APP_ID")),
            app_secret=_empty_to_none(os.getenv("FEISHU_APP_SECRET")),
            app_token=_empty_to_none(os.getenv("FEISHU_BITABLE_APP_TOKEN")),
            table_id=_empty_to_none(os.getenv("FEISHU_LEADS_TABLE_ID")),
            timeout_seconds=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "10")),
            page_size=int(os.getenv("FEISHU_SYNC_PAGE_SIZE", "100")),
            transport=transport,
            lark_cli_bin=os.getenv("FEISHU_LARK_CLI_BIN", "lark-cli"),
            lark_cli_as=os.getenv("FEISHU_LARK_CLI_AS", "user"),
        )

    @classmethod
    def from_customer_followup_env(cls) -> "FeishuBitableSettings":
        settings = cls.from_env()
        return cls(
            enabled=settings.enabled,
            app_id=settings.app_id,
            app_secret=settings.app_secret,
            app_token=_empty_to_none(os.getenv("FEISHU_CUSTOMER_FOLLOWUP_APP_TOKEN")),
            table_id=_empty_to_none(os.getenv("FEISHU_CUSTOMER_FOLLOWUP_TABLE_ID")),
            timeout_seconds=settings.timeout_seconds,
            page_size=settings.page_size,
            transport=settings.transport,
            lark_cli_bin=settings.lark_cli_bin,
            lark_cli_as=settings.lark_cli_as,
        )

    @classmethod
    def from_customer_crm_env(cls) -> "FeishuBitableSettings":
        return cls._from_named_table_env("FEISHU_CUSTOMER_CRM_TABLE_ID")

    @classmethod
    def from_customer_followup_record_env(cls) -> "FeishuBitableSettings":
        return cls._from_named_table_env("FEISHU_CUSTOMER_FOLLOWUP_RECORD_TABLE_ID")

    @classmethod
    def _from_named_table_env(cls, table_env_name: str) -> "FeishuBitableSettings":
        settings = cls.from_env()
        return cls(
            enabled=settings.enabled,
            app_id=settings.app_id,
            app_secret=settings.app_secret,
            app_token=_empty_to_none(os.getenv("FEISHU_CUSTOMER_CRM_APP_TOKEN")) or settings.app_token,
            table_id=_empty_to_none(os.getenv(table_env_name)),
            timeout_seconds=settings.timeout_seconds,
            page_size=settings.page_size,
            transport=settings.transport,
            lark_cli_bin=settings.lark_cli_bin,
            lark_cli_as=settings.lark_cli_as,
        )


@dataclass(frozen=True, slots=True)
class FeishuBitableWriteResult:
    record_id: str | None
    dry_run: bool
    payload: dict[str, Any]
    response_json: dict[str, Any] | None = None


class FeishuBitableError(RuntimeError):
    pass


CommandRunner = Callable[[list[str], str | None], str]


class FeishuBitableClient:
    def __init__(
        self,
        *,
        settings: FeishuBitableSettings | None = None,
        http_client: httpx.Client | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.settings = settings or FeishuBitableSettings.from_env()
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._tenant_token: str | None = None
        self._command_runner = command_runner or self._run_command

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def upsert_record(self, record_id: str | None, fields: dict[str, Any]) -> FeishuBitableWriteResult:
        payload = {"fields": fields}
        if not self._ready():
            return FeishuBitableWriteResult(record_id=record_id, dry_run=True, payload=payload)
        if self.settings.transport == "lark_cli":
            return self._lark_cli_upsert_record(record_id, fields, payload)
        try:
            if record_id:
                response = self._client.put(
                    self._record_url(record_id),
                    json=payload,
                    headers=self._headers(),
                    timeout=self.settings.timeout_seconds,
                )
            else:
                response = self._client.post(
                    self._records_url(),
                    json=payload,
                    headers=self._headers(),
                    timeout=self.settings.timeout_seconds,
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise FeishuBitableError(self._request_error("write", exc)) from exc
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable write failed: {data}")
        new_record_id = record_id or data.get("data", {}).get("record", {}).get("record_id")
        return FeishuBitableWriteResult(
            record_id=new_record_id,
            dry_run=False,
            payload=payload,
            response_json=data,
        )

    def list_records(self) -> list[dict[str, Any]]:
        if not self._ready():
            return []
        if self.settings.transport == "lark_cli":
            return self._lark_cli_list_records()
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": self.settings.page_size}
            if page_token:
                params["page_token"] = page_token
            data = self._openapi_get_records(params, operation="list")
            inner = data.get("data", {})
            records.extend(record for record in inner.get("items") or [] if isinstance(record, dict))
            if not inner.get("has_more"):
                return records
            page_token = _empty_to_none(inner.get("page_token"))
            if page_token is None:
                raise FeishuBitableError("Feishu Bitable list reported has_more without page_token")

    def find_records_by_exact_field(self, field_name: str, value: str) -> list[dict[str, Any]]:
        if not self._ready():
            return []
        if self.settings.transport == "lark_cli":
            return self._lark_cli_find_records_by_exact_field(field_name, value)
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": field_name, "operator": "is", "value": [value]}],
            }
        }
        try:
            response = self._client.post(
                f"{self._records_url()}/search",
                params={"page_size": 2},
                json=payload,
                headers=self._headers(),
                timeout=self.settings.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise FeishuBitableError(self._request_error("exact search", exc)) from exc
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable exact search failed: {data}")
        inner = data.get("data", {})
        if inner.get("has_more"):
            raise FeishuBitableError("Feishu Bitable exact search returned more than two matches")
        return [record for record in inner.get("items") or [] if isinstance(record, dict) and _field_equals(record, field_name, value)]

    def _openapi_get_records(self, params: dict[str, Any], *, operation: str) -> dict[str, Any]:
        try:
            response = self._client.get(
                self._records_url(),
                params=params,
                headers=self._headers(),
                timeout=self.settings.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise FeishuBitableError(self._request_error(operation, exc)) from exc
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable {operation} failed: {data}")
        return data

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
            raise FeishuBitableError(self._request_error("token", exc)) from exc
        data = _json(response)
        token = data.get("tenant_access_token")
        if response.status_code >= 300 or not token:
            raise FeishuBitableError(f"Feishu token request failed: {data}")
        self._tenant_token = str(token)
        return self._tenant_token

    def _records_url(self) -> str:
        return (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/"
            f"{self.settings.app_token}/tables/{self.settings.table_id}/records"
        )

    def _record_url(self, record_id: str) -> str:
        return f"{self._records_url()}/{record_id}"

    def _ready(self) -> bool:
        if self.settings.transport == "lark_cli":
            return bool(
                self.settings.enabled
                and self.settings.app_token
                and self.settings.table_id
                and self.settings.lark_cli_bin
            )
        return bool(
            self.settings.enabled
            and self.settings.app_id
            and self.settings.app_secret
            and self.settings.app_token
            and self.settings.table_id
        )

    def _request_error(self, operation: str, exc: Exception) -> str:
        return (
            "Feishu Bitable "
            f"{operation} request failed for app_token={mask_secret(self.settings.app_token)} "
            f"table_id={mask_secret(self.settings.table_id)}: {exc.__class__.__name__}"
        )

    def _lark_cli_upsert_record(
        self,
        record_id: str | None,
        fields: dict[str, Any],
        payload: dict[str, Any],
    ) -> FeishuBitableWriteResult:
        args = self._base_cli_args("+record-upsert") + [
            "--json",
            json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
            "--as",
            self.settings.lark_cli_as,
        ]
        if record_id:
            args.extend(["--record-id", record_id])
        data = self._run_lark_cli_json(args, "write")
        returned_record = data.get("data", {}).get("record", {})
        new_record_id = (
            record_id
            or returned_record.get("record_id")
            or _first(returned_record.get("record_id_list"))
            or data.get("data", {}).get("record_id")
        )
        return FeishuBitableWriteResult(
            record_id=str(new_record_id) if new_record_id else record_id,
            dry_run=False,
            payload=payload,
            response_json=data,
        )

    def _lark_cli_list_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            args = self._base_cli_args("+record-list") + [
                "--limit",
                str(self.settings.page_size),
                "--format",
                "json",
                "--as",
                self.settings.lark_cli_as,
            ]
            if offset:
                args.extend(["--offset", str(offset)])
            page = self._normalize_cli_records(self._run_lark_cli_json(args, "list"))
            records.extend(page)
            if len(page) < self.settings.page_size:
                return records
            offset += len(page)

    def _lark_cli_find_records_by_exact_field(self, field_name: str, value: str) -> list[dict[str, Any]]:
        args = self._base_cli_args("+record-list") + [
            "--filter-json",
            json.dumps({"logic": "and", "conditions": [[field_name, "==", value]]}, ensure_ascii=False, separators=(",", ":")),
            "--field-id",
            field_name,
            "--offset",
            "0",
            "--limit",
            "2",
            "--format",
            "json",
            "--as",
            self.settings.lark_cli_as,
        ]
        records = self._normalize_cli_records(self._run_lark_cli_json(args, "exact search"))
        return [record for record in records if _field_equals(record, field_name, value)]

    def _normalize_cli_records(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        inner = data.get("data", {})
        records = inner.get("records") or inner.get("items")
        if isinstance(records, list):
            return [record for record in records if isinstance(record, dict)]

        field_names = inner.get("fields") or []
        rows = inner.get("data") or []
        record_ids = inner.get("record_id_list") or []
        normalized: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            record_id = record_ids[index] if index < len(record_ids) else None
            normalized.append(
                {
                    "record_id": record_id,
                    "fields": {str(field): value for field, value in zip(field_names, row, strict=False)},
                }
            )
        return normalized

    def _base_cli_args(self, command: str) -> list[str]:
        return [
            self.settings.lark_cli_bin,
            "base",
            command,
            "--base-token",
            str(self.settings.app_token),
            "--table-id",
            str(self.settings.table_id),
        ]

    def _run_lark_cli_json(self, args: list[str], operation: str) -> dict[str, Any]:
        try:
            output = self._command_runner(args, None)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FeishuBitableError(self._request_error(operation, exc)) from exc
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise FeishuBitableError(f"Feishu lark-cli {operation} returned non-JSON output") from exc
        if not isinstance(data, dict):
            raise FeishuBitableError(f"Feishu lark-cli {operation} returned invalid JSON output")
        if data.get("ok") is False or data.get("code") not in (None, 0):
            raise FeishuBitableError(f"Feishu lark-cli {operation} failed: {_mask_cli_output(data, self.settings)}")
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


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise FeishuBitableError("Feishu returned non-JSON response") from exc
    return data if isinstance(data, dict) else {}


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


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


def _field_equals(record: dict[str, Any], field_name: str, value: str) -> bool:
    fields = record.get("fields")
    return isinstance(fields, dict) and str(fields.get(field_name) or "") == value


def _mask_cli_output(data: dict[str, Any], settings: FeishuBitableSettings) -> str:
    text = json.dumps(data, ensure_ascii=False)
    for value in (settings.app_id, settings.app_secret, settings.app_token, settings.table_id):
        if value:
            text = text.replace(value, mask_secret(value))
    return text


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}...{value[-4:]}"
