from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import storage.models  # noqa: F401
from sqlalchemy import inspect, text

from collectors.mediacrawler.adapter import MediaCrawlerConfig
from collectors.xiaohongshu.browser import XiaohongshuBrowserConfig
from storage.database import create_database_engine
from storage.settings import get_settings


REQUIRED_TABLES = {
    "queries",
    "collection_tasks",
    "contents",
    "comments",
    "public_profiles",
    "discovery_relations",
    "snapshots",
    "collection_events",
    "worker_heartbeats",
}


def main() -> None:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    if not report["ok"]:
        raise SystemExit(1)


def build_report() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    ok = True
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            connection.execute(text("select 1")).scalar_one()
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            revision = connection.execute(text("select version_num from alembic_version")).scalar_one_or_none()
            constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("discovery_relations")
                if constraint.get("name")
            }
        checks["postgresql"] = {"ok": True, "database_url": _mask_url(settings.database_url)}
        checks["migration"] = {"ok": revision is not None, "revision": revision}
        checks["tables"] = {"ok": REQUIRED_TABLES.issubset(tables), "missing": sorted(REQUIRED_TABLES - tables)}
        checks["constraints"] = {
            "ok": "uq_discovery_relations_query_id_content_id" in constraints,
            "discovery_relation_unique": "uq_discovery_relations_query_id_content_id" in constraints,
        }
    except Exception as exc:
        ok = False
        checks["postgresql"] = {"ok": False, "error": str(exc), "database_url": _mask_url(settings.database_url)}
    finally:
        engine.dispose()

    media_config = MediaCrawlerConfig.from_env()
    xhs_config = XiaohongshuBrowserConfig.from_env()
    checks["worker"] = {
        "ok": True,
        "adapter": os.getenv("WORKER_ADAPTER", "mediacrawler"),
        "worker_id": os.getenv("WORKER_ID"),
        "snapshot_root": os.getenv("WORKER_SNAPSHOT_ROOT", ".runtime/storage-snapshots"),
    }
    mediacrawler_profile_dir = media_config.home / "browser_data" / (media_config.user_data_dir % "xhs")
    checks["mediacrawler"] = {
        "ok": media_config.home.exists() and media_config.python_executable.exists(),
        "home": str(media_config.home),
        "python": str(media_config.python_executable),
        "output_root": str(media_config.output_root),
        "headless": media_config.headless,
        "enable_cdp_mode": media_config.enable_cdp_mode,
        "cdp_connect_existing": media_config.cdp_connect_existing,
        "cdp_debug_port": media_config.cdp_debug_port,
        "auto_close_browser": media_config.auto_close_browser,
        "save_login_state": media_config.save_login_state,
        "persistent_profile_dir": str(mediacrawler_profile_dir),
        "persistent_profile_exists": mediacrawler_profile_dir.exists(),
    }
    checks["playwright"] = {
        "ok": xhs_config.profile_dir.exists(),
        "profile_dir": str(xhs_config.profile_dir),
        "snapshot_dir": str(xhs_config.snapshot_dir),
        "screenshot_dir": str(xhs_config.screenshot_dir),
        "headless": xhs_config.headless,
    }
    checks["feishu"] = {
        "ok": True,
        "status": "configured" if os.getenv("FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_APP_ID") else "未配置",
        "webhook_configured": bool(os.getenv("FEISHU_WEBHOOK_URL")),
        "app_configured": bool(os.getenv("FEISHU_APP_ID")),
        "dry_run": os.getenv("FEISHU_DRY_RUN", "true"),
    }
    checks["directories"] = {
        "ok": all(
            _ensure_writable(path)
            for path in (
                Path(os.getenv("WORKER_SNAPSHOT_ROOT", ".runtime/storage-snapshots")),
                media_config.output_root,
                xhs_config.snapshot_dir,
                xhs_config.screenshot_dir,
            )
        ),
        "paths": [
            str(Path(os.getenv("WORKER_SNAPSHOT_ROOT", ".runtime/storage-snapshots"))),
            str(media_config.output_root),
            str(xhs_config.snapshot_dir),
            str(xhs_config.screenshot_dir),
        ],
    }
    for value in checks.values():
        ok = ok and bool(value.get("ok"))
    return {"ok": ok, "checks": checks}


def _ensure_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _mask_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


if __name__ == "__main__":
    main()
