from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from apps.worker.main import WorkerConfig
from collectors.mediacrawler import MediaCrawlerConfig
from collectors.xiaohongshu.browser import XiaohongshuBrowserConfig
from integrations.feishu.client import FeishuSettings, mask_secret
from storage.database import create_database_engine


REQUIRED_TABLES = {
    "queries",
    "collection_tasks",
    "contents",
    "comments",
    "public_profiles",
    "discovery_relations",
    "snapshots",
    "collection_events",
}

REQUIRED_UNIQUE_CONSTRAINTS = {
    "contents": "uq_contents_platform_content_id",
    "comments": "uq_comments_platform_comment_id",
    "public_profiles": "uq_public_profiles_platform_user_id",
    "discovery_relations": "uq_discovery_relations_query_id_content_id",
}


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    result: dict[str, Any] = {
        "postgresql": _check_postgresql(database_url),
        "worker": _worker_config(),
        "mediacrawler": _mediacrawler_config(),
        "playwright": _playwright_config(),
        "feishu": _feishu_config(),
    }
    result["ok"] = _overall_ok(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


def _check_postgresql(database_url: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "configured": bool(database_url),
        "database_url": _mask_database_url(database_url),
        "connected": False,
        "dialect": None,
        "current_revision": None,
        "tables": {},
        "unique_constraints": {},
        "errors": [],
    }
    try:
        engine = create_database_engine(database_url)
        payload["dialect"] = engine.dialect.name
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
            payload["connected"] = True
            try:
                payload["current_revision"] = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            except Exception as exc:  # pragma: no cover - diagnostic branch
                payload["errors"].append(f"alembic_version: {exc.__class__.__name__}")
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            payload["tables"] = {table: table in table_names for table in sorted(REQUIRED_TABLES)}
            for table, constraint in REQUIRED_UNIQUE_CONSTRAINTS.items():
                if table not in table_names:
                    payload["unique_constraints"][table] = False
                    continue
                constraints = {item["name"] for item in inspector.get_unique_constraints(table)}
                payload["unique_constraints"][table] = constraint in constraints
        engine.dispose()
    except Exception as exc:
        payload["errors"].append(str(exc))
    return payload


def _worker_config() -> dict[str, Any]:
    config = WorkerConfig.from_env()
    return {
        "worker_id": config.worker_id,
        "poll_interval_seconds": config.poll_interval_seconds,
        "task_timeout_minutes": config.task_timeout_minutes,
        "snapshot_root": str(config.snapshot_root),
        "snapshot_root_writable": _writable_dir(config.snapshot_root),
        "adapter": os.getenv("WORKER_ADAPTER", "xiaohongshu"),
        "platform": os.getenv("WORKER_PLATFORM", "xhs"),
    }


def _mediacrawler_config() -> dict[str, Any]:
    config = MediaCrawlerConfig.from_env()
    return {
        "home": str(config.home),
        "home_exists": config.home.exists(),
        "python_executable": str(config.python_executable),
        "python_executable_exists": config.python_executable.exists(),
        "output_root": str(config.output_root),
        "output_root_writable": _writable_dir(config.output_root),
        "log_dir": None if config.log_dir is None else str(config.log_dir),
        "log_dir_writable": None if config.log_dir is None else _writable_dir(config.log_dir),
        "login_type": config.login_type,
        "headless": config.headless,
        "get_comments": config.get_comments,
        "max_comments_per_note": config.max_comments_per_note,
        "proxy_configured": bool(config.proxy_server),
    }


def _playwright_config() -> dict[str, Any]:
    config = XiaohongshuBrowserConfig.from_env()
    return {
        "profile_dir": str(config.profile_dir),
        "profile_dir_writable": _writable_dir(config.profile_dir),
        "headless": config.headless,
        "snapshot_dir": str(config.snapshot_dir),
        "snapshot_dir_writable": _writable_dir(config.snapshot_dir),
        "screenshot_dir": str(config.screenshot_dir),
        "screenshot_dir_writable": _writable_dir(config.screenshot_dir),
        "page_timeout_ms": config.page_timeout_ms,
        "manual_login_timeout_ms": config.manual_login_timeout_ms,
        "proxy_configured": bool(config.proxy_server),
    }


def _feishu_config() -> dict[str, Any]:
    settings = FeishuSettings.from_env()
    return {
        "enabled": settings.enabled,
        "webhook_configured": bool(settings.webhook_url),
        "webhook_url": mask_secret(settings.webhook_url),
        "app_id_configured": bool(settings.app_id),
        "app_secret_configured": bool(settings.app_secret),
        "verification_token_configured": bool(settings.verification_token),
        "encrypt_key_configured": bool(settings.encrypt_key),
        "timeout_seconds": settings.timeout_seconds,
        "max_retries": settings.max_retries,
    }


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".check_runtime_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _mask_database_url(value: str | None) -> str | None:
    if not value:
        return None
    if "@" not in value:
        return value
    prefix, suffix = value.rsplit("@", 1)
    if ":" not in prefix:
        return value
    scheme_user = prefix.rsplit(":", 1)[0]
    return f"{scheme_user}:***@{suffix}"


def _overall_ok(result: dict[str, Any]) -> bool:
    pg = result["postgresql"]
    return bool(
        pg["connected"]
        and pg["dialect"] == "postgresql"
        and all(pg["tables"].values())
        and all(pg["unique_constraints"].values())
        and result["worker"]["snapshot_root_writable"]
        and result["mediacrawler"]["home_exists"]
        and result["mediacrawler"]["python_executable_exists"]
        and result["mediacrawler"]["output_root_writable"]
        and result["playwright"]["profile_dir_writable"]
        and result["playwright"]["snapshot_dir_writable"]
        and result["playwright"]["screenshot_dir_writable"]
    )


if __name__ == "__main__":
    main()
