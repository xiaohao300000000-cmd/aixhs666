from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from platform_config.models import CampaignConfig


def load_campaign_config(path: str | Path) -> CampaignConfig:
    config_path = Path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        return CampaignConfig.model_validate(payload)
    except FileNotFoundError as exc:
        raise ValueError(f"campaign config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"campaign config is not valid JSON: {config_path}") from exc
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
