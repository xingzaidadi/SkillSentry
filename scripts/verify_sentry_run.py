#!/usr/bin/env python3
"""Verify sentry_run.py lightweight profiles."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_fake_claude(bin_dir: Path) -> None:
    cmd = bin_dir / "claude.cmd"
    cmd.write_text(
        "@echo off\r\n"
        "if not \"%SKILLSENTRY_FAKE_CLAUDE_COUNT%\"==\"\" echo hit>>\"%SKILLSENTRY_FAKE_CLAUDE_COUNT%\"\r\n"
        "echo [EXECUTION FAILED] fake local profile response\r\n",
        encoding="utf-8",
    )
    sh = bin_dir / "claude"
    sh.write_text(
        "#!/bin/sh\n"
        "if [ -n \"$SKILLSENTRY_FAKE_CLAUDE_COUNT\" ]; then echo hit >> \"$SKILLSENTRY_FAKE_CLAUDE_COUNT\"; fi\n"
        "echo '[EXECUTION FAILED] fake local profile response'\n",
        encoding="utf-8",
    )
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)


def make_fixture(root: Path) -> tuple[Path, Path]:
    skill_dir = root / "fixture-skill"
    skill_dir.mkdir()
    skill = skill_dir / "SKILL.md"
    skill.write_text(
        "---\nname: sentry-run-fixture\ndescription: Fixture skill for sentry_run tests\n---\nRespond briefly.",
        encoding="utf-8",
    )
    cases = root / "evals.json"
    save_json(
        cases,
        [
            {
                "id": "eval-1",
                "name": "fixture",
                "prompt": "Say ok",
                "assertions": [{"name": "A1", "type": "exact_match", "expected": "ok"}],
            }
        ],
    )
    return skill, cases


def run_profile(
    root: Path,
    env: dict,
    profile: str,
    skill: Path | None = None,
    cases: Path | None = None,
    session: Path | None = None,
    reuse_session: Path | None = None,
    force_executor: bool = False,
    force_grader: bool = False,
):
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "sentry_run.py"),
        "--profile",
        profile,
        "--format",
        "json",
    ]
    if skill is not None:
        cmd.extend(["--skill", str(skill)])
    if cases is not None:
        cmd.extend(["--cases", str(cases)])
    if session is not None:
        cmd.extend(["--session-dir", str(session)])
    if reuse_session is not None:
        cmd.extend(["--reuse-session", str(reuse_session)])
    if force_executor:
        cmd.append("--force-executor")
    if force_grader:
        cmd.append("--force-grader")
    if profile == "local":
        cmd.extend(["--model", "sonnet", "--executor-model", "sonnet", "--timeout-per-eval", "10"])
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def verify_lint(root: Path, env: dict, skill: Path, cases: Path, errors: list[str]) -> Path | None:
    completed = run_profile(root, env, "lint", skill=skill, cases=cases)
    if completed.returncode != 0:
        errors.append(f"lint exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return None
    payload = json.loads(completed.stdout)
    if payload.get("status") != "OK":
        errors.append(f"lint expected OK, got {payload.get('status')}")
    session_dir = Path(payload.get("session_dir", ""))
    if not (session_dir / "evals.json").exists():
        errors.append("lint did not prepare evals.json")
    session = load_json(session_dir / "session.json")
    if "case_lint" not in session:
        errors.append("lint did not write session.case_lint")
    return session_dir


def verify_debug(root: Path, env: dict, session_dir: Path, errors: list[str]) -> None:
    completed = run_profile(root, env, "debug", session=session_dir)
    if completed.returncode != 0:
        errors.append(f"debug exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    payload = json.loads(completed.stdout)
    if payload.get("status") != "OK":
        errors.append(f"debug expected OK, got {payload.get('status')}")
    for required in ("gate-result.json", "diagnostics.json", "report.html", "sentry-run-result.json"):
        if not (session_dir / required).exists():
            errors.append(f"debug missing {required}")


def fake_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def verify_local(root: Path, env: dict, skill: Path, cases: Path, errors: list[str]) -> None:
    completed = run_profile(root, env, "local", skill=skill, cases=cases)
    if completed.returncode != 0:
        errors.append(f"local exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    payload = json.loads(completed.stdout)
    if payload.get("status") != "OK":
        errors.append(f"local expected OK, got {payload.get('status')}")
    session_dir = Path(payload.get("session_dir", ""))
    for required in ("executor_results.json", "grading-summary.json", "diagnostics.json", "report.html", "sentry-run-result.json"):
        if not (session_dir / required).exists():
            errors.append(f"local missing {required}")
    session = load_json(session_dir / "session.json")
    if session.get("executor", {}).get("success") != 1:
        errors.append("local did not update session.executor.success")
    if session.get("grader_report", {}).get("status") != "completed":
        errors.append("local did not update session.grader_report.status")
    if not (session_dir / "manifest.json").exists():
        errors.append("local did not write manifest.json")

    count_file = Path(env["SKILLSENTRY_FAKE_CLAUDE_COUNT"])
    before = fake_count(count_file)
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir)
    if completed.returncode != 0:
        errors.append(f"local reuse exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before:
        errors.append(f"local reuse should not call fake claude again: before={before}, after={after}")
    reused_payload = json.loads(completed.stdout)
    if reused_payload.get("executor", {}).get("reused") is not True:
        errors.append("local reuse did not mark executor.reused=true")
    if reused_payload.get("grader", {}).get("reused") is not True:
        errors.append("local reuse did not mark grader.reused=true")

    # Changing cases must invalidate both executor and grader.
    before = fake_count(count_file)
    save_json(
        cases,
        [
            {
                "id": "eval-1",
                "name": "fixture changed",
                "prompt": "Say changed",
                "assertions": [{"name": "A1", "type": "exact_match", "expected": "changed"}],
            }
        ],
    )
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir)
    if completed.returncode != 0:
        errors.append(f"local changed cases exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before + 1:
        errors.append(f"changed cases should rerun executor: before={before}, after={after}")
    changed_cases_payload = json.loads(completed.stdout)
    if changed_cases_payload.get("executor", {}).get("reused") is True:
        errors.append("changed cases incorrectly reused executor")
    if changed_cases_payload.get("grader", {}).get("reused") is True:
        errors.append("changed cases incorrectly reused grader")

    # Changing SKILL.md must invalidate executor and refresh session metadata.
    before = fake_count(count_file)
    skill.write_text(
        "---\nname: sentry-run-fixture\ndescription: Updated fixture skill for sentry_run tests\n---\nRespond with the updated behavior.",
        encoding="utf-8",
    )
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir)
    if completed.returncode != 0:
        errors.append(f"local changed skill exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before + 1:
        errors.append(f"changed skill should rerun executor: before={before}, after={after}")
    changed_skill_payload = json.loads(completed.stdout)
    if changed_skill_payload.get("executor", {}).get("reused") is True:
        errors.append("changed skill incorrectly reused executor")
    session = load_json(session_dir / "session.json")
    preflight_hash = changed_skill_payload.get("preflight", {}).get("skill_hash")
    if preflight_hash and session.get("skill_hash") != preflight_hash:
        errors.append("changed skill did not refresh session.skill_hash")

    # force-executor must rerun executor even when manifest matches.
    before = fake_count(count_file)
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir, force_executor=True)
    if completed.returncode != 0:
        errors.append(f"local force executor exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before + 1:
        errors.append(f"--force-executor should rerun executor: before={before}, after={after}")
    force_executor_payload = json.loads(completed.stdout)
    if force_executor_payload.get("executor", {}).get("reused") is True:
        errors.append("--force-executor incorrectly reused executor")

    # force-grader must rerun grader without rerunning executor when executor manifest matches.
    before = fake_count(count_file)
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir, force_grader=True)
    if completed.returncode != 0:
        errors.append(f"local force grader exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before:
        errors.append(f"--force-grader should not rerun executor: before={before}, after={after}")
    force_grader_payload = json.loads(completed.stdout)
    if force_grader_payload.get("executor", {}).get("reused") is not True:
        errors.append("--force-grader should still reuse executor")
    if force_grader_payload.get("grader", {}).get("reused") is True:
        errors.append("--force-grader incorrectly reused grader")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-run-") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        make_fake_claude(bin_dir)
        skill, cases = make_fixture(root)
        env = os.environ.copy()
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["SKILLSENTRY_SESSION_ROOT"] = str(root / "sessions")
        env["SKILLSENTRY_FAKE_CLAUDE_COUNT"] = str(root / "fake-claude-count.txt")

        lint_session = verify_lint(root, env, skill, cases, errors)
        if lint_session is not None:
            verify_debug(root, env, lint_session, errors)
        verify_local(root, env, skill, cases, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_run.py profiles")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry run: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
