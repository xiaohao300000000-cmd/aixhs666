import httpx
import pytest

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableError, FeishuBitableSettings


def test_bitable_client_dry_run_returns_payload_without_network() -> None:
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=False,
            app_id=None,
            app_secret=None,
            app_token=None,
            table_id=None,
        )
    )

    result = client.upsert_record(None, {"客户": "福州家长", "状态": "待确认"})

    assert result.dry_run is True
    assert result.record_id is None
    assert result.payload["fields"]["客户"] == "福州家长"


def test_bitable_settings_from_env_reads_table(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_xxx")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "base_token")
    monkeypatch.setenv("FEISHU_LEADS_TABLE_ID", "tbl123")

    settings = FeishuBitableSettings.from_env()

    assert settings.enabled is True
    assert settings.app_token == "base_token"
    assert settings.table_id == "tbl123"


def test_bitable_settings_from_env_forces_dry_run_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_SYNC_DRY_RUN", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_xxx")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "base_token")
    monkeypatch.setenv("FEISHU_LEADS_TABLE_ID", "tbl123")

    settings = FeishuBitableSettings.from_env()

    client = FeishuBitableClient(settings=settings, http_client=_FailingClient())
    result = client.upsert_record(None, {"客户": "福州家长"})

    assert settings.enabled is False
    assert result.dry_run is True
    assert client.list_records() == []


def test_bitable_client_with_incomplete_credentials_stays_offline() -> None:
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=True,
            app_id="cli_xxx",
            app_secret=None,
            app_token=None,
            table_id=None,
        ),
        http_client=_FailingClient(),
    )

    upsert = client.upsert_record(None, {"客户": "福州家长"})
    listed = client.list_records()

    assert upsert.dry_run is True
    assert listed == []


def test_bitable_client_masks_transport_errors_in_token_request() -> None:
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=True,
            app_id="cli_xxx",
            app_secret="super-secret",
            app_token="app_token_123456",
            table_id="tbl_id_987654",
        ),
        http_client=_TimeoutingClient(token_error=True),
    )

    with pytest.raises(FeishuBitableError) as exc_info:
        client.upsert_record(None, {"客户": "福州家长"})

    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" not in message
    assert "app_token_123456" not in message
    assert "tbl_id_987654" not in message
    assert "app_token=app_toke...3456" in message
    assert "table_id=tbl_id_9...7654" in message


def test_bitable_client_uses_page_size_and_masks_request_errors() -> None:
    requests: list[httpx.Request] = []
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=True,
            app_id="cli_xxx",
            app_secret="super-secret",
            app_token="app_token_123456",
            table_id="tbl_id_987654",
            page_size=42,
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(_records_handler(requests, fail_with_timeout=True))),
    )

    with pytest.raises(FeishuBitableError) as exc_info:
        client.list_records()

    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "https://open.feishu.cn/open-apis/bitable/v1/apps/app_token_123456/tables/tbl_id_987654/records" not in message
    assert "app_token=app_toke...3456" in message
    assert "table_id=tbl_id_9...7654" in message
    assert requests[1].url.params["page_size"] == "42"


def test_bitable_client_masks_request_errors_on_upsert() -> None:
    requests: list[httpx.Request] = []
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=True,
            app_id="cli_xxx",
            app_secret="super-secret",
            app_token="app_token_123456",
            table_id="tbl_id_987654",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(_upsert_handler(requests))),
    )

    with pytest.raises(FeishuBitableError) as exc_info:
        client.upsert_record(None, {"客户": "福州家长"})

    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "https://open.feishu.cn/open-apis/bitable/v1/apps/app_token_123456/tables/tbl_id_987654/records" not in message
    assert "app_token=app_toke...3456" in message
    assert "table_id=tbl_id_9...7654" in message
    assert len(requests) == 2


def test_bitable_client_external_http_client_is_not_closed() -> None:
    client_handle = _ClosableClient()
    client = FeishuBitableClient(
        settings=FeishuBitableSettings(
            enabled=False,
            app_id=None,
            app_secret=None,
            app_token=None,
            table_id=None,
        ),
        http_client=client_handle,
    )

    client.close()

    assert client_handle.closed is False


class _FailingClient:
    def post(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network access is not expected")

    def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network access is not expected")

    def close(self) -> None:
        pass


class _ClosableClient(_FailingClient):
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _TimeoutingClient:
    def __init__(self, *, token_error: bool = False) -> None:
        self.token_error = token_error
        self._token_requested = False

    def post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", str(url))
        if self.token_error and not self._token_requested:
            self._token_requested = True
            raise httpx.ReadTimeout("timed out", request=request)
        self._token_requested = True
        if "tenant_access_token" in str(url):
            return httpx.Response(200, json={"tenant_access_token": "tenant-token"}, request=request)
        return httpx.Response(200, json={"code": 0, "data": {"record": {"record_id": "record-1"}}}, request=request)

    def get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("GET", str(url))
        raise httpx.ReadTimeout("timed out", request=request)

    def close(self) -> None:
        pass


def _records_handler(requests: list[httpx.Request], *, fail_with_timeout: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"tenant_access_token": "tenant-token"}, request=request)
        if fail_with_timeout:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"code": 0, "data": {"items": []}}, request=request)

    return handler


def _upsert_handler(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={"tenant_access_token": "tenant-token"}, request=request)
        raise httpx.ReadTimeout("timed out", request=request)

    return handler
