"""S5.2 zero-downtime deploy: health-gated blue-green switch (expand-contract).

Orchestrator mode (staging/production hosts):

    python scripts/deploy_rolling.py \
        --ready-url http://127.0.0.1:8001/ready \
        --reload-cmd "caddy reload --config /etc/caddy/Caddyfile" \
        --drain-cmd  "docker stop -t 35 bangla-gpt-app-api-1"

    1. poll GET /ready on the NEW instance until it returns 200 (the app only
       reports ready once boot guards passed and the search index is built);
    2. only then run --reload-cmd (Caddy reload is graceful: in-flight requests
       finish on the old upstream while new ones go to the new one);
    3. then run --drain-cmd to stop the old instance gracefully.
    If /ready never goes green within --timeout NOTHING is touched: the old
    release keeps serving and the script exits 1.

--demo mode is a self-contained local proof of the mechanism: it boots two
hermetic app instances (mock provider, temp DB), serves them through a tiny
in-process proxy under continuous load, performs the gate -> flip -> drain
sequence, and fails unless every request during the switch succeeded.

    python scripts/deploy_rolling.py --demo
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API_DIR = HERE.parent / "apps" / "api"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def wait_ready(url: str, timeout: float, client: httpx.AsyncClient) -> bool:
    """Gate: true once the new release answers /ready with 200."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = await client.get(url, timeout=3.0)
            if r.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.5)
    return False


def orchestrator(args: argparse.Namespace) -> int:
    async def _run() -> int:
        async with httpx.AsyncClient() as client:
            print(f"gating on {args.ready_url} (timeout {args.timeout}s) ...")
            if not await wait_ready(args.ready_url, args.timeout, client):
                print(
                    "GATE FAILED: /ready never went green -- old release keeps serving"
                )
                return 1
            print("gate green: switching upstream")
            for cmd in (args.reload_cmd, args.drain_cmd):
                if not cmd:
                    continue
                proc = await asyncio.to_thread(
                    subprocess.run, cmd, shell=True, check=False
                )
                if proc.returncode != 0:
                    print(f"step failed ({proc.returncode}): {cmd}")
                    return 1
            print("ROLLING DEPLOY: DONE")
            return 0

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# demo: two real instances + in-process proxy + continuous load + switch
# ---------------------------------------------------------------------------


class Proxy:
    """Minimal forwarder whose upstream flips atomically between requests."""

    def __init__(self) -> None:
        self.upstream = ""
        self.server: asyncio.Server | None = None

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        status, body = 502, b""
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            head = request.split(b"\r\n")[0].decode()
            path = head.split(" ")[1] if len(head.split(" ")) > 1 else "/"
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self.upstream}{path}", timeout=10.0)
            status, body = r.status_code, r.content
        except (
            httpx.HTTPError,
            asyncio.IncompleteReadError,
            UnicodeDecodeError,
            OSError,
        ):
            status, body = 502, b""
        with contextlib.suppress(OSError):
            writer.write(
                b"HTTP/1.1 %d OK\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                % (status, len(body))
            )
            writer.write(body)
            await writer.drain()
            writer.close()

    async def start(self, port: int) -> None:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", port)


def _spawn_instance(port: int, db_file: str, log_file: str) -> subprocess.Popen:
    py = sys.executable
    env = {
        **os.environ,
        "LLM_PROVIDER": "mock",
        "RETRIEVAL_MODE": "bm25",
        "DATABASE_URL": f"sqlite:///./{db_file}",
        "LOG_LEVEL": "WARNING",
    }
    err = (API_DIR / log_file).open("w", encoding="utf-8")
    return subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "bangla_gpt_api.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=API_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=err,
    )


def _dump_failure(
    label: str, proc: subprocess.Popen[bytes] | None, log_name: str
) -> None:
    rc = proc.returncode if proc is not None else None
    tail = ""
    with contextlib.suppress(OSError):
        tail = (API_DIR / log_name).read_text(encoding="utf-8", errors="replace")[
            -2000:
        ]
    print(
        f"DEMO FAILED: {label} (rc={rc})\n--- {log_name} tail ---\n{tail}", flush=True
    )


