from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings


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
