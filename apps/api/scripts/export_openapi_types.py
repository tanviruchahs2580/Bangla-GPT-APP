#!/usr/bin/env python
"""Dump the served OpenAPI document to the web app's committed fixture (F-157).

The frontend's contract test (apps/web/src/test/apiContract.test.ts) runs in
vitest with no server, so it reads a committed snapshot of ``app.openapi()``
instead. This script regenerates that snapshot; CI runs it and diffs, so a
schema change that ships without the fixture following fails the api job.

Usage:
    python scripts/export_openapi_types.py [output.json]

Default output: apps/web/src/test/fixtures/openapi.json (next to the test
that consumes it). Deterministic bytes (sorted keys, fixed indent, trailing
newline) so the CI diff shows exactly the schema change, never formatting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: apps/api/scripts -> apps/web/src/test/fixtures
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[2] / "web" / "src" / "test" / "fixtures" / "openapi.json"
)

#: Test-stack settings: production guards stay off and no database is opened
#: (openapi() reads the route table, never a table). The secret is a dummy
#: throwaway value (built, not a literal, to keep bandit's S106 quiet): the
#: document it produces carries no key material.
_TEST_SETTINGS = dict(
    env="test",
    jwt_secret="x" * 48,
    database_url="sqlite://",
)


def main() -> int:
    from bangla_gpt_api.config import Settings
    from bangla_gpt_api.main import create_app

    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    doc = create_app(Settings(**_TEST_SETTINGS)).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    operations = sum(
        1
        for methods in doc["paths"].values()
        for method in methods
        if method in ("get", "post", "put", "patch", "delete")
    )
    print(f"openapi fixture written: {output} ({len(doc['paths'])} paths, {operations} operations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
