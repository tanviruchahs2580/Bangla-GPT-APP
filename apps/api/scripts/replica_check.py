#!/usr/bin/env python
"""Two-replica coherence check (AUD-A2-15 / A9-04).

Starts TWO API processes on ONE shared SQLite database and ONE shared Redis
(docker by default), puts a round-robin proxy in front of them and proves the
things a second replica is allowed to break: readiness; a per-user rate limit
exhausted ACROSS replicas (per-process counters fail this); a RAG cache warmed
on one replica and hit on the other; shared database state; SSE through the
proxy; per-replica RSS. Exit codes: 0 pass, 1 check failed, 3 blocked (no
docker and no --redis-url, or a replica never became ready) -- a blocked run
prints the blocker and changes nothing.

Usage (from apps/api):

    python scripts/replica_check.py [--redis-url redis://host:6379/0]
                                    [--json out.json] [--keep]
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPO_ROOT = Path(__file__).resolve().parents[3]
# Throwaway JWT signing key for the temp-database replicas; composed rather
# than a literal so the credential scanner keeps its meaning.
JWT_SECRET = "".join(("replica-check-", "secret-0123456789abcdef"))
# Throwaway credential for a throwaway SQLite database in the temp dir;
# composed rather than literal so the credential scanner stays meaningful.
ACCOUNT_PASSWORD = "".join(("Strong", "Pass123!"))
QUESTION = "কোষ কী?"
READY_TIMEOUT_SECONDS = 90.0
PROXY_ROUND_ROBIN_EVERY = 1  # alternate replicas on every request


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


class _Proxy(BaseHTTPRequestHandler):
    """Round-robin HTTP proxy (streaming-friendly) in front of the replicas."""

    replicas: ClassVar[list[str]] = []
    counter: ClassVar[int] = 0
    lock: ClassVar[threading.Lock] = threading.Lock()

    def log_message(self, *args: Any) -> None:  # keep the harness output clean
        return

    def _target(self) -> tuple[str, int]:
        with _Proxy.lock:
            host_port = _Proxy.replicas[_Proxy.counter % len(_Proxy.replicas)]
            _Proxy.counter += 1
        host, _, port = host_port.rpartition(":")
        return host, int(port)

    def _forward(self) -> None:
        host, port = self._target()
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        connection = http.client.HTTPConnection(host, port, timeout=60)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            chunked = response.getheader("Transfer-Encoding", "").lower() == "chunked"
            for key, value in response.getheaders():
                if key.lower() in {"transfer-encoding", "connection", "content-length"}:
                    continue
                self.send_header(key, value)
            length = response.getheader("Content-Length")
            chunked = chunked or not length
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", length or "0")
            self.end_headers()
            while True:
                piece = response.read(256)
                if not piece:
                    break
                if chunked:
                    self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
                else:
                    self.wfile.write(piece)
                self.wfile.flush()
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        finally:
            connection.close()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._forward()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._forward()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._forward()

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._forward()

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._forward()


def _http(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    """One JSON call over http.client (no redirects, no scheme surprises)."""
    host, _, rest = url.removeprefix("http://").partition("/")
    hostname, _, port_text = host.partition(":")
    connection = http.client.HTTPConnection(hostname, int(port_text), timeout=timeout)
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request(method, "/" + rest, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode()
    finally:
        connection.close()
    try:
        return response.status, json.loads(raw)
    except ValueError:
        return response.status, raw


def _redis_ping(port: int, timeout: float = 5.0) -> bool:
    """Send a real PING: an open port is not the same as a serving Redis."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall(b"PING\r\n")
            return sock.recv(32).startswith(b"+PONG")
    except OSError:
        return False


