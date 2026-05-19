#!/usr/bin/env python3
"""Verify sentry_timing.py deterministic timing analysis."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import sentry_timing
import sentry_state


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_timing_payload() -> dict:
    return {
        "total_ms": 150.0,
        "steps": [
            {"step": "cases", "tool": "sentry-cases", "status": "OK", "duration_ms": 10.0},
            {"step": "executor-with", "tool": "sentry-executor", "status": "OK", "duration_ms": 100.0},
            {"step": "grader-report", "tool": "sentry-grader", "status": "OK", "duration_ms": 40.0},
        ],
        "phases": [
            {"phase": "preflight", "status": "OK", "duration_ms": 5.0},
            {"phase": "collect_results", "status": "OK", "duration_ms": 7.0},
        ],
        "failed_steps": [],
    }


def make_executor_payload() -> dict:
    return {
        "total": 3,
        "success": 2,
        "failed": 1,
        "results": [
            {"eval_id": "eval-1", "name": "fast", "status": "success", "duration": 0.2},
            {"eval_id": "eval-2", "name": "slow", "status": "success", "duration": 5.0},
            {"eval_id": "eval-3", "name": "failed", "status": "failed", "duration": 1.2},
        ],
    }


def make_grading_payload(eval_id: str, duration_ms: float, total: int = 2) -> dict:
    return {
        "eval_id": eval_id,
        "duration_ms": duration_ms,
        "runs": {"run-1": {"pass": True, "assertions": []}},
        "summary": {"pass": total, "fail": 0, "total": total, "authoritative_pass_rate": 1.0},
    }


def make_cases() -> list[dict]:
    return [
        {"id": "eval-1", "prompt": "fast"},
        {"id": "eval-2", "prompt": "slow"},
    ]


def verify_eval_result(root: Path, errors: list[str]) -> None:
    session_dir = root / "eval-result-session"
    session_dir.mkdir()
    save_json(session_dir / "session.json", {"skill": "timing-fixture", "mode": "smoke"})
    save_json(session_dir / "executor_results.json", make_executor_payload())
    save_json(session_dir / "eval-1" / "grading.json", make_grading_payload("eval-1", 300.0))
    save_json(session_dir / "eval-2" / "grading.json", make_grading_payload("eval-2", 900.0))
    (session_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    result_file = root / "eval_result.json"
    save_json(
        result_file,
        {
            "verdict": "PASS",
            "status": "pass",
            "timings": make_timing_payload(),
            "artifacts": {"session_report_html": str(session_dir / "report.html")},
        },
    )
    payload = sentry_timing.analyze(result_file, top=2)
    if payload.get("status") != "OK":
        errors.append("eval_result analysis did not return OK")
    if payload.get("top_steps", [{}])[0].get("step") != "executor-with":
        errors.append("eval_result top step should be executor-with")
    if len(payload.get("top_steps", [])) != 2:
        errors.append("eval_result top limit was not applied")
    if "Executor dominates" not in payload.get("recommendation", ""):
        errors.append("eval_result recommendation should mention executor")
    executor = payload.get("executor_timing", {})
    if not executor.get("available"):
        errors.append("eval_result should resolve executor timing from session_report_html")
    if executor.get("slowest_cases", [{}])[0].get("eval_id") != "eval-2":
        errors.append("eval_result executor slowest case should be eval-2")
    grader = payload.get("grader_timing", {})
    if not grader.get("available"):
        errors.append("eval_result should resolve grader timing from session_report_html")
    if grader.get("slowest_cases", [{}])[0].get("eval_id") != "eval-2":
        errors.append("eval_result grader slowest case should be eval-2")


def verify_session(root: Path, errors: list[str]) -> None:
    session_dir = root / "session"
    session_dir.mkdir()
    timing = make_timing_payload()
    sentry_state.save_session(
        session_dir,
        {
            "skill": "timing-fixture",
            "mode": "smoke",
            "last_step": "publish",
            "ci_step_timings": timing["steps"],
            "ci_phase_timings": timing["phases"],
            "ci_timing": {"total_ms": timing["total_ms"], "failed_steps": []},
        },
    )
    save_json(session_dir / "evals.json", make_cases())
    save_json(session_dir / "executor_results.json", make_executor_payload())
    save_json(session_dir / "eval-1" / "grading.json", make_grading_payload("eval-1", 300.0))
    save_json(session_dir / "eval-2" / "grading.json", make_grading_payload("eval-2", 900.0))
    save_json(session_dir / "eval-stale" / "grading.json", make_grading_payload("eval-stale", 9999.0))
    payload = sentry_timing.analyze(session_dir, top=5)
    if payload.get("source", {}).get("kind") != "session":
        errors.append("session analysis source kind should be session")
    if payload.get("total_ms") != 150.0:
        errors.append("session total_ms should be 150.0")
    executor = payload.get("executor_timing", {})
    variants = executor.get("variants", [])
    if not variants or variants[0].get("duration_ms", {}).get("p95") != 4760.0:
        errors.append("session executor timing p95 should ignore stale executor cases")
    if executor.get("expected_cases") != 2 or variants[0].get("total") != 2:
        errors.append("session executor timing total should reflect current evals.json case count")
    grader = payload.get("grader_timing", {})
    if grader.get("duration_ms", {}).get("p50") != 600.0:
        errors.append("session grader timing p50 should be 600.0ms")
    if grader.get("grading_files") != 2:
        errors.append("session grader timing should ignore stale grading files outside evals.json")
    if grader.get("total") != 2 or grader.get("expected_cases") != 2:
        errors.append("session grader timing total should reflect current evals.json case count")

    partial_dir = root / "partial-session"
    partial_dir.mkdir()
    sentry_state.save_session(partial_dir, {"skill": "timing-fixture", "mode": "local"})
    save_json(partial_dir / "evals.json", make_cases())
    save_json(partial_dir / "eval-1" / "grading.json", make_grading_payload("eval-1", 300.0))
    partial_payload = sentry_timing.analyze(partial_dir, top=5)
    partial_grader = partial_payload.get("grader_timing", {})
    if partial_grader.get("total") != 2 or partial_grader.get("timed") != 1:
        errors.append("partial grader timing should report total current cases and timed grading files")
    if partial_grader.get("missing_cases") != 1 or partial_grader.get("missing_case_ids") != ["eval-2"]:
        errors.append("partial grader timing should report missing current case ids")
    partial_executor = partial_payload.get("executor_timing", {})
    if partial_executor.get("available") is not False or partial_executor.get("expected_cases") != 2:
        errors.append("partial executor timing should report expected current cases when summary is missing")

    partial_executor_dir = root / "partial-executor-session"
    partial_executor_dir.mkdir()
    sentry_state.save_session(partial_executor_dir, {"skill": "timing-fixture", "mode": "local"})
    save_json(partial_executor_dir / "evals.json", make_cases())
    save_json(
        partial_executor_dir / "executor_results.json",
        {
            "results": [
                {"eval_id": "eval-1", "name": "fast", "status": "success", "duration": 0.2},
                {"eval_id": "eval-2", "name": "failed", "status": "failed"},
                {"eval_id": "eval-stale", "name": "stale", "status": "failed", "duration": 99.0},
            ],
        },
    )
    partial_executor_payload = sentry_timing.analyze(partial_executor_dir, top=5)
    partial_variant = partial_executor_payload.get("executor_timing", {}).get("variants", [{}])[0]
    if partial_variant.get("total") != 2 or partial_variant.get("timed") != 1 or partial_variant.get("failed") != 1:
        errors.append("partial executor timing should count failed current cases even without duration")
    if partial_variant.get("missing_cases") != 0:
        errors.append("partial executor timing should not treat untimed reported cases as missing")

    missing_executor_dir = root / "missing-executor-case-session"
    missing_executor_dir.mkdir()
    sentry_state.save_session(missing_executor_dir, {"skill": "timing-fixture", "mode": "local"})
    save_json(missing_executor_dir / "evals.json", make_cases())
    save_json(
        missing_executor_dir / "executor_results.json",
        {"results": [{"eval_id": "eval-1", "name": "fast", "status": "success", "duration": 0.2}]},
    )
    missing_executor_payload = sentry_timing.analyze(missing_executor_dir, top=5)
    missing_variant = missing_executor_payload.get("executor_timing", {}).get("variants", [{}])[0]
    if missing_variant.get("missing_cases") != 1 or missing_variant.get("missing_case_ids") != ["eval-2"]:
        errors.append("executor timing should report missing current case ids")
    if not any("executor with_skill is missing 1" in hint for hint in missing_executor_payload.get("timing_hints", [])):
        errors.append("executor timing should include missing current case hint")


def verify_sentry_run_result(root: Path, errors: list[str]) -> None:
    session_dir = root / "run-result-session"
    session_dir.mkdir()
    sentry_state.save_session(session_dir, {"skill": "timing-fixture", "mode": "local"})
    save_json(session_dir / "executor_results.json", make_executor_payload())
    save_json(session_dir / "eval-1" / "grading.json", make_grading_payload("eval-1", 300.0))
    save_json(session_dir / "eval-2" / "grading.json", make_grading_payload("eval-2", 900.0))
    result_file = root / "sentry-run-result.json"
    run_result = {
        "status": "OK",
        "profile": "local",
        "session_dir": str(session_dir),
        "timings": {
            "total_ms": 1800.0,
            "phases_ms": {"preflight": 10.0, "executor": 1200.0, "grader": 500.0, "diagnostics": 90.0},
        },
        "executor": {
            "step": "executor-with",
            "reused": True,
            "reuse": {"reusable": True, "reason": "matched"},
        },
        "grader": {
            "step": "grader-report",
            "reused": False,
            "reuse": {"reusable": False, "reason": "missing_outputs"},
        },
        "reuse_summary": {
            "steps": [
                {"step": "executor-with", "reused": True, "reusable": True, "reason": "matched"},
                {"step": "grader-report", "reused": False, "reusable": False, "reason": "missing_outputs"},
            ],
            "reused_steps": ["executor-with"],
            "rerun_steps": ["grader-report"],
            "miss_reasons": {"missing_outputs": 1},
            "all_reused": False,
        },
    }
    save_json(result_file, run_result)
    save_json(session_dir / "sentry-run-result.json", run_result)
    payload = sentry_timing.analyze(result_file, top=2)
    if payload.get("source", {}).get("kind") != "sentry_run_result":
        errors.append("sentry-run-result source kind should be sentry_run_result")
    if payload.get("top_phases", [{}])[0].get("phase") != "executor":
        errors.append("sentry-run-result top phase should be executor")
    if "Executor dominates" not in payload.get("recommendation", ""):
        errors.append("sentry-run-result recommendation should mention executor")
    decisions = payload.get("reuse_decisions", [])
    if len(decisions) != 2 or decisions[0].get("reason") != "matched" or decisions[1].get("reason") != "missing_outputs":
        errors.append("sentry-run-result should include executor/grader reuse decisions")
    if payload.get("reuse_summary", {}).get("rerun_steps") != ["grader-report"]:
        errors.append("sentry-run-result should include reuse summary rerun steps")
    if not any("Required outputs are missing" in hint for hint in payload.get("reuse_hints", [])):
        errors.append("sentry-run-result should derive reuse hints from miss reasons")
    text = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(result_file),
            "--format",
            "text",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if text.returncode != 0:
        errors.append(f"sentry_timing.py text sentry-run-result exited {text.returncode}: {text.stderr.strip()} {text.stdout.strip()}")
    for marker in ("reuse decisions:", "rerun steps: grader-report", "reuse hints:", "Required outputs are missing"):
        if marker not in text.stdout:
            errors.append(f"sentry_timing.py text sentry-run-result missing {marker!r}")
    if not payload.get("executor_timing", {}).get("available"):
        errors.append("sentry-run-result should resolve executor timing from session_dir")
    if not payload.get("grader_timing", {}).get("available"):
        errors.append("sentry-run-result should resolve grader timing from session_dir")
    session_payload = sentry_timing.analyze(session_dir, top=2)
    if session_payload.get("source", {}).get("kind") != "sentry_run_result":
        errors.append("local session dir should fall back to sentry-run-result.json timing")
    if session_payload.get("top_phases", [{}])[0].get("phase") != "executor":
        errors.append("local session dir fallback should preserve profile phase timings")
    run_result_without_session_dir = dict(run_result)
    run_result_without_session_dir.pop("session_dir", None)
    save_json(session_dir / "sentry-run-result.json", run_result_without_session_dir)
    inferred_payload = sentry_timing.analyze(session_dir / "sentry-run-result.json", top=2)
    if not inferred_payload.get("executor_timing", {}).get("available"):
        errors.append("sentry-run-result next to session.json should infer session_dir")
    legacy_run_result = dict(run_result)
    legacy_run_result.pop("reuse_summary", None)
    save_json(result_file, legacy_run_result)
    legacy_payload = sentry_timing.analyze(result_file, top=2)
    if legacy_payload.get("reuse_summary", {}).get("rerun_steps") != ["grader-report"]:
        errors.append("legacy sentry-run-result should synthesize reuse summary rerun steps")
    if not any("Required outputs are missing" in hint for hint in legacy_payload.get("reuse_hints", [])):
        errors.append("legacy sentry-run-result should synthesize reuse hints")


def verify_cli(root: Path, errors: list[str]) -> None:
    result_file = root / "cli-eval-result.json"
    save_json(result_file, {"timings": make_timing_payload()})
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(result_file),
            "--format",
            "json",
            "--top",
            "1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        errors.append(f"sentry_timing.py exited {completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}")
        return
    payload = json.loads(completed.stdout)
    if len(payload.get("top_steps", [])) != 1:
        errors.append("CLI top limit was not applied")
    missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(root / "missing.json"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if missing.returncode != 2:
        errors.append(f"sentry_timing.py missing input exit expected 2, got {missing.returncode}")
    empty_session = root / "empty-session"
    empty_session.mkdir()
    sentry_state.save_session(empty_session, {"skill": "timing-fixture", "mode": "local"})
    text = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(empty_session),
            "--format",
            "text",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if text.returncode != 0:
        errors.append(f"sentry_timing.py text empty session exited {text.returncode}: {text.stderr.strip()} {text.stdout.strip()}")
    if "executor timing: unavailable" not in text.stdout:
        errors.append("text output should explain unavailable executor timing")

    missing_artifacts = root / "missing-artifacts-session"
    missing_artifacts.mkdir()
    sentry_state.save_session(missing_artifacts, {"skill": "timing-fixture", "mode": "local"})
    save_json(missing_artifacts / "evals.json", make_cases())
    text_expected = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(missing_artifacts),
            "--format",
            "text",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if text_expected.returncode != 0:
        errors.append(f"sentry_timing.py text expected cases exited {text_expected.returncode}: {text_expected.stderr.strip()} {text_expected.stdout.strip()}")
    if "expected_cases=2" not in text_expected.stdout:
        errors.append("text output should include expected_cases for unavailable executor/grader timing")

    save_json(missing_artifacts / "executor_results.json", {"results": [{"eval_id": "eval-1", "status": "success", "duration": 0.2}]})
    save_json(missing_artifacts / "eval-1" / "grading.json", make_grading_payload("eval-1", 300.0))
    text_missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_timing.py"),
            "--input",
            str(missing_artifacts),
            "--format",
            "text",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if text_missing.returncode != 0:
        errors.append(f"sentry_timing.py text missing cases exited {text_missing.returncode}: {text_missing.stderr.strip()} {text_missing.stdout.strip()}")
    if "missing=1" not in text_missing.stdout:
        errors.append("text output should include missing current case count")
    if "timing hints:" not in text_missing.stdout:
        errors.append("text output should include timing hints for missing current cases")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-timing-verify-") as tmp:
        root = Path(tmp)
        verify_eval_result(root, errors)
        verify_session(root, errors)
        verify_sentry_run_result(root, errors)
        verify_cli(root, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_timing.py")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry timing: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
