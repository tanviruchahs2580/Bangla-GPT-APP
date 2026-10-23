"""The proxy-trust pairing must hold: trust=true requires an overwriting proxy.

The defect this gate exists to prevent shipped twice in one repository state:

* ``docker-compose.yml`` did not pass ``TRUST_PROXY_HEADERS`` to the api
  container at all, and ``Settings.trust_proxy_headers`` defaults to False —
  so behind the bundled Caddy every request's ``request.client.host`` was the
  proxy's own address and **every IP-scoped rate limit shared one bucket**:
  ten logins/minute platform-wide, a whole class locked out of registration
  by one NAT, and the per-IP anti-abuse control effectively absent.
* the templates that documented the flag described appending proxies, which
  is the opposite of what ``TRUST_PROXY_HEADERS=true`` is safe with.

## What this checks, and what it deliberately does not

Checked here, deterministically, offline, from the repository text:

  1. ``docker-compose.yml`` forwards ``TRUST_PROXY_HEADERS`` to the api
     service (the regression was its absence);
  2. whenever the shipped default is ``true`` — in compose or in either env
     template — ``deploy/caddy/Caddyfile`` OVERWRITES ``X-Forwarded-For``
     (``header_up X-Forwarded-For {remote_host}``), which is the only thing
     that makes the default safe.

Not checked here, on purpose:

  * which proxy an operator actually deploys. That is runtime reality, not
    repository text; this gate can only keep the *bundle* self-consistent.
    ``docs/runbook.md`` and ``.env.production.example`` carry the operational
    rule: trust=true is correct only behind a proxy that overwrites.
  * Caddy syntax validity. ``docker compose config`` and the Caddy binary
    check that at deploy time; this is a drift guard, not a linter.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../apps/api/scripts/... -> repo root

COMPOSE = REPO / "docker-compose.yml"
CADDY = REPO / "deploy/caddy/Caddyfile"
TEMPLATES = (REPO / ".env.production.example", REPO / ".env.example")

#: compose default: `${TRUST_PROXY_HEADERS:-true}` / `:-false`
_COMPOSE_DEFAULT = re.compile(r"\$\{TRUST_PROXY_HEADERS:-(\w+)\}")
#: template line: `TRUST_PROXY_HEADERS=true`
_TEMPLATE_VALUE = re.compile(r"^TRUST_PROXY_HEADERS\s*=\s*(\w+)\s*$", re.MULTILINE)
#: the Caddy override that makes trust=true safe
_CADDY_OVERWRITE = re.compile(r"header_up\s+X-Forwarded-For\s+\{remote_host\}")


def _compose_forwards_flag(text: str) -> bool:
    """The api service must actually hand the variable to the container.

    The original defect was not a wrong value — it was no value: the compose
    api service never mentioned the variable, so an operator setting it in
    ``.env`` changed nothing. Any occurrence of the interpolation with a
    default counts; the check is deliberately textual and narrow.
    """
    return _COMPOSE_DEFAULT.search(text) is not None


def main() -> int:
    problems: list[str] = []

    compose_text = COMPOSE.read_text(encoding="utf-8")
    caddy_text = CADDY.read_text(encoding="utf-8")

    if not _compose_forwards_flag(compose_text):
        problems.append(
            "docker-compose.yml: the api service does not forward "
            "TRUST_PROXY_HEADERS (expected "
            "`TRUST_PROXY_HEADERS: ${TRUST_PROXY_HEADERS:-...}`) — an "
            "operator's value in .env would be silently ignored."
        )

    trusting_sources: list[str] = []
    compose_default = _COMPOSE_DEFAULT.search(compose_text)
    if compose_default and compose_default.group(1).lower() == "true":
        trusting_sources.append("docker-compose.yml default")
    for template in TEMPLATES:
        if not template.exists():
            continue
        match = _TEMPLATE_VALUE.search(template.read_text(encoding="utf-8"))
        if match and match.group(1).lower() == "true":
            trusting_sources.append(template.name)

    if trusting_sources and not _CADDY_OVERWRITE.search(caddy_text):
        problems.append(
            "deploy/caddy/Caddyfile: TRUST_PROXY_HEADERS=true ships by default in "
            f"{', '.join(trusting_sources)}, but the Caddyfile does not overwrite "
            "X-Forwarded-For (missing `header_up X-Forwarded-For {remote_host}`) — "
            "an appending proxy makes the trusted header spoofable and every "
            "IP-scoped rate limit bypassable."
        )

    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    print(
        "proxy contract ok: compose forwards TRUST_PROXY_HEADERS="
        f"{compose_default.group(1) if compose_default else '<unset>'}; "
        f"trusting sources: {', '.join(trusting_sources) or 'none'}; "
        "Caddy overwrite present."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
