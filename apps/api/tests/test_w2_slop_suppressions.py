"""F-194: every suppression in API source carries a written reason.

`CONTRIBUTING.md` promises that an unexplained `# noqa` / `# type: ignore` /
`# pragma: no cover` is queried in review; this test makes that mechanical.
The accepted reason forms are the two the codebase already uses: a ` - reason`
tail or a `(reason)` parenthetical. A directive with neither fails.

Two files are listed below because their suppressions belong to other wave-2
streams (the retrieval and tutor ownership boundaries); each entry must be
deleted when that stream annotates or removes its site.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bangla_gpt_api"

#: Files whose remaining unreasoned sites are owned by another stream.
OTHER_STREAM_FILES = frozenset(
    {
        "retrieval/hybrid_index.py",
        "routers/tutor.py",
    }
)

DIRECTIVE_RE = re.compile(
    r"#\s*(?:noqa(?::\s*[\w,\s]+)?|type:\s*ignore(?:\[[^\]]*\])?|pragma:\s*no cover)(?P<rest>.*)$"
)


def _has_reason(rest: str) -> bool:
    rest = rest.strip()
    if rest.startswith("- "):
        return len(rest) > 2
    if rest.startswith("(") and rest.endswith(")"):
        return len(rest) > 2
    # `# type: ignore[code]  # reason`: mypy rejects a ` - reason` tail after a
    # bracketed ignore ("Invalid type: ignore comment"), so the reason rides in
    # a second comment on the same line.
    return rest.startswith("# ") and len(rest) > 4


def test_every_suppression_in_api_source_states_a_reason() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in OTHER_STREAM_FILES:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = DIRECTIVE_RE.search(line)
            if match and not _has_reason(match.group("rest")):
                offenders.append(f"{relative}:{lineno}: {line.strip()}")
    assert not offenders, "suppressions without a reason: " + "; ".join(offenders)
