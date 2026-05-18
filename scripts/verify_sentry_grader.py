#!/usr/bin/env python3
"""Verify stable sentry_grader.py wrapper behavior without real LLM calls."""

from __future__ import annotations

import argparse
import json
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


def make_session(root: Path) -> Path:
    session_dir = root / "session"
    session_dir.mkdir()
    sentry_state.save_session(
        session_dir,
        {
            "skill": "grader-fixture",
            "mode": "smoke",
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
            "case_warnings": [],
        },
    )
    eval_dir = session_dir / "eval-1" / "with_skill" / "outputs"
    eval_dir.mkdir(parents=True)
    (eval_dir / "response.md").write_text("[EXECUTION FAILED]\nfake failure", encoding="utf-8")
    (eval_dir / "transcript.md").write_text("fake transcript", encoding="utf-8")
    return session_dir


def verify_success_path(root: Path, errors: list[str]) -> None:
    evals_file = root / "evals.json"
    save_json(
        evals_file,
        [
            {
                "id": "eval-1",
                "name": "fixture",
                "prompt": "fixture",
                "assertions": [
                    {"name": "A1", "type": "exact_match", "expected": "ok", "rule_ref": "R1"},
                    {"name": "A2", "type": "semantic", "expected": "works", "rule_ref": "R2"},
                ],
            }
        ],
    )
    session_dir = make_session(root)
    output = root / "grader-result.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "sentry_grader.py"),
            "--evals",
            str(evals_file),
            "--session-dir",
            str(session_dir),
            "--output",
            str(output),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        errors.append(f"sentry_grader.py exited {completed.returncode}: {completed.stderr.strip()}")
        return

    payload = load_json(output)
    if payload.get("status") != "OK":
        errors.append(f"grader status expected OK, got {payload.get('status')}")
    for required in ("grading_summary", "report_html"):
        path = Path(payload.get("artifacts", {}).get(required, ""))
        if not path.exists():
            errors.append(f"missing grader artifact: {required}")
    grading = load_json(session_dir / "eval-1" / "grading.json")
    if grading.get("summary", {}).get("authoritative_pass_rate") != 0.0:
        errors.append("deterministic failed grading should have authoritative_pass_rate=0.0")
    summary = load_json(session_dir / "grading-summary.json")
    if summary.get("status") != "generated_by_ci":
        errors.append("grading-summary.json status expected generated_by_ci")
    report = (session_dir / "report.html").read_text(encoding="utf-8")
    if "SkillSentry CI Report" not in report or "Execution Diagnostics" not in report:
        errors.append("report.html missing expected grader-report markers")
    session = sentry_state.load_session(session_dir)
    if session.get("grader_report", {}).get("status") != "completed":
        errors.append("session.grader_report.status expected completed")


def verify_missing_evals(root: Path, errors: list[str]) -> None:
    session_dir = root / "missing-session"
    session_dir.mkdir()
    sentry_state.save_session(session_dir, {"skill": "missing", "mode": "smoke"})
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "sentry_grader.py"),
            "--evals",
            str(root / "missing-evals.json"),
            "--session-dir",
            str(session_dir),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 1:
        errors.append(f"missing evals expected exit 1, got {completed.returncode}")
    payload = json.loads(completed.stdout)
    if payload.get("status") != "ERROR":
        errors.append("missing evals expected ERROR payload")
    session = sentry_state.load_session(session_dir)
    if session.get("grader_report", {}).get("status") != "failed":
        errors.append("missing evals should update session.grader_report.status=failed")


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-grader-") as tmp:
        root = Path(tmp)
        verify_success_path(root, errors)
        verify_missing_evals(root, errors)
    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_grader.py wrapper")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry grader: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
