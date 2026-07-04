from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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

    @classmethod
    def from_env(cls) -> "FeishuBitableSettings":
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", default=False)
            and not _env_bool("FEISHU_SYNC_DRY_RUN", default=False),
            app_id=_empty_to_none(os.getenv("FEISHU_APP_ID")),
            app_secret=_empty_to_none(os.getenv("FEISHU_APP_SECRET")),
            app_token=_empty_to_none(os.getenv("FEISHU_BITABLE_APP_TOKEN")),
            table_id=_empty_to_none(os.getenv("FEISHU_LEADS_TABLE_ID")),
            timeout_seconds=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "10")),
            page_size=int(os.getenv("FEISHU_SYNC_PAGE_SIZE", "100")),
        )


@dataclass(frozen=True, slots=True)
class FeishuBitableWriteResult:
    record_id: str | None
    dry_run: bool
    payload: dict[str, Any]
    response_json: dict[str, Any] | None = None


class FeishuBitableError(RuntimeError):
    pass


class FeishuBitableClient:
    def __init__(
        self,
        *,
        settings: FeishuBitableSettings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or FeishuBitableSettings.from_env()
        self._client = http_client or httpx.Client()
        self._tenant_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def upsert_record(self, record_id: str | None, fields: dict[str, Any]) -> FeishuBitableWriteResult:
        payload = {"fields": fields}
        if not self._ready():
            return FeishuBitableWriteResult(record_id=record_id, dry_run=True, payload=payload)
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
        response = self._client.get(
            self._records_url(),
            headers=self._headers(),
            timeout=self.settings.timeout_seconds,
        )
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable list failed: {data}")
        return list(data.get("data", {}).get("items") or [])

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._tenant_access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _tenant_access_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        response = self._client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret},
            timeout=self.settings.timeout_seconds,
        )
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
        return bool(
            self.settings.enabled
            and self.settings.app_id
            and self.settings.app_secret
            and self.settings.app_token
            and self.settings.table_id
        )


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
