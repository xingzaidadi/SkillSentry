#!/usr/bin/env python3
"""Verify GitHub Actions/Checks integration consumes sentry_ci outputs."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import report_to_checks


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "skill-eval.yml"


def make_result(verdict: str, status: str, exit_code: int) -> dict:
    return {
        "skill": "checks-fixture",
        "mode": "smoke",
        "threshold": 0.8,
        "verdict": verdict,
        "status": status,
        "exit_code": exit_code,
        "reasons": [f"fixture {verdict}"],
        "summary": {
            "authoritative_pass_rate": 1.0 if status == "pass" else 0.75,
            "grade": "S" if status == "pass" else "C",
            "delta": {"status": "N/A", "value": None},
        },
        "diagnostics": {
            "categories": [] if status == "pass" else ["fixture_category"],
            "notes": ["fixture diagnostic note"],
            "timing_hints": ["fixture timing hint"],
            "executor": {"total": 1, "success": 1 if status == "pass" else 0, "failed": 0, "timeouts": 0},
        },
        "artifacts": {
            "output_report_html": "ci-eval-results/checks-fixture/report.html",
            "session_report_html": "sessions/checks-fixture/report.html",
        },
        "evaluated_at": "2026-01-01T00:00:00+00:00",
    }


def verify_payloads(errors: list[str]) -> None:
    expected = {
        "PASS": ("pass", 0, "success"),
        "CONDITIONAL PASS": ("conditional", 1, "action_required"),
        "FAIL": ("fail", 1, "failure"),
        "ERROR": ("error", 2, "failure"),
    }
    for verdict, (status, exit_code, conclusion) in expected.items():
        payload = report_to_checks.build_check_payload(make_result(verdict, status, exit_code), "SkillSentry / fixture", "abc123")
        if payload.get("conclusion") != conclusion:
            errors.append(f"{verdict}: expected conclusion {conclusion}, got {payload.get('conclusion')}")
        output = payload.get("output", {})
        summary = output.get("summary", "")
        for marker in (status, "Report", "fixture diagnostic note", "fixture timing hint", "Authoritative pass rate"):
            if marker not in summary:
                errors.append(f"{verdict}: check summary missing {marker!r}")
        if "SkillSentry / fixture" != payload.get("name"):
            errors.append(f"{verdict}: check name was not preserved")
    malformed = make_result("PASS", "pass", 0)
    malformed["diagnostics"]["timing_hints"] = "single timing hint"
    payload = report_to_checks.build_check_payload(malformed, "SkillSentry / fixture", "abc123")
    if "single timing hint" not in payload.get("output", {}).get("summary", ""):
        errors.append("single-string timing_hints was not rendered as one hint")
    with tempfile.TemporaryDirectory(prefix="skillsentry-checks-") as tmp:
        result_file = Path(tmp) / "eval_result.json"
        fixture = make_result("PASS", "pass", 0)
        result_file.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
        loaded = report_to_checks.load_result(str(result_file))
        if loaded.get("verdict") != "PASS":
            errors.append("load_result should read UTF-8 BOM eval_result.json")


def verify_workflow(errors: list[str]) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = [
        "scripts/sentry_ci.py",
        "--github-output",
        "continue-on-error: true",
        "d.get('exit_code', 2)",
        "options: [smoke, quick, regression, standard, full]",
        "scripts/report_to_checks.py",
        "~/.claude/skills/SkillSentry/scripts/sentry_ci.py",
        "SESSION_ROOT=~/.claude/skills/SkillSentry/sessions",
        'if [ -d "$SESSION_ROOT" ]; then',
    ]
    for marker in required:
        if marker not in text:
            errors.append(f"workflow missing {marker!r}")
    if "scripts/ci_eval.py" in text:
        errors.append("workflow still references legacy scripts/ci_eval.py")
    if "测评 ${{ matrix.skill }} 模式=$MODE 自动" in text:
        errors.append("workflow still delegates CI run to an LLM prompt")
    if "skill-eval-测评" in text:
        errors.append("workflow still uses legacy skill-eval-测评 install path")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    verify_payloads(errors)
    verify_workflow(errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify CI Checks integration")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ci checks integration: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
