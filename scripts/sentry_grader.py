#!/usr/bin/env python3
"""Stable SkillSentry grader wrapper.

This wrapper keeps ci_grader.py as the grading implementation and adds the
CI/session/report contract around grader-report.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_report
import sentry_state
from ci_grader import grade_all_evals
from sentry_gate import build_gate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_grading_summary(session_dir: Path, gate: dict) -> Path:
    summary_payload = {
        "status": "generated_by_ci",
        "note": "CI compatibility summary. Per-eval grading.json files remain the source for deterministic gate counts.",
        "authoritative_pass_rate": gate.get("authoritative_pass_rate"),
        "grade": gate.get("grade"),
        "verdict": gate.get("verdict"),
        "sources": gate.get("sources", []),
    }
    summary_file = session_dir / "grading-summary.json"
    save_json(summary_file, summary_payload)
    return summary_file


def update_session_for_grader(session_dir: Path, payload: dict) -> None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    session = sentry_state.load_session(session_dir)
    session["grader_report"] = {
        "status": "completed" if payload.get("status") == "OK" else "failed",
        "grading_summary": payload.get("artifacts", {}).get("grading_summary"),
        "report_html": payload.get("artifacts", {}).get("report_html"),
        "updated_at": payload.get("updated_at"),
    }
    session["updated_at"] = utc_now()
    sentry_state.save_session(session_dir, session)


def execute_grader_report(
    *,
    evals_file: Path,
    session_dir: Path,
    model: str,
    verbose: bool = False,
    update_session: bool = True,
    write_report: bool = True,
) -> dict:
    """Run grader-report and return a stable JSON payload."""
    if not evals_file.exists():
        payload = {
            "status": "ERROR",
            "step": "grader-report",
            "error": f"evals file not found: {evals_file}",
            "artifacts": {},
            "updated_at": utc_now(),
        }
        if update_session:
            update_session_for_grader(session_dir, payload)
        return payload

    success = grade_all_evals(
        evals_file=evals_file,
        session_dir=session_dir,
        model=model,
        verbose=verbose,
    )
    artifacts: dict[str, str] = {}
    gate: dict = {}
    if success:
        gate = build_gate(session_dir)
        summary_file = write_grading_summary(session_dir, gate)
        artifacts["grading_summary"] = str(summary_file)
        if write_report:
            report = sentry_report.write_session_report(
                session_dir,
                gate,
                title="SkillSentry CI Report",
                generated_by="sentry_grader.py",
                footer="Full interactive reports are produced by sentry-grader.",
            )
            artifacts["report_html"] = str(report)

    payload = {
        "status": "OK" if success else "ERROR",
        "step": "grader-report",
        "model": model,
        "artifacts": artifacts,
        "gate": gate,
        "updated_at": utc_now(),
    }
    if update_session:
        update_session_for_grader(session_dir, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SkillSentry grader-report against existing executor outputs")
    parser.add_argument("--evals", required=True, help="evals.json path")
    parser.add_argument("--session-dir", required=True, help="Session directory")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--no-session-update", action="store_true", help="Do not update session.json")
    parser.add_argument("--no-report", action="store_true", help="Do not write report.html")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = execute_grader_report(
        evals_file=Path(args.evals),
        session_dir=Path(args.session_dir),
        model=args.model,
        verbose=args.verbose,
        update_session=not args.no_session_update,
        write_report=not args.no_report,
    )
    if args.output:
        save_json(Path(args.output), payload)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        gate = payload.get("gate", {})
        print(
            "sentry grader: "
            f"{payload['status']} | verdict: {gate.get('verdict', 'N/A')} | grade: {gate.get('grade', 'N/A')}"
        )
        if payload.get("error"):
            print(f"- {payload['error']}")
    return 0 if payload["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
