"""B14 — .env.example is generated from Settings (single source of truth).

Every Settings field must appear in .env.example, either active (``VAR=``)
or documented-commented (``# VAR=``), so operators never discover
parameters by reading source code.
"""

import re
from pathlib import Path

from bangla_gpt_api.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _var_documented(env_text: str, name: str) -> bool:
    return (
        re.search(rf"(?m)^{re.escape(name)}=", env_text) is not None
        or re.search(rf"(?m)^#\s*{re.escape(name)}=", env_text) is not None
    )


def test_env_example_covers_every_setting() -> None:
    env_text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    missing = [
        field for field in Settings.model_fields if not _var_documented(env_text, field.upper())
    ]
    assert not missing, f".env.example is missing: {missing}"


def test_production_env_example_covers_core_ops_vars() -> None:
    prod_text = (REPO_ROOT / ".env.production.example").read_text(encoding="utf-8")
    required = [
        "ENV",
        "JWT_SECRET",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD",
        "DOMAIN",
        "ACME_EMAIL",
        "DATABASE_URL",
        "REDIS_URL",
        "RATE_LIMIT_BACKEND",
        "ALLOWED_ORIGINS",
        "LLM_PROVIDER",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "SMTP_HOST",
        "LOG_LEVEL",
        "WEB_CONCURRENCY",
        "VITE_API_BASE",
    ]
    missing = [name for name in required if not _var_documented(prod_text, name)]
    assert not missing, f".env.production.example is missing: {missing}"
