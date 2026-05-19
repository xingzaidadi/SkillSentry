#!/usr/bin/env python3
"""Run SkillSentry deterministic self-checks as one command."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


CORE_CHECKS: list[list[str]] = [
    ["sentry_contract_lint.py", "--strict", "--format", "json"],
    ["verify_sentry_executor.py", "--format", "json"],
    ["verify_sentry_grader.py", "--format", "json"],
    ["verify_sentry_run.py", "--format", "json"],
    ["verify_local_dogfood.py", "--format", "json"],
    ["verify_sentry_report.py", "--format", "json"],
    ["verify_sentry_timing.py", "--format", "json"],
    ["verify_ci_diagnostics.py", "--format", "json"],
    ["verify_ci_exit_contract.py", "--format", "json"],
    ["verify_ci_checks_integration.py", "--format", "json"],
    ["verify_dashboard.py", "--format", "json"],
]

FULL_ONLY_CHECKS: list[list[str]] = [
    ["verify_ci_preflight.py", "--format", "json"],
    ["verify_ci_feasibility.py", "--format", "json"],
    ["verify_ci_failure_report.py", "--format", "json"],
    ["verify_ci_modes.py", "--format", "json"],
]


def run_check(args: list[str]) -> dict:
    started = time.time()
    cmd = [sys.executable, str(SCRIPT_DIR / args[0]), *args[1:]]
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration_ms = round((time.time() - started) * 1000, 1)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None
    return {
        "name": args[0],
        "command": " ".join(cmd),
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "duration_ms": duration_ms,
        "stdout_json": parsed,
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-2000:] if stderr else "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic SkillSentry self-checks")
    parser.add_argument("--full", action="store_true", help="Also run wider CI/pipeline fixture checks")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing check")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = CORE_CHECKS + (FULL_ONLY_CHECKS if args.full else [])
    results: list[dict] = []
    for check in checks:
        result = run_check(check)
        results.append(result)
        if args.format == "text":
            print(f"{result['status']} {result['name']} ({result['duration_ms']} ms)")
            if result["status"] != "PASS":
                if result.get("stdout_tail"):
                    print(result["stdout_tail"])
                if result.get("stderr_tail"):
                    print(result["stderr_tail"], file=sys.stderr)
        if args.fail_fast and result["status"] != "PASS":
            break

    failures = [item for item in results if item["status"] != "PASS"]
    payload = {
        "status": "PASS" if not failures else "FAIL",
        "mode": "full" if args.full else "core",
        "total": len(results),
        "failed": len(failures),
        "results": results,
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif failures:
        print(f"deterministic checks: FAIL ({len(failures)}/{len(results)} failed)")
    else:
        print(f"deterministic checks: PASS ({len(results)} checks)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