def demo(args: argparse.Namespace) -> int:
    async def _run() -> int:
        old_port, new_port, proxy_port = _free_port(), _free_port(), _free_port()
        print(f"ports: old={old_port} new={new_port} proxy={proxy_port}", flush=True)
        # Fresh demo DB: sidecars left by an interrupted run poison schema init.
        for name in ("_deploy_demo.db", "_deploy_demo.db-wal", "_deploy_demo.db-shm"):
            with contextlib.suppress(OSError):
                (API_DIR / name).unlink()
        old_proc = _spawn_instance(old_port, "_deploy_demo.db", "_deploy_demo_old.log")
        new_proc = None
        proxy = Proxy()
        await proxy.start(proxy_port)
        proxy.upstream = f"http://127.0.0.1:{old_port}"
        failures = 0
        total = 0
        switching = asyncio.Event()

        async def load() -> None:
            nonlocal failures, total
            while not switching.is_set():
                total += 1
                try:
                    r = await client.get(
                        f"http://127.0.0.1:{proxy_port}/health", timeout=5.0
                    )
                    if r.status_code != 200:
                        failures += 1
                except httpx.HTTPError:
                    failures += 1
                await asyncio.sleep(0.02)

        client = httpx.AsyncClient()
        loaders: list[asyncio.Task[None]] = []
        try:
            # The old release must SERVE live traffic before the new one boots
            # alongside it (runbook sequence; concurrent cold boots of two
            # instances on one SQLite file race).
            if not await wait_ready(f"http://127.0.0.1:{old_port}/ready", 90, client):
                _dump_failure(
                    "old release never became ready", old_proc, "_deploy_demo_old.log"
                )
                return 1
            print("old release serving; booting new release alongside ...", flush=True)
            loaders = [asyncio.create_task(load()) for _ in range(3)]
            new_proc = _spawn_instance(
                new_port, "_deploy_demo.db", "_deploy_demo_new.log"
            )
            if not await wait_ready(f"http://127.0.0.1:{new_port}/ready", 120, client):
                _dump_failure(
                    "new release never became ready", new_proc, "_deploy_demo_new.log"
                )
                return 1
            # Gate green -> flip upstream atomically -> drain old. On real hosts
            # this is `caddy reload` + graceful stop; here it is one assignment.
            proxy.upstream = f"http://127.0.0.1:{new_port}"
            print("gate green: upstream flipped to new release", flush=True)
            await asyncio.sleep(0.3)  # let in-flight old-upstream requests finish
            old_proc.terminate()
            await asyncio.to_thread(old_proc.wait)
            switching.set()
            await asyncio.gather(*loaders)
            loaders = []
            # Keep load running briefly against the NEW upstream.
            for _ in range(20):
                total += 1
                r = await client.get(
                    f"http://127.0.0.1:{proxy_port}/health", timeout=5.0
                )
                if r.status_code != 200:
                    failures += 1
                await asyncio.sleep(0.05)
            print(f"demo: requests={total} failures={failures}", flush=True)
            if failures == 0 and total > 30:
                print("ZERO-DOWNTIME SWITCH: PASS (0 failed requests)", flush=True)
                return 0
            print("ZERO-DOWNTIME SWITCH: FAIL", flush=True)
            return 1
        finally:
            for t in loaders:
                t.cancel()
            for p in (old_proc, new_proc):
                if p is not None and p.poll() is None:
                    p.terminate()
            if proxy.server is not None:
                proxy.server.close()
            await client.aclose()

    try:
        return asyncio.run(_run())
    finally:
        time.sleep(1.5)  # let uvicorn children release the sqlite file
        for name in ("_deploy_demo.db", "_deploy_demo.db-wal", "_deploy_demo.db-shm"):
            with contextlib.suppress(OSError):
                (API_DIR / name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--demo", action="store_true", help="self-contained local proof"
    )
    parser.add_argument("--ready-url", help="new instance /ready URL to gate on")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--reload-cmd", help="proxy upstream switch command (graceful)")
    parser.add_argument("--drain-cmd", help="old instance graceful-stop command")
    args = parser.parse_args()
    if args.demo:
        return demo(args)
    if not args.ready_url or not args.reload_cmd:
        parser.error(
            "orchestrator mode needs --ready-url and --reload-cmd (or use --demo)"
        )
    return orchestrator(args)


if __name__ == "__main__":
    raise SystemExit(main())
