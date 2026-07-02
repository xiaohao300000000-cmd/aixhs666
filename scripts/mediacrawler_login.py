from __future__ import annotations

import argparse
import os
from pathlib import Path

from collectors.mediacrawler import MediaCrawlerConfig, MediaCrawlerXiaohongshuAdapter


DEFAULT_LOGIN_QUERY = "KET 没过怎么办"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a persistent MediaCrawler Xiaohongshu login session.")
    parser.add_argument("--query", default=DEFAULT_LOGIN_QUERY, help="A small real search to run after manual login.")
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Time allowed for manual login and first run.")
    parser.add_argument("--check-only", action="store_true", help="Only print the configured persistent login paths.")
    args = parser.parse_args()

    os.environ.setdefault("WORKER_ADAPTER", "mediacrawler")
    os.environ.setdefault("MEDIACRAWLER_ENABLE_CDP_MODE", "true")
    os.environ.setdefault("MEDIACRAWLER_CDP_CONNECT_EXISTING", "false")
    os.environ.setdefault("MEDIACRAWLER_AUTO_CLOSE_BROWSER", "false")
    os.environ.setdefault("MEDIACRAWLER_SAVE_LOGIN_STATE", "true")
    os.environ.setdefault("MEDIACRAWLER_USER_DATA_DIR", "aixhs_%s_user_data_dir")
    os.environ.setdefault("MEDIACRAWLER_HEADLESS", "false")
    os.environ["MEDIACRAWLER_TIMEOUT_SECONDS"] = str(args.timeout_seconds)

    config = MediaCrawlerConfig.from_env()
    user_data_dir = config.persistent_profile_dir
    print(f"MediaCrawler home: {config.home}")
    print(f"Persistent XHS profile: {user_data_dir}")
    print(f"CDP self-managed browser: {config.enable_cdp_mode and not config.cdp_connect_existing}")
    print("Manual action: scan the Xiaohongshu QR code if prompted. Do not enter credentials in this script.")

    if args.check_only:
        return

    adapter = MediaCrawlerXiaohongshuAdapter(config=config)
    page = adapter.search(args.query, limit=20)
    print(f"Login/search completed. Items collected: {len(page.items)}")
    print(f"Persistent profile kept at: {user_data_dir}")


if __name__ == "__main__":
    main()
