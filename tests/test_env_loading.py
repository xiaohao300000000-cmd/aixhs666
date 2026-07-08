from __future__ import annotations

import os
from pathlib import Path

from runtime_env import load_dotenv


def test_load_dotenv_sets_missing_values_without_overriding_existing(tmp_path: Path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "AIXHS_TEST_FROM_ENV=from-file",
                "AIXHS_TEST_EXISTING=from-file",
                "AIXHS_TEST_QUOTED='quoted value'",
                "AIXHS_TEST_COMMENTED=value # inline comment",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AIXHS_TEST_FROM_ENV", raising=False)
    monkeypatch.delenv("AIXHS_SKIP_DOTENV", raising=False)
    monkeypatch.setenv("AIXHS_TEST_EXISTING", "already-set")

    loaded = load_dotenv(dotenv)

    assert loaded is True
    assert os.environ["AIXHS_TEST_FROM_ENV"] == "from-file"
    assert os.environ["AIXHS_TEST_EXISTING"] == "already-set"
    assert os.environ["AIXHS_TEST_QUOTED"] == "quoted value"
    assert os.environ["AIXHS_TEST_COMMENTED"] == "value"
