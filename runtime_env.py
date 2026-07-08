from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> bool:
    if os.getenv("AIXHS_SKIP_DOTENV") == "1":
        return False
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return False
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value
    return True


def _parse_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, _clean_value(value.strip())


def _clean_value(value: str) -> str:
    quote = value[:1]
    if quote in {"'", '"'} and value.endswith(quote):
        return value[1:-1]
    return value.split(" #", 1)[0].strip()
