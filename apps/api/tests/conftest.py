"""Hermetic test configuration.

Developers may keep a real ``.env`` beside the compose stack; unit tests must
never inherit values from it. pydantic-settings resolves ``env_file``
relative to the current working directory, and in v2 it captures the config
at class-creation time — patching ``Settings.model_config`` alone does NOT
disable loading. We force ``_env_file=None`` through ``__init__`` and also
clear any config-named OS environment variables for every test.

The default ``database_url`` is a file-based SQLite store (for local dev
persistence), which tests must never touch: tests that do not pass an
explicit ``database_url`` get an in-memory database so every run stays
hermetic.
"""

import os

import pytest

from bangla_gpt_api.config import Settings

_ORIG_MODEL_CONFIG = dict(Settings.model_config)
_ORIG_INIT = Settings.__init__


def _hermetic_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    kwargs["_env_file"] = None
    # Explicit kwargs/env still win (pydantic-settings precedence); only the
    # file-DB default is replaced, so tests never share ./bangla_gpt.db.
    if "database_url" not in kwargs and "DATABASE_URL" not in os.environ:
        kwargs["database_url"] = "sqlite://"
    return _ORIG_INIT(self, *args, **kwargs)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = dict(_ORIG_MODEL_CONFIG)
    cfg["env_file"] = None
    monkeypatch.setattr(Settings, "model_config", cfg)
    monkeypatch.setattr(Settings, "__init__", _hermetic_init)
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
