"""Human-labelled retrieval evaluation set (T-14).

The loader and status helpers for the ``human`` provenance class. The schema
the module accepts is documented in ``eval/human/README.md``; the repository
ships NO human-labelled data — creating it is a human task (V2 HO-4: teachers
and students label Bangla queries against the served corpus). CI prints
``HUMAN SET: ABSENT`` (non-failing) until a set with at least the configured
minimum exists; the ``require_human_eval`` gate flag turns the absence into a
failure for release gating only.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The only provenance this module accepts. Mixing classes is forbidden
#: (T-14): metrics are reported per provenance and never merged.
HUMAN_PROVENANCE = "human"

REQUIRED_ITEM_FIELDS = (
    "query",
    "expected_chunk_ids",
    "class_level",
    "subject",
    "annotator_id",
    "date",
)


def load_human_eval(path: Path) -> dict:
    """Load and validate a human-labelled eval set.

    Raises ValueError when the file's provenance is not ``human`` or an item
    misses a required field — a mislabelled set must never silently count as
    human evidence.
    """
    data: dict = json.loads(path.read_text(encoding="utf-8"))
    provenance = data.get("provenance")
    if provenance != HUMAN_PROVENANCE:
        raise ValueError(
            f"{path.name}: provenance must be {HUMAN_PROVENANCE!r}, got {provenance!r}"
        )
    for i, item in enumerate(data.get("items", [])):
        missing = [f for f in REQUIRED_ITEM_FIELDS if f not in item]
        if missing:
            raise ValueError(f"{path.name}: item {i} missing fields {missing}")
    return data


def human_set_status(path: Path, *, min_items: int) -> tuple[str, int]:
    """(status, item count) for the human set at ``path``.

    Statuses: ``absent`` (no file), ``invalid`` (unreadable/unlabelled),
    ``present-below-minimum``, ``present``. Never raises for a missing or
    broken file — the CI status line must render either way.
    """
    if not Path(path).is_file():
        return ("absent", 0)
    try:
        data = load_human_eval(Path(path))
    except (ValueError, json.JSONDecodeError, OSError):
        return ("invalid", 0)
    n = len(data.get("items", []))
    return ("present" if n >= min_items else "present-below-minimum", n)


def render_status_line(path: Path, *, min_items: int) -> str:
    """The one-line status CI prints (non-failing by design)."""
    status, n = human_set_status(path, min_items=min_items)
    if status == "absent":
        return f"HUMAN SET: ABSENT (0 items; needs >= {min_items}; labelling is HO-4)"
    if status == "invalid":
        return f"HUMAN SET: INVALID ({path} does not carry a valid human-labelled set)"
    if status == "present-below-minimum":
        return f"HUMAN SET: PRESENT but below minimum ({n}/{min_items} items)"
    return f"HUMAN SET: PRESENT ({n} items, minimum {min_items} met)"
