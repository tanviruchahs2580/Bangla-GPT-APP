"""Hermetic test configuration.

Developers may keep a real ``.env`` beside the compose stack; unit tests must
never inherit values from it. pydantic-settings resolves ``env_file``
relative to the current working directory, so we disable it for every test.
"""

import pytest

from bangla_gpt_api.config import Settings

_ORIG_MODEL_CONFIG = dict(Settings.model_config)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = dict(_ORIG_MODEL_CONFIG)
    cfg["env_file"] = None
    monkeypatch.setattr(Settings, "model_config", cfg)
