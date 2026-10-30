"""F-198: inventory the two-value status-code asserts and pin the allowed pairs.

Each allowed pair encodes a deliberate posture; an unlisted pair, or a new
occurrence of a listed one beyond the recorded count, fails this test. The
inventory may only shrink as asserts are tightened to their real contract.
"""

import re
from collections import Counter
from pathlib import Path

TESTS = Path(__file__).resolve().parent

STATUS_IN_RE = re.compile(r"status_code in \(([^)]*)\)")

#: Pair -> why the ambiguity is intentional. These are the only acceptable
#: two-value status asserts in the suite.
ALLOWED_PAIRS: dict[tuple[str, ...], str] = {
    ("200", "201", "202"): "the product-analytics ingest accepts any documented accept code",
    ("200", "404"): "an empty collection and an absent one are the same answer to a client",
    ("200", "503"): "a corpus-dependent read answers 503 when the local corpus is absent",
    (
        "201",
        "422",
    ): "shorttest creation depends on corpus coverage for the filter; both are contract",
    ("400", "403"): "submission refused at validation or by the assignment guard",
    (
        "400",
        "404",
    ): "an unparsable id and an absent row share the refusal (no-existence-leak posture)",
    ("400", "409"): "roster conflict: field validation vs duplicate membership",
    ("401", "403"): "auth guard vs role guard; which one refuses is deliberately indistinct",
    ("401", "404"): "no session and no row look the same to an unauthenticated caller",
    ("401", "429"): "the limiter may refuse before authentication does",
    (
        "401",
        "422",
    ): "the body reader may reject a malformed request before the auth dependency runs",
    ("403", "404"): "another tenant's row and a missing row look the same (no existence leak)",
    ("404", "405"): "an unlisted path and a wrong method on a listed one both mean 'not a route'",
    ("404", "422"): "an unknown id and a malformed payload share the refusal",
}

#: Current occurrence count per pair. May only fall; delete entries at zero.
EXPECTED_COUNTS: dict[tuple[str, ...], int] = {
    ("200", "201", "202"): 1,
    ("200", "404"): 1,
    ("200", "503"): 1,
    ("201", "422"): 1,
    ("400", "403"): 1,
    ("400", "404"): 1,
    ("400", "409"): 1,
    ("401", "403"): 3,
    ("401", "404"): 1,
    ("401", "422"): 2,
    ("401", "429"): 1,
    ("403", "404"): 4,
    ("404", "405"): 2,
    ("404", "422"): 1,
}


def _pairs() -> Counter[tuple[str, ...]]:
    found: Counter[tuple[str, ...]] = Counter()
    for path in sorted(TESTS.glob("test_*.py")):
        for match in STATUS_IN_RE.finditer(path.read_text(encoding="utf-8")):
            values = tuple(
                sorted(part.strip() for part in match.group(1).split(",") if part.strip())
            )
            found[values] += 1
    return found


def test_every_two_value_status_assert_uses_a_documented_pair() -> None:
    undocumented = {pair: count for pair, count in _pairs().items() if pair not in ALLOWED_PAIRS}
    assert not undocumented, (
        "two-value status asserts without a documented posture: "
        f"{undocumented}; add the pair to ALLOWED_PAIRS with its reason or assert one code"
    )


def test_recorded_pair_counts_only_shrink() -> None:
    found = _pairs()
    grown = {
        pair: (EXPECTED_COUNTS.get(pair, 0), count)
        for pair, count in found.items()
        if count > EXPECTED_COUNTS.get(pair, 0)
    }
    assert not grown, f"recorded count grew (old, new): {grown}"
