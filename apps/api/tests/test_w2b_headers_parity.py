"""F-193/SEC-10: the three static hosts ship the same security header set.

The Vercel deployment carried Permissions-Policy while the Caddy and nginx
paths set no policy at all, so camera/microphone/geolocation stayed reachable
on the self-hosted deployments. The header is now mirrored into
deploy/caddy/Caddyfile and apps/web/deploy/security-headers.conf; these tests
parse all three host configs and fail when a host loses a core header or the
Permissions-Policy value drifts from the others.

New file kept ASCII-only (repo rule for new files).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VERCEL = REPO_ROOT / "apps" / "web" / "vercel.json"
NGINX_SNIPPET = REPO_ROOT / "apps" / "web" / "deploy" / "security-headers.conf"
CADDY = REPO_ROOT / "deploy" / "caddy" / "Caddyfile"

#: Headers every host must set. HSTS is excluded on purpose: it belongs to
#: the TLS-terminating hosts (Caddy and Vercel), while the nginx image may
#: sit behind a terminator that already sets it.
CORE_HEADERS = frozenset(
    {
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    }
)


def _vercel_headers() -> dict[str, str]:
    data = json.loads(VERCEL.read_text(encoding="utf-8"))
    headers: dict[str, str] = {}
    for block in data.get("headers", []):
        for header in block.get("headers", []):
            headers[str(header["key"])] = str(header["value"])
    return headers


def _nginx_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in NGINX_SNIPPET.read_text(encoding="utf-8").splitlines():
        match = re.match(r"add_header\s+(\S+)\s+(\"[^\"]*\"|\S+)", raw.strip())
        if match is None:
            continue
        headers[match.group(1)] = match.group(2).strip('"')
    return headers


def _caddy_headers() -> dict[str, str]:
    """Header directives from the site-level block and the SPA handle."""
    headers: dict[str, str] = {}
    in_block = False
    for raw in CADDY.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "header {":
            in_block = True
            continue
        if in_block:
            if line == "}":
                in_block = False
                continue
            if line.startswith("-"):  # header deletion (-Server), not a set
                continue
            name = line.split()[0]
            value = line[len(name) :].strip().strip('"')
            headers[name] = value
        elif line.startswith("header "):
            parts = line.split(None, 2)
            name = parts[1].strip('"')
            value = parts[2].strip().strip('"') if len(parts) > 2 else ""
            headers[name] = value
    return headers


def _hosts() -> dict[str, dict[str, str]]:
    return {"vercel": _vercel_headers(), "nginx": _nginx_headers(), "caddy": _caddy_headers()}


def test_every_host_sets_the_core_security_headers() -> None:
    for host, headers in _hosts().items():
        missing = sorted(CORE_HEADERS - set(headers))
        assert not missing, f"{host} is missing security headers: {missing}"


def test_permissions_policy_is_identical_on_every_host() -> None:
    values = {host: headers["Permissions-Policy"] for host, headers in _hosts().items()}
    assert len(set(values.values())) == 1, f"Permissions-Policy differs across hosts: {values}"
