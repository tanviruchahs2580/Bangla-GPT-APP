"""AUD-B-03 / AUD-B-07: deploy hardening cannot silently regress.

Config-drift guards, not runtime tests: ``docker-compose.yml``, the pgBackRest
stanza and the nightly backup loop are the artifacts an operator actually
runs, and nothing else in this suite reads them. Each declaration below was
verified against the real image during the fix (running the api, web, redis,
caddy and postgres containers with exactly these settings answered their
health checks); these tests keep the declarations from disappearing.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
PGBR_CONF = ROOT / "deploy" / "postgres" / "pgbackrest.conf"
PGBR_NIGHTLY = ROOT / "deploy" / "postgres" / "pgbackrest_nightly.sh"

#: Every service gets a capability drop and no-new-privileges (AUD-B-07).
HARDENED_SERVICES = (
    "api",
    "redis",
    "worker",
    "web",
    "caddy",
    "postgres",
    "prometheus",
    "grafana",
    "backup",
    "pgbackrest",
)

#: Services whose only writable paths are volumes/tmpfs (verified).
READ_ONLY_SERVICES = ("api", "worker", "backup", "web")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(text: str, header: str, indent: int) -> str:
    """Text of a mapping block whose header line sits at ``indent`` spaces.

    The block runs while every non-blank line is indented at least
    ``indent + 2`` (its children); the first line below that ends it. For a
    service that is the next service name; for a top-level anchor it is
    ``services:``.
    """
    pattern = re.compile(rf"(?m)^{' ' * indent}{re.escape(header)}:.*$")
    match = pattern.search(text)
    if match is None:
        raise AssertionError(f"compose block {header!r} at indent {indent} not found")
    body = text[match.end() :]
    child_indent = " " * (indent + 2)
    lines: list[str] = []
    for line in body.splitlines():
        if line.strip() and not line.startswith(child_indent):
            break
        lines.append(line)
    return "\n".join(lines)


def _effective_service(text: str, name: str) -> str:
    """A service block with its ``x-api-common`` anchor merged in.

    The api service gets its hardening through the YAML merge key, so reading
    only its own block would miss (or falsely report) the declarations.
    """
    block = _block(text, name, 2)
    if "<<: *api-common" in block:
        block += "\n" + _block(text, "x-api-common", 0)
    return block


def test_every_service_drops_capabilities_and_blocks_escalation() -> None:
    text = _text(COMPOSE)
    for service in HARDENED_SERVICES:
        block = _effective_service(text, service)
        assert "cap_drop:" in block and "- ALL" in block, f"{service}: cap_drop missing"
        assert "no-new-privileges:true" in block, f"{service}: security_opt missing"


def test_read_only_services_have_tmpfs_for_their_writes() -> None:
    text = _text(COMPOSE)
    for service in READ_ONLY_SERVICES:
        block = _effective_service(text, service)
        assert "read_only: true" in block, f"{service}: read_only missing"
        assert "tmpfs:" in block, f"{service}: no tmpfs for temporary files"
    api = _effective_service(text, "api")
    # (regex literal: this asserts a config string, it does not touch a path)
    assert re.search(r"(?m)^\s+- /?tmp$", api), "gunicorn needs a writable temp dir"
    web = _effective_service(text, "web")
    assert "/var/cache/nginx" in web, "nginx writes its temp dirs under /var/cache/nginx"
    # AUD-B-24: the web image is nginxinc/nginx-unprivileged -- master and
    # workers run as uid 101 and listen on 8080 -- so with `cap_drop: ALL` the
    # container can still bind, and no capability is granted. This used to
    # assert `NET_BIND_SERVICE in web`, which was true of the earlier root nginx
    # on :80 and is now a false failure. The invariant worth pinning is the
    # pair: a privileged port (<1024) requires the capability back beside
    # `cap_drop: ALL`, an unprivileged one forbids granting it.
    ports = re.findall(r'(?m)^\s*- "?(\d{1,5})"?\s*$', web)
    assert ports, "web: no port declared"
    if any(int(port) < 1024 for port in ports):
        assert "NET_BIND_SERVICE" in web, (
            f"web binds a privileged port ({ports}): nginx cannot bind it with "
            "cap_drop: ALL, so cap_add must restore NET_BIND_SERVICE"
        )
    else:
        assert "NET_BIND_SERVICE" not in web, (
            f"web listens on an unprivileged port ({ports}); NET_BIND_SERVICE must stay dropped"
        )
    assert "8080" in ports, "the unprivileged image listens on 8080; Caddy proxies web:8080"


def test_pgbackrest_repo_is_encrypted_and_the_pass_is_injected() -> None:
    """AUD-B-03: cipher enabled, passphrase supplied out-of-band, loud when absent."""
    conf = _text(PGBR_CONF)
    cipher_lines = [
        line.strip() for line in conf.splitlines() if line.strip().startswith("repo1-cipher-type")
    ]
    # pgBackRest 2.59.1 accepts exactly 'none' and 'aes-256-cbc'; ctr is rejected.
    assert cipher_lines == ["repo1-cipher-type=aes-256-cbc"], cipher_lines

    compose = _text(COMPOSE)
    for service in ("postgres", "pgbackrest"):
        block = _effective_service(compose, service)
        assert "PGBACKREST_REPO1_CIPHER_PASS" in block, (
            f"{service} must receive the repo passphrase environment variable"
        )

    nightly = _text(PGBR_NIGHTLY)
    assert "PGBACKREST_REPO1_CIPHER_PASS" in nightly
    assert "exit 1" in nightly, "the nightly loop must refuse to run without the passphrase"
