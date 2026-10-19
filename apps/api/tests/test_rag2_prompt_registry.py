"""AUD-A2-06 / A5-02: prompts are versioned files with an owner and a changelog.

What is pinned here:

* every registered prompt file exists and carries id, SemVer version, owner
  and a non-empty changelog naming the version it ships;
* the tutor's system prompt and instructions are LOADED from the registry
  (the module constant is the file content, byte for byte -- the digest of
  the pre-migration text is the regression anchor);
* prompts that still live as module constants are byte-identical to their
  registry file, so the two cannot drift while the handoff to migrate them
  is open;
* the loader fails loudly when the registry is missing (no silent fallback
  that would ship an unreviewed prompt);
* the loaded prompt version (id@version+digest) is what generation traces
  carry.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from bangla_gpt_api.services import tutor
from bangla_gpt_api.services.safety import AGE_RULE_SENTENCE

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
MANIFEST = json.loads((PROMPTS_DIR / "manifest.json").read_text(encoding="utf-8"))

#: Digest of SYSTEM_PROMPT as shipped inline in services/tutor.py before the
#: registry migration (captured at HEAD eddd04c, evidence E-R2-rag2-001).
#: The migration moved text, it did not change it -- if this digest moves, a
#: prompt edit happened and the registry changelog must say so.
BASELINE_SYSTEM_PROMPT_DIGEST = "54f3e1b19ebb"


def test_manifest_entries_are_complete() -> None:
    assert MANIFEST["prompts"], "registry must not be empty"
    ids = [row["id"] for row in MANIFEST["prompts"]]
    assert len(ids) == len(set(ids)), "prompt ids must be unique"
    for row in MANIFEST["prompts"]:
        assert row["owner"], f"{row['id']} has no owner"
        version = row["version"]
        assert version.count(".") == 2, f"{row['id']} version is not SemVer: {version}"
        changelog = row.get("changelog") or []
        assert changelog, f"{row['id']} has no changelog"
        assert any(entry["version"] == version for entry in changelog), (
            f"{row['id']} changelog does not document its current version {version}"
        )
        for entry in changelog:
            assert entry["date"] and entry["note"], f"{row['id']} has an empty changelog entry"
        path = PROMPTS_DIR / row["file"]
        assert path.is_file(), f"{row['id']} file missing: {path}"
        assert path.read_text(encoding="utf-8").strip(), f"{row['id']} file is empty"


def test_registry_files_have_no_orphans() -> None:
    registered = {row["file"] for row in MANIFEST["prompts"]}
    # README.md documents the registry; every other markdown file is a prompt.
    on_disk = {p.name for p in PROMPTS_DIR.glob("*.md")} - {"README.md"}
    assert on_disk == registered, f"unregistered prompt files: {sorted(on_disk - registered)}"


def test_tutor_prompts_are_loaded_from_the_registry() -> None:
    # The text is the file's text (one trailing newline is the file's ending).
    system_file = (PROMPTS_DIR / "tutor_system.md").read_text(encoding="utf-8")
    expected = system_file[:-1].replace("{{age_rule}}", AGE_RULE_SENTENCE)
    assert expected == tutor.SYSTEM_PROMPT
    assert AGE_RULE_SENTENCE in tutor.SYSTEM_PROMPT
    grounding = (PROMPTS_DIR / "tutor_grounding_retry.md").read_text(encoding="utf-8")
    assert grounding[:-1] == tutor.GROUNDING_RETRY_INSTRUCTION
    hint = (PROMPTS_DIR / "tutor_hint_first.md").read_text(encoding="utf-8")
    assert hint[:-1] == tutor.HINT_FIRST_INSTRUCTION


def test_system_prompt_text_did_not_change_in_the_migration() -> None:
    digest = hashlib.sha256(tutor.SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
    assert digest == BASELINE_SYSTEM_PROMPT_DIGEST


def test_prompt_version_is_registry_identity() -> None:
    spec = tutor.load_prompt("tutor_system")
    entry = next(row for row in MANIFEST["prompts"] if row["id"] == "tutor_system")
    assert spec.trace_version == tutor.PROMPT_VERSION
    assert tutor.PROMPT_VERSION.startswith(f"tutor_system@{spec.version}+sp-")
    assert entry["version"] == spec.version


def test_prompt_versions_in_the_registry_trace_value() -> None:
    # A prompt edit without a version bump would leave a stale identity in
    # traces; the digest half makes that visible even before the changelog is
    # read, and this test pins the composition.
    spec = tutor.load_prompt("tutor_hint_first")
    assert spec.trace_version == f"tutor_hint_first@{spec.version}+sp-{spec.digest}"


@pytest.mark.parametrize(
    "row",
    [row for row in MANIFEST["prompts"] if row.get("module_constant")],
    ids=lambda row: row["id"],
)
def test_unmigrated_prompts_match_their_registry_file(row: dict) -> None:
    """Prompts not yet loaded from the registry must equal their file.

    The handoff (migrate generators/* and answer_structure to load_prompt)
    stays open until every entry loses ``module_constant``; this test is what
    makes the intermediate state safe -- file and constant cannot drift.
    """
    module_name, attr = row["module_constant"].split(":")
    value = getattr(importlib.import_module(module_name), attr)
    file_text = (PROMPTS_DIR / row["file"]).read_text(encoding="utf-8")
    assert value == file_text[:-1]


def test_loader_fails_loudly_on_a_missing_registry(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="prompt registry missing"):
        tutor.load_prompt("tutor_system", directory=tmp_path)


def test_loader_rejects_an_unknown_prompt_id() -> None:
    with pytest.raises(RuntimeError, match="not in"):
        tutor.load_prompt("no_such_prompt")


def test_generation_trace_carries_the_prompt_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every generation trace names the exact prompt that produced it."""
    events: list[tuple[str, dict]] = []

    def _capture(event: str, **fields: object) -> None:
        events.append((event, fields))

    monkeypatch.setattr(tutor, "trace_event", _capture)
    service = tutor.TutorService.__new__(tutor.TutorService)
    service.index_version = "corpus-fp"
    service._trace_generation(
        route="deep",
        provider=type("P", (), {"name": "p"})(),
        prompt_text="x",
        answer="y",
        latency_ms=1,
    )
    assert len(events) == 1
    name, fields = events[0]
    assert name == "generation"
    assert fields["prompt_version"] == tutor.PROMPT_VERSION
