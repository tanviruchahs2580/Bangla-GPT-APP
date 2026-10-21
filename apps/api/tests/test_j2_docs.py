"""Doc-tooling configuration invariants (audit findings J-02, J-10).

Two committed config files decide whether the documentation gates work, and
both have a failure mode that is invisible without a test:

* `cspell.json` names dictionaries by exact string, and a *wrong-case*
  dictionary name (`en-GB` instead of the accepted `en-gb`) is silently
  ignored - the check still passes, just without the British-English
  dictionary, which is how "behaviour"/"licence" end up "unknown". The test
  pins the name and the spell-check scope decisions.
* `.markdownlint-cli2.jsonc` is evaluated from the repository root, so its
  ignore list must cover every virtualenv a documented workflow creates
  (`apps/api/.venv` included), otherwise a developer who follows the README
  gets vendored-licence hits while CI stays green.

The README assertions are the J-02 checklist items that can be checked
mechanically: the support channel and the docs entry points are linked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_jsonc(path: Path) -> dict:
    """Parse JSON-with-line-comments (the `//` form cspell and cli2 accept)."""
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        cut = len(line)
        index = 0
        while index < len(line):
            char = line[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "/" and line[index : index + 2] == "//":
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return json.loads("\n".join(out))


def test_cspell_config_uses_the_accepted_dictionary_name() -> None:
    config = load_jsonc(REPO / "cspell.json")
    assert config["version"] == "0.2"
    # "en-GB" is silently ignored by cspell; only the lowercase spelling loads.
    assert "en-gb" in config["dictionaries"]
    assert "en-GB" not in config["dictionaries"]


def test_cspell_exempts_bengali_and_keeps_a_real_word_list() -> None:
    config = load_jsonc(REPO / "cspell.json")
    patterns = "\n".join(config["ignoreRegExpList"])
    assert "u0980" in patterns, "Bengali script must be exempt (native review owns it)"
    assert len(config["words"]) > 100, "the project word list is the check's vocabulary"
    assert "Bangla" in config["words"]
    # Generated and point-in-time material must not be spell-checked as prose.
    for ignored in ("CHANGELOG.md", "docs/archive/**", "docs/API.md"):
        assert ignored in config["ignorePaths"]


def test_markdownlint_ignores_every_virtualenv() -> None:
    config = load_jsonc(REPO / ".markdownlint-cli2.jsonc")
    ignores = config["ignores"]
    assert "**/.venv/**" in ignores, "the README quick start creates apps/api/.venv"
    assert "CHANGELOG.md" in ignores


def test_readme_links_support_docs_and_licence() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for required in (
        "](SUPPORT.md)",
        "](SECURITY.md)",
        "](CONTRIBUTING.md)",
        "](LICENSE)",
        "](CHANGELOG.md)",
        "](docs/INDEX.md)",
        "](docs/architecture.md)",
    ):
        assert required in readme, f"README is missing a link to {required[2:-1]}"


def test_readme_badges_point_at_workflows_that_exist() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    badges = re.findall(r"actions/workflows/([\w.-]+)/badge\.svg", readme)
    assert badges, "the README must carry live workflow badges (J-02)"
    for badge in badges:
        assert (REPO / ".github" / "workflows" / badge).is_file(), (
            f"no workflow file for badge {badge}"
        )


def test_readme_has_no_release_note_wall() -> None:
    """Version history belongs in CHANGELOG.md; the README states the current
    version and points at the changelog instead of listing releases."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## v0." not in readme
    assert len(readme.splitlines()) < 400
