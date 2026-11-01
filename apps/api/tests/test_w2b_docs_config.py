"""F-141/SEC-10: the OWASP checklist names real configuration.

The checklist told operators to set ``CORS_ORIGINS``, which no Settings field
reads (the app reads ``ALLOWED_ORIGINS`` and pydantic drops unknown env
names), so following it silently left CORS closed; and it pointed
``enforce_production_safety`` at config.py although the function lives in
main.py. These tests keep every backticked env-style name in the checklist
tied to a real Settings field and the boot-guard pointer tied to a real
definition.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import re
from pathlib import Path

from bangla_gpt_api.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKLIST = REPO_ROOT / "docs" / "owasp_checklist.md"


def test_every_env_style_name_in_the_checklist_is_a_settings_field() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    names = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", text))
    unknown = sorted(name for name in names if name.lower() not in Settings.model_fields)
    assert not unknown, (
        "docs/owasp_checklist.md names env vars the app does not read "
        f"(pydantic would ignore them): {unknown}"
    )


def test_the_boot_guard_pointer_names_the_file_that_defines_it() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")
    match = re.search(
        r"`enforce_production_safety\(\)`\s*\n?\s*\(`([^`]+\.py)`\)",
        text,
    )
    assert match is not None, "the checklist must cite the boot guard's file"
    cited = REPO_ROOT / match.group(1)
    assert cited.is_file(), f"cited boot-guard file does not exist: {match.group(1)}"
    assert "def enforce_production_safety(" in cited.read_text(encoding="utf-8"), (
        f"{match.group(1)} does not define enforce_production_safety"
    )
