#!/usr/bin/env python3
"""Deterministic evals.json feasibility lint.

This is a light tool: no LLM calls, no network calls. It checks whether cases
reference local resources that are unavailable in the current environment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_state


WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[^\s，。；,;`\"']+")
LINT_VERSION = 1


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_cases(payload) -> list:
    """Accept legacy list payloads and common wrapped eval/case shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("evals", "cases", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def inspect_case_feasibility(cases) -> list[dict]:
    """Return deterministic warnings for cases that cannot run as-is."""
    warnings: list[dict] = []

    for case in extract_cases(cases):
        if not isinstance(case, dict):
            continue
        case_id = case.get("id") or case.get("case_id") or "unknown"
        prompt = case.get("prompt", "") or ""
        if not isinstance(prompt, str):
            continue
        for raw_path in WINDOWS_PATH_PATTERN.findall(prompt):
            normalized = raw_path.rstrip(".,;，。；)")
            if not Path(normalized).exists():
                warnings.append({
                    "case_id": case_id,
                    "type": "missing_local_path",
                    "path": normalized,
                    "message": "Generated case references a local path that does not exist in this environment.",
                })
    return warnings


def lint_cases_file(cases_file: Path) -> dict:
    payload = load_json(cases_file)
    cases = extract_cases(payload)
    warnings = inspect_case_feasibility(payload)
    return {
        "status": "WARN" if warnings else "OK",
        "step": "case-lint",
        "version": LINT_VERSION,
        "cases_file": str(cases_file),
        "total": len(cases),
        "warnings": warnings,
        "warning_count": len(warnings),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def record_case_feasibility(session_dir: Path, cases) -> list[dict]:
    """Write feasibility warnings into session.json and return them."""
    warnings = inspect_case_feasibility(cases)
    session = sentry_state.load_session(session_dir)
    session["case_warnings"] = warnings
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    sentry_state.save_session(session_dir, session)
    return warnings


def record_case_lint_result(session_dir: Path, result: dict) -> None:
    session = sentry_state.load_session(session_dir)
    session["case_warnings"] = result.get("warnings", [])
    session["case_lint"] = {
        "status": result.get("status"),
        "version": result.get("version", LINT_VERSION),
        "total": result.get("total", 0),
        "warning_count": result.get("warning_count", 0),
        "cases_file": result.get("cases_file"),
        "checked_at": result.get("checked_at"),
    }
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    sentry_state.save_session(session_dir, session)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint evals.json feasibility without running executor/grader")
    parser.add_argument("--cases", required=True, help="Path to evals.json/cases.cache.json")
    parser.add_argument("--session-dir", help="Optional session directory to update with case_warnings")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = lint_cases_file(Path(args.cases))
    if args.session_dir:
        record_case_lint_result(Path(args.session_dir), result)
    if args.output:
        save_json(Path(args.output), result)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"case lint: {result['status']} | warnings: {result['warning_count']} | total: {result['total']}")
        for warning in result["warnings"]:
            print(f"- {warning['case_id']}: {warning['type']} {warning.get('path', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