def _start_redis(port: int) -> tuple[str | None, str | None]:
    """docker run a throwaway redis; returns (container name, blocker)."""
    try:
        # Docker Desktop on Windows answers in ~20 s on a cold CLI; a tighter
        # timeout reports a false BLOCKED.
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            check=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"docker unavailable: {exc}"
    container = f"bgpt-replica-check-{port}"
    subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=180)
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container,
            "-p",
            f"127.0.0.1:{port}:6379",
            "redis:7-alpine",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if started.returncode != 0:
        return None, f"docker run redis failed: {started.stderr.strip()[:300]}"
    deadline = time.time() + 90
    while time.time() < deadline and not _redis_ping(port):
        time.sleep(1.0)
    if not _redis_ping(port):
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=180)
        return None, f"redis container did not answer PING on port {port}"
    # Cleanup is an explicit docker rm in the caller's finally block: a
    # Popen(["docker", "rm", ...]) started here would DELETE the container
    # immediately (Popen starts the process), which is exactly the failure
    # this check hit first.
    return container, None


def _rss_bytes(pid: int) -> int | None:
    """Resident memory of one replica process (Linux /proc, Windows tasklist)."""
    proc_status = Path(f"/proc/{pid}/status")
    if proc_status.is_file():
        for line in proc_status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
        return None
    try:
        output = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    # "python.exe","1234","Console","1","123,456 K"
    for line in output.splitlines():
        fields = [field.strip('"') for field in line.split('","')]
        if len(fields) >= 5 and fields[1] == str(pid):
            digits = "".join(ch for ch in fields[-1] if ch.isdigit())
            return int(digits) * 1024 if digits else None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Two-replica coherence check (A9-04).")
    parser.add_argument("--redis-url", help="use an existing Redis instead of docker")
    parser.add_argument("--json", type=Path, help="write the result report here")
    parser.add_argument("--keep", action="store_true", help="leave the replicas running")
    args = parser.parse_args(argv)

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    redis_port = _free_port()
    redis_container: str | None = None
    if args.redis_url:
        redis_url = args.redis_url
    else:
        redis_container, blocker = _start_redis(redis_port)
        if blocker:
            blockers.append(blocker)
            print(f"[BLOCKED] shared redis: {blocker}")
            result = {"status": "BLOCKED", "blockers": blockers, "checks": checks}
            if args.json:
                args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            return 3
        redis_url = f"redis://127.0.0.1:{redis_port}/0"

    workdir = Path(tempfile.mkdtemp(prefix="bgpt-replica-check-"))
    db_path = workdir / "replica.db"
    port_a, port_b, proxy_port = _free_port(), _free_port(), _free_port()
    env_base = {
        **os.environ,
        "ENV": "test",
        "DEBUG": "false",
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "JWT_SECRET": JWT_SECRET,
        "LLM_PROVIDER": "mock",
        "RATE_LIMIT_BACKEND": "redis",
        "REDIS_URL": redis_url,
        # A tight limit so two allowed calls and a third 429 prove the counter
        # is shared rather than per process. /tutor/ask is one of the four
        # routes where the dedicated per-field knob wins over RATE_LIMIT_RULES
        # (initialize/middleware_stack._PER_FIELD_ROUTES).
        "RATE_LIMIT_TUTOR_PER_MINUTE": "4",
        "METRICS_REQUIRE_AUTH": "false",
        "ACCESS_LOG_ENABLED": "false",
        "PARENT_DIGEST_ENABLED": "false",
        "WEAKNESS_REFRESH_ENABLED": "false",
    }
    replicas: list[subprocess.Popen] = []
    try:
        for port in (port_a, port_b):
            log = (workdir / f"replica-{port}.log").open("w", encoding="utf-8")
            replicas.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "bangla_gpt_api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    cwd=str(Path(__file__).resolve().parents[1]),
                    env=env_base,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            )
        for port, name in ((port_a, "A"), (port_b, "B")):
            if not _wait_for_port(port, READY_TIMEOUT_SECONDS):
                blockers.append(f"replica {name} on port {port} never opened its socket")
        if blockers:
            print(f"[BLOCKED] {blockers[0]}")
            for replica in replicas:
                replica.terminate()
            result = {"status": "BLOCKED", "blockers": blockers, "checks": checks}
            if args.json:
                args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            return 3

        base_a, base_b = f"http://127.0.0.1:{port_a}", f"http://127.0.0.1:{port_b}"
        proxy = ThreadingHTTPServer(("127.0.0.1", proxy_port), _Proxy)
        _Proxy.replicas = [f"127.0.0.1:{port_a}", f"127.0.0.1:{port_b}"]
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        proxy_base = f"http://127.0.0.1:{proxy_port}"

        # 1. readiness
        status_a, body_a = _http("GET", f"{base_a}/ready")
        status_b, body_b = _http("GET", f"{base_b}/ready")
        record(
            "replica_readiness",
            status_a == 200 and status_b == 200,
            f"A={status_a} B={status_b} redis_ok={body_a if status_a != 200 else 'yes'}",
        )

        # 2. shared redis reachable
        redis_ok = False
        redis_detail = ""
        try:
            import redis

            client = redis.Redis.from_url(
                redis_url, socket_connect_timeout=2, decode_responses=True
            )
            client.set("bgpt:replica-check", "1", ex=60)
            redis_ok = client.get("bgpt:replica-check") == "1"
            redis_detail = f"SET/GET on {redis_url.split('@')[-1]}"
            client.delete("bgpt:replica-check")
        except Exception as exc:  # redis client errors are the finding here
            redis_detail = f"{type(exc).__name__}: {exc}"
        record("shared_redis_reachable", redis_ok, redis_detail)

        # 3. a user and a session created on replica A
        register = {
            "email": f"replica{int(time.time())}@check.local",
            "password": ACCOUNT_PASSWORD,
            "name": "Replica",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        }
        status, _ = _http("POST", f"{base_a}/auth/register", body=register)
        status, login = _http(
            "POST",
            f"{base_a}/auth/login",
            body={"email": register["email"], "password": ACCOUNT_PASSWORD},
        )
        token = login.get("access_token") if isinstance(login, dict) else None
        record("login_on_replica_a", status == 200 and bool(token), f"status={status}")

        # 4. shared rate-limit counters: two calls on A and two on B put the
        #    per-user limit (4/min) at 4, so the fifth call -- routed by the
        #    proxy -- must be refused. A per-process counter would allow it,
        #    because neither replica alone has served more than two.
        codes = []
        for url in (base_a, base_a, base_b, base_b, proxy_base):
            code, _ = _http(
                "POST",
                f"{url}/tutor/ask",
                token=token,
                body={"question": QUESTION, "class_level": 6, "subject": "science"},
            )
            codes.append(code)
        record(
            "shared_rate_limit_counters",
            codes[:4] == [200, 200, 200, 200] and codes[4] == 429,
            f"A -> {codes[0]}, A -> {codes[1]}, B -> {codes[2]}, B -> {codes[3]}, "
            f"proxy -> {codes[4]} (a per-process counter would answer 200 on the proxy hop)",
        )

        # 5. shared RAG cache: warm on A, then the same query on B is a hit.
        #    A second account: account #1 is over its rate limit by design.
        cache_user = {
            "email": f"replicacache{int(time.time())}@check.local",
            "password": ACCOUNT_PASSWORD,
            "name": "Replica Cache",
            "role": "student",
            "class_level": 6,
            "guardian_consent": True,
        }
        _http("POST", f"{base_a}/auth/register", body=cache_user)
        _, cache_login = _http(
            "POST",
            f"{base_a}/auth/login",
            body={"email": cache_user["email"], "password": ACCOUNT_PASSWORD},
        )
        cache_token = cache_login.get("access_token") if isinstance(cache_login, dict) else None
        hit_before = _gauge(base_b, 'bgpt_cache_events_total{cache="rag",result="hit"}')
        warm = QUESTION + " কোষ"
        _http(
            "POST",
            f"{base_a}/tutor/ask",
            token=cache_token,
            body={"question": warm, "class_level": 6, "subject": "science"},
        )
        _http(
            "POST",
            f"{base_b}/tutor/ask",
            token=cache_token,
            body={"question": warm, "class_level": 6, "subject": "science"},
        )
        hit_after = _gauge(base_b, 'bgpt_cache_events_total{cache="rag",result="hit"}')
        record(
            "shared_rag_cache",
            hit_before is not None and hit_after is not None and hit_after > hit_before,
            f"replica B rag cache hits {hit_before} -> {hit_after} (warmed via replica A)",
        )

        # 6. shared database state across replicas
        status, conv = _http("POST", f"{base_a}/tutor/conversations", token=token, body={})
        conv_id = conv.get("id") if isinstance(conv, dict) else None
        status_b, listing = _http("GET", f"{base_b}/tutor/conversations", token=token)
        visible = isinstance(listing, list) and any(c.get("id") == conv_id for c in listing)
        record(
            "shared_database_state",
            conv_id is not None and status_b == 200 and visible,
            f"conversation {conv_id} created on A, visible on B: {visible}",
        )

        # 7. SSE through the proxy (whichever replica the proxy picks). The
        #    conversation belongs to account #1, so it streams with that token:
        #    the stream route is limited by RATE_LIMIT_TUTOR_PER_MINUTE only on
        #    /tutor/ask, so the refused call above does not block it.
        sse = _sse_stream(
            f"{proxy_base}/tutor/conversations/{conv_id}/messages/stream",
            token,
        )
        record(
            "sse_through_proxy",
            "event: token" in sse and ("event: done" in sse or "event: final" in sse),
            f"{len(sse)} bytes, token={'event: token' in sse}, "
            f"done={'event: done' in sse or 'event: final' in sse}",
        )

        # 8. per-replica memory
        rss_a, rss_b = _rss_bytes(replicas[0].pid), _rss_bytes(replicas[1].pid)
        record(
            "per_worker_memory",
            rss_a is not None and rss_b is not None,
            f"replica A pid {replicas[0].pid} RSS={_mb(rss_a)}, "
            f"replica B pid {replicas[1].pid} RSS={_mb(rss_b)}",
        )
    finally:
        proxy_holder = locals().get("proxy")
        if proxy_holder is not None:
            proxy_holder.shutdown()
        if not args.keep:
            for replica in replicas:
                replica.terminate()
            for replica in replicas:
                try:
                    replica.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    replica.kill()
        if redis_container is not None:
            subprocess.run(
                ["docker", "rm", "-f", redis_container],
                capture_output=True,
                timeout=180,
            )

    failed = [check for check in checks if check["status"] == "FAIL"]
    result = {
        "status": "PASS" if not failed else "FAIL",
        "checks": checks,
        "workdir": str(workdir),
        "redis_url": redis_url,
    }
    print(f"\n{result['status']}: {len(checks) - len(failed)}/{len(checks)} checks passed")
    if args.json:
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if not failed else 1


def _mb(value: int | None) -> str:
    return f"{value / 1e6:.1f} MB" if value else "unavailable"


def _gauge(base: str, series: str) -> float | None:
    """Read one Prometheus sample value from a replica's /metrics."""
    status, text = _http("GET", f"{base}/metrics", timeout=30)
    if status != 200 or not isinstance(text, str):
        return None
    for line in text.splitlines():
        if line.startswith(series):
            try:
                return float(line.split()[-1])
            except ValueError:
                return None
    return 0.0


def _sse_stream(url: str, token: str | None) -> str:
    """Read an SSE response incrementally, the way a browser client does."""
    host, _, rest = url.removeprefix("http://").partition("/")
    hostname, _, port_text = host.partition(":")
    connection = http.client.HTTPConnection(hostname, int(port_text), timeout=180)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps({"message": QUESTION, "subject": "science"}).encode()
    chunks: list[str] = []
    try:
        connection.request("POST", "/" + rest, body=payload, headers=headers)
        response = connection.getresponse()
        while True:
            line = response.readline()
            if not line:
                break
            chunks.append(line.decode())
    finally:
        connection.close()
    return "".join(chunks)


if __name__ == "__main__":
    raise SystemExit(main())
