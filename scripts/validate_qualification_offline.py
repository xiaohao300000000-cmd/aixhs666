from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platform_config.loader import load_campaign_config
from services.qualification import summarize_qualification_results
from storage.database import SessionLocal


DEFAULT_CAMPAIGNS = [
    "configs/campaigns/education_fuzhou_offline.json",
    "configs/campaigns/ielts_nationwide_online.json",
]


def build_qualification_validation_report(
    session: Any,
    *,
    campaign_paths: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    campaigns: dict[str, Any] = {}
    for path in campaign_paths:
        config = load_campaign_config(path)
        campaigns[config.campaign_id] = summarize_qualification_results(session, config, now=now)
    return {
        "generated_at": now.isoformat(),
        "source": "existing_lead_screening_results",
        "privacy": "aggregate_counts_only_no_raw_text_or_profile_data",
        "campaigns": campaigns,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run read-only offline qualification validation over saved screening results.")
    parser.add_argument("--campaign", action="append", dest="campaigns", default=[])
    parser.add_argument("--output", default=".runtime/qualification-validation-result.json")
    args = parser.parse_args(argv)
    campaign_paths = args.campaigns or DEFAULT_CAMPAIGNS
    with SessionLocal() as session:
        report = build_qualification_validation_report(session, campaign_paths=campaign_paths)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
