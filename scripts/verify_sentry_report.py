#!/usr/bin/env python3
"""Verify deterministic sentry_report.py behavior."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import sentry_report
import sentry_state


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_contains(text: str, marker: str, label: str, errors: list[str]) -> None:
    if marker not in text:
        errors.append(f"{label}: missing {marker!r}")


def make_session(root: Path, verdict: str = "CONDITIONAL PASS") -> tuple[Path, dict]:
    session_dir = root / verdict.lower().replace(" ", "-")
    session_dir.mkdir(parents=True)
    sentry_state.save_session(
        session_dir,
        {
            "skill": "report-fixture",
            "mode": "standard",
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "preflight": {
                "status": "OK",
                "skill_type": "text_generation",
                "skill_hash_short": "fixture",
                "runtime_tools": {
                    "claude_cli": {"available": False},
                    "anthropic_sdk": {"available": True},
                    "anthropic_api_key": {"configured": True},
                },
            },
            "sync": {"pull": "skipped_no_config", "push_cases": "skipped_no_config", "push_results": "skipped_no_config"},
            "case_warnings": [{"case_id": "eval-1", "reason": "fixture warning"}],
            "publish": {"status": "OK"},
        },
    )
    gate = {
        "verdict": verdict,
        "grade": "B",
        "authoritative_pass_rate": 0.75,
        "delta": {"status": "no_baseline"},
        "decision_reasons": ["fixture reason"],
    }
    save_json(session_dir / "gate-result.json", gate)
    return session_dir, gate


def verify_session_report(root: Path, errors: list[str]) -> None:
    session_dir, gate = make_session(root)
    report = sentry_report.write_session_report(session_dir, gate)
    text = report.read_text(encoding="utf-8")
    for marker in ("SkillSentry Report", "CONDITIONAL PASS", "Execution Diagnostics", "skipped_no_config"):
        assert_contains(text, marker, "session report", errors)


def verify_preserve_interactive_report(root: Path, errors: list[str]) -> None:
    session_dir, gate = make_session(root, "PASS")
    report = session_dir / "report.html"
    report.write_text("<html><body>Interactive grader report</body></html>", encoding="utf-8")
    kept = sentry_report.ensure_session_report(session_dir, gate)
    text = kept.read_text(encoding="utf-8")
    if text != "<html><body>Interactive grader report</body></html>":
        errors.append("ensure_session_report overwrote a non-generated interactive report")


def verify_ci_result_report(root: Path, errors: list[str]) -> None:
    result = {
        "skill": "report-fixture",
        "mode": "smoke",
        "verdict": "ERROR",
        "status": "error",
        "exit_code": 2,
        "reasons": ["Pipeline step failed"],
        "summary": {},
        "diagnostics": {
            "categories": ["preflight_error"],
            "preflight": {"status": "ERROR", "skill_type": "N/A", "claude_cli_available": False},
            "notes": ["skill_not_found"],
        },
    }
    result_file = root / "eval_result.json"
    save_json(result_file, result)

    output = root / "from-result.html"
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "sentry_report.py"),
            "--result",
            str(result_file),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        errors.append(f"sentry_report.py --result exited {completed.returncode}: {completed.stderr.strip()}")
        return
    text = output.read_text(encoding="utf-8")
    for marker in ("SkillSentry CI Result", "Pipeline step failed", "preflight_error", "skill_not_found"):
        assert_contains(text, marker, "result report", errors)


def verify_ci_artifacts(root: Path, errors: list[str]) -> None:
    session_dir, _gate = make_session(root, "FAIL")
    results = {
        "verdict": "ERROR",
        "reasons": ["forced failure"],
        "summary": {},
        "diagnostics": {"categories": ["runner_timeout"], "notes": ["timeout"]},
    }
    artifacts = sentry_report.ensure_ci_report_artifacts(
        root / "out",
        results,
        skill="report-fixture",
        mode="quick",
        session_dir=session_dir,
        generated_by="verify_sentry_report.py",
    )
    for key in ("output_report_html", "session_report_html"):
        path = Path(artifacts.get(key, ""))
        if not path.exists():
            errors.append(f"missing artifact report: {key}")
            continue
        text = path.read_text(encoding="utf-8")
        assert_contains(text, "SkillSentry CI Result", key, errors)
        assert_contains(text, "runner_timeout", key, errors)


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-report-") as tmp:
        root = Path(tmp)
        verify_session_report(root, errors)
        verify_preserve_interactive_report(root, errors)
        verify_ci_result_report(root, errors)
        verify_ci_artifacts(root, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify deterministic sentry_report.py behavior")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry report: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
