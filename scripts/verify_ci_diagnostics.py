#!/usr/bin/env python3
"""Verify deterministic CI diagnostics are surfaced in JSON, Markdown, and HTML."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sentry_ci
import sentry_publish
import sentry_state
from sentry_diagnostics import collect_diagnostics


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_session(root: Path) -> Path:
    session_dir = root / "session"
    session_dir.mkdir()
    sentry_state.save_session(
        session_dir,
        {
            "skill": "diagnostic-fixture",
            "mode": "standard",
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "last_step": "publish",
            "pipeline": [
                "static",
                "cases",
                "sync-pull",
                "sync-push-cases",
                "executor-with",
                "executor-without",
                "comparator",
                "grader-report",
                "sync-push-results",
                "gate",
                "publish",
            ],
            "completed_steps": [],
            "case_warnings": [
                {
                    "case_id": "eval-1",
                    "type": "missing_local_path",
                    "path": "C:\\missing\\fixture.txt",
                    "message": "Generated case references a local path that does not exist.",
                }
            ],
            "sync": {
                "pull": {"status": "skipped_no_config", "message": "no config"},
                "push_cases": {"status": "OK", "message": "fixture"},
                "push_results": {"status": "skipped_no_config", "message": "no config"},
                "push_run": None,
            },
            "ci_step_timings": [
                {"step": "cases", "tool": "sentry-cases", "status": "OK", "duration_ms": 12.5},
                {"step": "executor-with", "tool": "sentry-executor", "status": "OK", "duration_ms": 45.0},
                {"step": "grader-report", "tool": "sentry-grader", "status": "OK", "duration_ms": 30.0},
            ],
            "ci_phase_timings": [
                {"phase": "preflight", "status": "OK", "duration_ms": 5.0},
                {"phase": "session", "status": "OK", "duration_ms": 3.0},
            ],
            "ci_timing": {"total_ms": 100.0, "failed_steps": []},
            "ci": True,
        },
    )

    save_json(
        session_dir / "evals.json",
        [
            {
                "id": "eval-1",
                "name": "diagnostic fixture",
                "prompt": "Return OK",
                "assertions": [
                    {"name": "contains OK", "type": "exact_match", "expected": "OK", "rule_ref": "fixture"}
                ],
            }
        ],
    )
    save_json(
        session_dir / "executor_results.json",
        {
            "total": 2,
            "success": 1,
            "failed": 1,
            "results": [
                {"eval_id": "eval-1", "status": "success", "duration": 0.4},
                {"eval_id": "eval-2", "status": "timeout", "duration": 1.5, "error": "Timeout after 1s"},
            ],
        },
    )
    save_json(
        session_dir / "eval-1" / "grading.json",
        {
            "eval_id": "eval-1",
            "duration_ms": 250.0,
            "timing": {"grader_duration_ms": 250.0},
            "runs": {
                "run-1": {
                    "pass": False,
                    "assertions": [
                        {
                            "id": "contains OK",
                            "type": "exact_match",
                            "expect": "OK",
                            "pass": False,
                            "evidence": "LLM grader call failed",
                        }
                    ],
                }
            },
            "summary": {
                "pass": 0,
                "fail": 1,
                "total": 1,
                "precision_breakdown": {"exact_match": {"pass": 0, "total": 1}},
                "authoritative_pass_rate": 0.0,
                "grader_error": "LLM grader call failed",
            },
        },
    )
    save_json(
        session_dir / "publish-result.json",
        {"status": "OK", "message": "local publish result ready", "artifacts": [], "updated_at": "2026-01-01T00:00:00+00:00"},
    )
    gate = sentry_ci.build_gate(session_dir)
    save_json(session_dir / "gate-result.json", gate)
    return session_dir


def make_quality_failure_session(root: Path) -> Path:
    session_dir = root / "quality-session"
    session_dir.mkdir()
    sentry_state.save_session(
        session_dir,
        {
            "skill": "quality-fixture",
            "mode": "standard",
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "last_step": "gate",
            "pipeline": ["executor-with", "grader-report", "gate"],
            "completed_steps": [],
            "case_warnings": [],
            "sync": {
                "pull": {"status": "OK", "message": "fixture"},
                "push_cases": {"status": "OK", "message": "fixture"},
                "push_results": {"status": "OK", "message": "fixture"},
                "push_run": None,
            },
            "ci": True,
        },
    )
    save_json(
        session_dir / "executor_results.json",
        {"total": 1, "success": 1, "failed": 0, "results": [{"eval_id": "eval-1", "status": "success"}]},
    )
    save_json(
        session_dir / "eval-1" / "grading.json",
        {
            "eval_id": "eval-1",
            "runs": {
                "run-1": {
                    "pass": False,
                    "assertions": [
                        {
                            "id": "contains OK",
                            "type": "exact_match",
                            "expect": "OK",
                            "pass": False,
                            "evidence": "response did not satisfy assertion",
                        }
                    ],
                }
            },
            "summary": {
                "pass": 0,
                "fail": 1,
                "total": 1,
                "precision_breakdown": {"exact_match": {"pass": 0, "total": 1}},
                "authoritative_pass_rate": 0.0,
            },
        },
    )
    gate = sentry_ci.build_gate(session_dir)
    save_json(session_dir / "gate-result.json", gate)
    return session_dir


def assert_contains(container, value: str, label: str, errors: list[str]) -> None:
    if value not in container:
        errors.append(f"{label}: missing {value!r}")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-diagnostics-") as tmp:
        root = Path(tmp)
        session_dir = make_session(root)
        gate = json.loads((session_dir / "gate-result.json").read_text(encoding="utf-8"))

        diagnostics = collect_diagnostics(session_dir, gate)
        for category in ("case_unusable", "runner_timeout", "grader_error", "environment_skipped"):
            assert_contains(diagnostics.get("categories", []), category, "diagnostic categories", errors)
        if "quality_failure" in diagnostics.get("categories", []):
            errors.append("diagnostic categories: technical failures must not also be quality_failure")
        if diagnostics.get("case_warnings_count") != 1:
            errors.append("case_warnings_count: expected 1")
        if diagnostics.get("executor", {}).get("timeouts") != 1:
            errors.append("executor.timeouts: expected 1")
        if diagnostics.get("sync", {}).get("pull") != "skipped_no_config":
            errors.append("sync.pull: expected skipped_no_config")
        if diagnostics.get("timings", {}).get("total_ms") != 100.0:
            errors.append("timings.total_ms: expected 100.0")
        if diagnostics.get("timings", {}).get("slowest_steps", [{}])[0].get("step") != "executor-with":
            errors.append("timings.slowest_steps[0]: expected executor-with")
        if diagnostics.get("timings", {}).get("phases", [{}])[0].get("phase") != "preflight":
            errors.append("timings.phases[0]: expected preflight")
        if diagnostics.get("timings", {}).get("executor_cases", {}).get("slowest_cases", [{}])[0].get("eval_id") != "eval-2":
            errors.append("timings.executor_cases.slowest_cases[0]: expected eval-2")
        if diagnostics.get("timings", {}).get("grader_cases", {}).get("duration_ms", {}).get("p50") != 250.0:
            errors.append("timings.grader_cases.duration_ms.p50: expected 250.0")

        sentry_ci.write_minimal_report(session_dir, gate)
        report_text = (session_dir / "report.html").read_text(encoding="utf-8")
        for marker in ("Execution Diagnostics", "runner_timeout", "LLM grader call failed", "skipped_no_config", "Step timings", "Phase timings", "Executor case timings", "Grader case timings", "p50=250.0ms", "p95=250.0ms"):
            assert_contains(report_text, marker, "ci report.html", errors)

        args = SimpleNamespace(skill="diagnostic-fixture", mode="standard", threshold=0.8, github_output=False)
        results = sentry_ci.collect_results(session_dir, args)
        output_dir = root / "out"
        sentry_ci.write_ci_output(output_dir, results, args)
        output_json = json.loads((output_dir / "eval_result.json").read_text(encoding="utf-8"))
        summary_md = (output_dir / "summary.md").read_text(encoding="utf-8")
        if "diagnostics" not in output_json:
            errors.append("eval_result.json: missing diagnostics")
        if output_json.get("timings", {}).get("total_ms") != 100.0:
            errors.append("eval_result.json: missing top-level timings")
        for marker in ("Execution Diagnostics", "runner_timeout", "skipped_no_config", "CI timing", "CI phases", "Executor case timing", "Grader case timing", "p50=250.0ms", "p95=250.0ms"):
            assert_contains(summary_md, marker, "summary.md", errors)

        sentry_publish.ensure_report(session_dir, gate)
        publish_report = (session_dir / "report.html").read_text(encoding="utf-8")
        for marker in ("SkillSentry Publish Result", "Execution Diagnostics", "Publish</th><td>OK"):
            assert_contains(publish_report, marker, "publish report.html", errors)

        quality_dir = make_quality_failure_session(root)
        quality_gate = json.loads((quality_dir / "gate-result.json").read_text(encoding="utf-8"))
        quality_diagnostics = collect_diagnostics(quality_dir, quality_gate)
        assert_contains(quality_diagnostics.get("categories", []), "quality_failure", "quality diagnostics", errors)
        for category in ("case_unusable", "runner_timeout", "grader_error"):
            if category in quality_diagnostics.get("categories", []):
                errors.append(f"quality diagnostics: unexpected {category}")

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify SkillSentry CI diagnostics")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ci diagnostics: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
