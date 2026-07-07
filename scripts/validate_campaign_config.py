from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from platform_config.loader import load_campaign_config
from platform_config.validation import validate_campaign_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate one Campaign config JSON file.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_campaign_config(args.path)
        result = validate_campaign_config(config)
    except ValueError as exc:
        print(json.dumps({"validation_result": "failed", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True))
    return 0 if result.validation_result == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
