from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = ROOT / "docs" / "remediation" / "evidence"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--task", default="T-00", help="evidence subdirectory task id")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    workdir = (ROOT / args.cwd).resolve()
    if not workdir.is_relative_to(ROOT):
        parser.error("working directory must remain inside the repository")
    evidence = EVIDENCE_ROOT / args.task

    env = os.environ.copy()
    env.update({"CI": "1", "GIT_PAGER": "cat", "PAGER": "cat"})
    recorded_command = command.copy()
    if command:
        executable = Path(command[0])
        if not executable.is_absolute() and ("/" in command[0] or "\\" in command[0]):
            command[0] = str((workdir / executable).resolve())
    started = datetime.now(UTC)
    tick = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        exit_code = result.returncode
        output = result.stdout
    except OSError as exc:
        exit_code = 127
        output = f"{type(exc).__name__}: {exc}\n"
    duration = time.monotonic() - tick
    finished = datetime.now(UTC)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    header = "\n".join(
        [
            f"Evidence-ID: EV-T00-{args.id}",
            f"Captured-UTC: {started.isoformat()}",
            f"Finished-UTC: {finished.isoformat()}",
            f"Base-SHA: {revision}",
            f"Working-directory: {workdir.relative_to(ROOT).as_posix()}",
            f"Command: {shlex.join(recorded_command)}",
            f"Python: {sys.version.split()[0]}",
            f"Exit-code: {exit_code}",
            f"Duration-seconds: {duration:.3f}",
            "--- output ---",
        ]
    )
    target = evidence / f"{args.id}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + "\n" + output, encoding="utf-8", newline="\n")
    print(f"evidence={target.relative_to(ROOT).as_posix()}")
    print(f"command_exit={exit_code}")
    print(f"duration_seconds={duration:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
