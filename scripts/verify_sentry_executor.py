#!/usr/bin/env python3
"""Verify stable sentry_executor.py wrapper behavior without real model calls."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import sentry_state


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_fake_claude(bin_dir: Path) -> None:
    cmd = bin_dir / "claude.cmd"
    cmd.write_text("@echo off\r\necho fake executor response\r\n", encoding="utf-8")
    sh = bin_dir / "claude"
    sh.write_text("#!/bin/sh\necho fake executor response\n", encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)


def make_session(session_dir: Path, *, skill_type: str = "text_generation") -> None:
    sentry_state.save_session(
        session_dir,
        {
            "skill": "executor-fixture",
            "mode": "standard",
            "skill_type": skill_type,
            "skill_hash": "fixture",
            "runtime": "ci",
            "completed_steps": [],
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
        },
    )


def run_executor(root: Path, session_dir: Path, variant: str, env: dict, output: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "sentry_executor.py"),
            "--evals",
            str(root / "evals.json"),
            "--skill",
            str(root / "SKILL.md"),
            "--session-dir",
            str(session_dir),
            "--variant",
            variant,
            "--timeout-per-eval",
            "10",
            "--output",
            str(output),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def verify_with_skill(root: Path, env: dict, errors: list[str]) -> None:
    session_dir = root / "session-with"
    session_dir.mkdir()
    make_session(session_dir)
    output = root / "with-result.json"
    completed = run_executor(root, session_dir, "with_skill", env, output)
    if completed.returncode != 0:
        errors.append(f"with_skill exited {completed.returncode}: {completed.stderr.strip()}")
        return
    payload = load_json(output)
    if payload.get("status") != "OK":
        errors.append(f"with_skill status expected OK, got {payload.get('status')}")
    summary = load_json(session_dir / "executor_results.json")
    if summary.get("success") != 1 or summary.get("total") != 1:
        errors.append(f"with_skill summary expected 1/1, got {summary}")
    response = session_dir / "eval-1" / "with_skill" / "outputs" / "response.md"
    if not response.exists() or "fake executor response" not in response.read_text(encoding="utf-8"):
        errors.append("with_skill response.md missing fake executor response")
    session = sentry_state.load_session(session_dir)
    if session.get("executor", {}).get("success") != 1:
        errors.append("with_skill did not update session.executor.success")


def verify_without_skill(root: Path, env: dict, errors: list[str]) -> None:
    session_dir = root / "session-without"
    session_dir.mkdir()
    make_session(session_dir)
    output = root / "without-result.json"
    completed = run_executor(root, session_dir, "without_skill", env, output)
    if completed.returncode != 0:
        errors.append(f"without_skill exited {completed.returncode}: {completed.stderr.strip()}")
        return
    summary = load_json(session_dir / "executor_without_skill_results.json")
    if summary.get("success") != 1 or summary.get("total") != 1:
        errors.append(f"without_skill summary expected 1/1, got {summary}")
    session = sentry_state.load_session(session_dir)
    if session.get("without_skill", {}).get("status") != "completed":
        errors.append("without_skill did not update session.without_skill.status=completed")


def verify_mcp_skip(root: Path, env: dict, errors: list[str]) -> None:
    session_dir = root / "session-mcp"
    session_dir.mkdir()
    make_session(session_dir, skill_type="mcp_based")
    output = root / "mcp-result.json"
    completed = run_executor(root, session_dir, "without_skill", env, output)
    if completed.returncode != 0:
        errors.append(f"mcp skip exited {completed.returncode}: {completed.stderr.strip()}")
        return
    payload = load_json(output)
    if payload.get("status") != "PARTIAL":
        errors.append(f"mcp skip status expected PARTIAL, got {payload.get('status')}")
    if (session_dir / "executor_without_skill_results.json").exists():
        errors.append("mcp skip should not execute without_skill baseline")
    session = sentry_state.load_session(session_dir)
    if session.get("without_skill", {}).get("status") != "partial":
        errors.append("mcp skip did not update session.without_skill.status=partial")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-executor-") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)
        save_json(
            root / "evals.json",
            [{"id": "eval-1", "name": "fixture", "prompt": "Say fixture", "assertions": []}],
        )
        (root / "SKILL.md").write_text("---\nname: executor-fixture\n---\nRespond briefly.", encoding="utf-8")
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

        verify_with_skill(root, env, errors)
        verify_without_skill(root, env, errors)
        verify_mcp_skip(root, env, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_executor.py wrapper")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry executor: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
