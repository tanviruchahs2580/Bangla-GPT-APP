"""AUD-B-27/B-31 drift guards: the compliance documents cannot rot silently.

* Every ``__tablename__`` in the schema must appear in the data inventory /
  flow map -- a new table added without a data-classification row fails.
* The applicable-law mapping must keep its sources (URLs) and the fetch date,
  and must not drift into asserting legal conclusions (no "we comply"/
  "compliant" claims; every row keeps the counsel question).
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]
# The mapped classes live in the db/models package (C-03 split of the former
# 978-line module); every module of it is walked, which is a superset of the
# single file this used to parse.
MODELS = REPO / "apps" / "api" / "src" / "bangla_gpt_api" / "db" / "models"
INVENTORY = REPO / "docs" / "compliance" / "data-inventory-and-flow-map.md"
LAW_MAP = REPO / "docs" / "compliance" / "bangladesh-law-mapping.md"


def _table_names() -> list[str]:
    names: list[str] = []
    for path in sorted(MODELS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and getattr(stmt.targets[0], "id", "") == "__tablename__"
                    and isinstance(stmt.value, ast.Constant)
                ):
                    names.append(stmt.value.value)
    return names


def test_every_table_appears_in_the_inventory() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    missing = [name for name in _table_names() if f"`{name}`" not in text]
    assert not missing, (
        f"tables missing from docs/compliance/data-inventory-and-flow-map.md: {missing}"
    )
    assert len(_table_names()) >= 40, "schema walk found too few tables; parser drift?"


def test_flow_map_names_the_third_party_and_storage_edges() -> None:
    text = INVENTORY.read_text(encoding="utf-8")
    for anchor in (
        "Google Gemini",
        "services/tutor.py:build_evidence_prompt_with_selection",
        "services/pii.py:redact_pii",
        "services/retention.py",
        "pgbackrest",
        "email_bounces",
    ):
        assert anchor in text, anchor


def test_law_mapping_keeps_sources_and_dates() -> None:
    text = LAW_MAP.read_text(encoding="utf-8")
    for url in (
        "https://en.wikipedia.org/wiki/Cyber_Security_Act,_2023",
        "dlapiperdataprotection.com",
        "pages.nist.gov/800-63-4/sp800-63b.html",
    ):
        assert url in text, url
    assert "2026-10-19" in text  # fetch date
    assert re.search(r"counsel", text)
    # Section reference for the NIST baseline is explicit.
    assert "3.1.1.2" in text


def test_law_mapping_makes_no_compliance_claims() -> None:
    text = LAW_MAP.read_text(encoding="utf-8").lower()
    for forbidden in (
        "we are compliant",
        "we comply",
        "fully compliant",
        "legally compliant",
        "meets the requirements of",
    ):
        assert forbidden not in text, forbidden
    assert "no legal conclusions" in text
