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
from datetime import datetime
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
    cases.write_text(
        json.dumps(
            [
                {
                    "id": "eval-1",
                    "name": "fixture",
                    "prompt": "Say ok",
                    "assertions": [{"name": "A1", "type": "exact_match", "expected": "ok"}],
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8-sig",
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
    output_dir: Path | None = None,
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
    if output_dir is not None:
        cmd.extend(["--output-dir", str(output_dir)])
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
    assert_timings(payload, "lint", ("preflight", "session", "prepare_cases"), errors)
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
    assert_timings(payload, "debug", ("gate", "diagnostics", "report"), errors)
    for required in ("gate-result.json", "diagnostics.json", "report.html", "sentry-run-result.json"):
        if not (session_dir / required).exists():
            errors.append(f"debug missing {required}")


def fake_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def assert_timings(payload: dict, profile: str, required_phases: tuple[str, ...], errors: list[str]) -> None:
    timings = payload.get("timings")
    if not isinstance(timings, dict):
        errors.append(f"{profile} missing timings")
        return
    if not isinstance(timings.get("total_ms"), (int, float)):
        errors.append(f"{profile} missing timings.total_ms")
    phases = timings.get("phases_ms")
    if not isinstance(phases, dict):
        errors.append(f"{profile} missing timings.phases_ms")
        return
    for phase in required_phases:
        if not isinstance(phases.get(phase), (int, float)):
            errors.append(f"{profile} missing timing phase: {phase}")


def verify_local(root: Path, env: dict, skill: Path, cases: Path, errors: list[str]) -> None:
    completed = run_profile(root, env, "local", skill=skill, cases=cases)
    if completed.returncode != 0:
        errors.append(f"local exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    payload = json.loads(completed.stdout)
    if payload.get("status") != "OK":
        errors.append(f"local expected OK, got {payload.get('status')}")
    assert_timings(payload, "local", ("preflight", "session", "prepare_cases", "executor", "grader", "diagnostics"), errors)
    session_dir = Path(payload.get("session_dir", ""))
    for required in ("executor_results.json", "grading-summary.json", "diagnostics.json", "report.html", "sentry-run-result.json"):
        if not (session_dir / required).exists():
            errors.append(f"local missing {required}")
    session = load_json(session_dir / "session.json")
    if session.get("executor", {}).get("success") != 1:
        errors.append("local did not update session.executor.success")
    if session.get("grader_report", {}).get("status") != "completed":
        errors.append("local did not update session.grader_report.status")
    if session.get("cases", {}).get("reused") is not False:
        errors.append("local fresh prepare should write session.cases.reused=false")
    if not (session_dir / "manifest.json").exists():
        errors.append("local did not write manifest.json")
    manifest = load_json(session_dir / "manifest.json")
    grader_outputs = manifest.get("steps", {}).get("grader-report", {}).get("outputs", [])
    if len(grader_outputs) != len(set(grader_outputs)):
        errors.append("local manifest grader outputs should be unique")
    if not any(str(output).endswith("eval-1\\grading.json") or str(output).endswith("eval-1/grading.json") for output in grader_outputs):
        errors.append("local manifest grader outputs should include expected per-eval grading.json")

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
    assert_timings(reused_payload, "local reuse", ("prepare_cases", "executor", "grader", "diagnostics"), errors)
    if reused_payload.get("executor", {}).get("reused") is not True:
        errors.append("local reuse did not mark executor.reused=true")
    if reused_payload.get("executor", {}).get("reuse", {}).get("reason") != "matched":
        errors.append("local reuse did not explain executor reuse as matched")
    if reused_payload.get("grader", {}).get("reused") is not True:
        errors.append("local reuse did not mark grader.reused=true")
    if reused_payload.get("grader", {}).get("reuse", {}).get("reason") != "matched":
        errors.append("local reuse did not explain grader reuse as matched")
    if reused_payload.get("cases", {}).get("reused") is not True:
        errors.append("local reuse did not mark cases.reused=true")
    reuse_summary = reused_payload.get("reuse_summary", {})
    if reuse_summary.get("all_reused") is not True:
        errors.append("local reuse summary should mark all_reused=true")
    if reuse_summary.get("rerun_steps") != []:
        errors.append(f"local reuse summary should have no rerun_steps, got {reuse_summary.get('rerun_steps')!r}")
    session = load_json(session_dir / "session.json")
    if session.get("cases", {}).get("reused") is not True:
        errors.append("local reuse should write session.cases.reused=true")

    # Missing executor response artifacts must invalidate executor reuse.
    response_file = session_dir / "eval-1" / "with_skill" / "outputs" / "response.md"
    if response_file.exists():
        response_file.unlink()
    before = fake_count(count_file)
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir)
    if completed.returncode != 0:
        errors.append(f"local missing response exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before + 1:
        errors.append(f"missing response should rerun executor: before={before}, after={after}")
    missing_response_payload = json.loads(completed.stdout)
    if missing_response_payload.get("executor", {}).get("reused") is True:
        errors.append("missing response incorrectly reused executor")
    if missing_response_payload.get("executor", {}).get("reuse", {}).get("reason") != "missing_outputs":
        errors.append("missing response did not explain executor reuse miss as missing_outputs")
    reuse_summary = missing_response_payload.get("reuse_summary", {})
    if "executor-with" not in reuse_summary.get("rerun_steps", []):
        errors.append("missing response reuse summary should include executor-with rerun")
    if reuse_summary.get("miss_reasons", {}).get("missing_outputs") != 1:
        errors.append("missing response reuse summary should count one missing_outputs miss")
    if not response_file.exists():
        errors.append("missing response was not restored by executor rerun")

    # Missing per-eval grading artifacts must invalidate grader reuse.
    grading_file = session_dir / "eval-1" / "grading.json"
    if grading_file.exists():
        grading_file.unlink()
    before = fake_count(count_file)
    completed = run_profile(root, env, "local", skill=skill, cases=cases, reuse_session=session_dir)
    if completed.returncode != 0:
        errors.append(f"local missing grading exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    after = fake_count(count_file)
    if after != before:
        errors.append(f"missing grading should not rerun executor: before={before}, after={after}")
    missing_grading_payload = json.loads(completed.stdout)
    if missing_grading_payload.get("executor", {}).get("reused") is not True:
        errors.append("missing grading should still reuse executor")
    if missing_grading_payload.get("grader", {}).get("reused") is True:
        errors.append("missing grading incorrectly reused grader")
    if missing_grading_payload.get("grader", {}).get("reuse", {}).get("reason") != "missing_outputs":
        errors.append("missing grading did not explain grader reuse miss as missing_outputs")
    reuse_summary = missing_grading_payload.get("reuse_summary", {})
    if reuse_summary.get("reused_steps") != ["executor-with"]:
        errors.append(f"missing grading reuse summary should reuse only executor-with, got {reuse_summary.get('reused_steps')!r}")
    if reuse_summary.get("rerun_steps") != ["grader-report"]:
        errors.append(f"missing grading reuse summary should rerun only grader-report, got {reuse_summary.get('rerun_steps')!r}")
    if not grading_file.exists():
        errors.append("missing grading was not restored by grader rerun")

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
    if changed_cases_payload.get("cases", {}).get("reused") is True:
        errors.append("changed cases incorrectly reused prepared cases")

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
    if force_executor_payload.get("executor", {}).get("reuse", {}).get("reason") != "force_executor":
        errors.append("--force-executor did not explain executor reuse miss as force_executor")

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
    if force_grader_payload.get("grader", {}).get("reuse", {}).get("reason") != "force_grader":
        errors.append("--force-grader did not explain grader reuse miss as force_grader")
    reuse_summary = force_grader_payload.get("reuse_summary", {})
    if reuse_summary.get("miss_reasons", {}).get("force_grader") != 1:
        errors.append("--force-grader reuse summary should count force_grader miss")


def verify_delegated_ci_json(root: Path, env: dict, errors: list[str]) -> None:
    completed = run_profile(
        root,
        env,
        "ci",
        skill=root / "missing-skill",
        output_dir=root / "ci-output",
    )
    if completed.returncode != 2:
        errors.append(f"delegated ci missing skill should exit 2, got {completed.returncode}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f"delegated ci --format json stdout was not clean JSON: {exc}: {completed.stdout[:200]!r}")
        return
    if payload.get("profile") != "ci":
        errors.append(f"delegated ci profile was {payload.get('profile')!r}")
    if payload.get("exit_code") != 2:
        errors.append(f"delegated ci payload exit_code was {payload.get('exit_code')!r}")
    if "delegated_stdout" not in payload:
        errors.append("delegated ci payload missing captured stdout")


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
        today = datetime.now().strftime("%Y-%m-%d")
        fixture_session_root = root / "sessions" / "fixture-skill"
        fixture_session_root.mkdir(parents=True)
        (fixture_session_root / f"{today}_scratch").mkdir()
        (fixture_session_root / f"{today}_002").mkdir()

        lint_session = verify_lint(root, env, skill, cases, errors)
        if lint_session is not None:
            if not lint_session.name.endswith("_003"):
                errors.append(f"lint session should ignore non-numeric session names and use _003, got {lint_session.name}")
            verify_debug(root, env, lint_session, errors)
        verify_local(root, env, skill, cases, errors)
        verify_delegated_ci_json(root, env, errors)
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
