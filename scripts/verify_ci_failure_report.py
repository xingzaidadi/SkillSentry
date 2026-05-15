#!/usr/bin/env python3
"""Verify CI writes stable HTML reports for failure paths."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sentry_ci
import sentry_state


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def save_session(session_dir: Path) -> None:
    sentry_state.save_session(
        session_dir,
        {
            "skill": "failure-report-fixture",
            "mode": "smoke",
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "preflight": {
                "status": "OK",
                "skill_type": "text_generation",
                "skill_hash_short": "fixture",
                "runtime_tools": {
                    "claude_cli": {"available": False, "path": None},
                    "anthropic_sdk": {"available": True},
                    "anthropic_api_key": {"configured": True},
                    "llm_fallback": {"mode": None},
                },
            },
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
            "case_warnings": [],
        },
    )


def verify_direct_failure_report(root: Path, errors: list[str]) -> None:
    session_dir = root / "session"
    session_dir.mkdir()
    save_session(session_dir)
    args = SimpleNamespace(skill="failure-report-fixture", mode="smoke", threshold=0.8, github_output=False)
    results = {
        "verdict": "ERROR",
        "reasons": ["Pipeline 步骤失败: executor-with"],
        "summary": {},
        "diagnostics": sentry_ci.collect_diagnostics(session_dir),
    }
    output_dir = root / "out"
    sentry_ci.write_ci_output(output_dir, results, args, session_dir=session_dir)

    for report in (output_dir / "report.html", session_dir / "report.html"):
        if not report.exists():
            errors.append(f"missing report: {report}")
            continue
        text = report.read_text(encoding="utf-8")
        for marker in ("SkillSentry CI Result", "Execution Diagnostics", "Pipeline 步骤失败"):
            if marker not in text:
                errors.append(f"{report.name}: missing {marker!r}")

    payload = json.loads((output_dir / "eval_result.json").read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts", {})
    if not artifacts.get("output_report_html") or not artifacts.get("session_report_html"):
        errors.append("eval_result.json artifacts missing report paths")


def verify_preflight_failure_report(root: Path, errors: list[str]) -> None:
    output_dir = root / "preflight-out"
    missing_skill = root / "missing" / "SKILL.md"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "sentry_ci.py"),
        "--skill",
        str(missing_skill),
        "--mode",
        "smoke",
        "--output-dir",
        str(output_dir),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 2:
        errors.append(f"preflight failure expected exit 2, got {completed.returncode}")

    report = output_dir / "report.html"
    if not report.exists():
        errors.append("preflight failure did not write output report.html")
    else:
        text = report.read_text(encoding="utf-8")
        for marker in ("SkillSentry CI Result", "preflight_error", "skill_not_found"):
            if marker not in text:
                errors.append(f"preflight report missing {marker!r}")

    result_file = output_dir / "eval_result.json"
    if not result_file.exists():
        errors.append("preflight failure did not write eval_result.json")
    else:
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if not payload.get("artifacts", {}).get("output_report_html"):
            errors.append("preflight eval_result.json missing output report artifact")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-failure-report-") as tmp:
        root = Path(tmp)
        verify_direct_failure_report(root, errors)
        verify_preflight_failure_report(root, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify CI failure report artifacts")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ci failure report: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
