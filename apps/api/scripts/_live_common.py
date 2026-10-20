"""Shared helpers for the live runners (A8-05 / A9-01).

`evaluate_live.py` and `ttft_profile.py` both need the key resolution and the
split items; they live here so neither script imports the other (the
_changelog_common.py pattern).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]


def _load_items(split: str) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (APP_ROOT / "eval" / "golden_v2.json").read_text(encoding="utf-8")
    )
    items: list[dict[str, Any]] = data["items"]
    if split == "all":
        return items
    selected = [it for it in items if it.get("split", "dev") == split]
    if not selected:
        raise SystemExit(f"split {split!r} selected no items")
    return selected


def _redteam_items() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(
        (APP_ROOT / "eval" / "redteam_v2.json").read_text(encoding="utf-8")
    )
    items: list[dict[str, Any]] = data["items"]
    return items


def _dotenv_value(path: Path, name: str) -> str:
    """One value out of a dotenv file, without importing a parser for it."""
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    """The provider key from the environment or the gitignored apps/api/.env."""
    key = (
        os.environ.get("GEMINI_API_KEY", "") or _dotenv_value(APP_ROOT / ".env", "GEMINI_API_KEY")
    ).strip()
    if not key:
        raise SystemExit(
            "no GEMINI_API_KEY: set it in the process environment or in the "
            "gitignored apps/api/.env (the value is never printed here)"
        )
    return key
