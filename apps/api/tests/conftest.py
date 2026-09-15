"""Hermetic test configuration.

Two layers of isolation:

1. Module (import) time — applied *before* test collection. ``main.py`` builds
   a module-level ``app = create_app()`` for gunicorn, and test modules import
   it during collection, before any fixture runs. Without the import-time patch
   here, that collection-time build would use the real default (a file SQLite
   store) and pollute the workspace; CI's later ``alembic upgrade head`` then
   fails against the half-created schema (``table users already exists``).

2. Per test — the autouse fixture re-applies the patch and clears any
   config-named OS environment variables.

Developers may keep a real ``.env`` beside the compose stack; unit tests must
never inherit values from it. pydantic-settings resolves ``env_file`` relative
to the current working directory, and in v2 it captures the config at
class-creation time — patching ``Settings.model_config`` alone does NOT
disable loading, so we force ``_env_file=None`` through ``__init__`` too.

The default ``database_url`` is a file-based SQLite store (for local dev
persistence), which tests must never touch: tests that do not pass an
explicit ``database_url`` (kwarg or env) get an in-memory database, so
every run stays hermetic and never shares ``./bangla_gpt.db``.
"""

import os

import pytest

from bangla_gpt_api.config import Settings

_ORIG_MODEL_CONFIG = dict(Settings.model_config)
_ORIG_INIT = Settings.__init__

_HERMETIC_MODEL_CONFIG = dict(_ORIG_MODEL_CONFIG)
_HERMETIC_MODEL_CONFIG["env_file"] = None


def _hermetic_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    kwargs["_env_file"] = None
    # Explicit kwargs/env still win (pydantic-settings precedence); only the
    # file-DB default is replaced, so tests never share ./bangla_gpt.db.
    if "database_url" not in kwargs and "DATABASE_URL" not in os.environ:
        kwargs["database_url"] = "sqlite://"
    return _ORIG_INIT(self, *args, **kwargs)


# Layer 1: active before any test module import during collection.
Settings.model_config = _HERMETIC_MODEL_CONFIG  # type: ignore[misc]
Settings.__init__ = _hermetic_init  # type: ignore[method-assign]


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    # Layer 2: re-assert the patch for the duration of each test and scrub
    # process environment so no config value leaks in from the runner.
    monkeypatch.setattr(Settings, "model_config", dict(_HERMETIC_MODEL_CONFIG))
    monkeypatch.setattr(Settings, "__init__", _hermetic_init)
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
