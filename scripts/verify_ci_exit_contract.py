#!/usr/bin/env python3
"""Verify sentry_ci exit-code and GitHub output contracts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sentry_ci


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


EXPECTED = {
    "PASS": ("pass", 0),
    "CONDITIONAL PASS": ("conditional", 1),
    "FAIL": ("fail", 1),
    "ERROR": ("error", 2),
}


def parse_github_output(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def make_results(verdict: str) -> dict:
    rate = 1.0 if verdict == "PASS" else (0.75 if verdict != "ERROR" else None)
    summary = {
        "authoritative_pass_rate": rate,
        "grade": "S" if verdict == "PASS" else ("C" if verdict == "CONDITIONAL PASS" else "D"),
    }
    if verdict == "ERROR":
        summary = {}
    return {
        "verdict": verdict,
        "reasons": [f"fixture {verdict}"],
        "summary": summary,
        "diagnostics": {
            "categories": ["quality_failure"] if verdict == "FAIL" else ([] if verdict == "PASS" else ["fixture"]),
            "notes": ["fixture"],
        },
    }


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-exit-contract-") as tmp:
        root = Path(tmp)
        old_github_output = os.environ.get("GITHUB_OUTPUT")
        try:
            for verdict, (expected_status, expected_code) in EXPECTED.items():
                actual_status = sentry_ci.release_status_for_verdict(verdict)
                actual_code = sentry_ci.exit_code_for_verdict(verdict)
                if actual_status != expected_status:
                    errors.append(f"{verdict}: expected status {expected_status}, got {actual_status}")
                if actual_code != expected_code:
                    errors.append(f"{verdict}: expected exit code {expected_code}, got {actual_code}")

                output_dir = root / verdict.lower().replace(" ", "-")
                github_output = output_dir / "github-output.txt"
                output_dir.mkdir(parents=True, exist_ok=True)
                os.environ["GITHUB_OUTPUT"] = str(github_output)
                args = SimpleNamespace(
                    skill="exit-contract-fixture",
                    mode="smoke",
                    threshold=0.8,
                    github_output=True,
                )
                sentry_ci.write_ci_output(output_dir, make_results(verdict), args)

                payload = json.loads((output_dir / "eval_result.json").read_text(encoding="utf-8"))
                if payload.get("status") != expected_status:
                    errors.append(f"{verdict}: eval_result.status expected {expected_status}, got {payload.get('status')}")
                if payload.get("exit_code") != expected_code:
                    errors.append(f"{verdict}: eval_result.exit_code expected {expected_code}, got {payload.get('exit_code')}")
                if not payload.get("artifacts", {}).get("output_report_html"):
                    errors.append(f"{verdict}: eval_result missing output_report_html")

                outputs = parse_github_output(github_output)
                expected_outputs = {
                    "verdict": verdict,
                    "status": expected_status,
                    "release_status": expected_status,
                    "exit_code": str(expected_code),
                    "report_html": str(output_dir / "report.html"),
                }
                for key, expected in expected_outputs.items():
                    if outputs.get(key) != expected:
                        errors.append(f"{verdict}: GITHUB_OUTPUT {key} expected {expected!r}, got {outputs.get(key)!r}")
                for key in ("diagnostic_categories", "authoritative_pass_rate", "grade"):
                    if key not in outputs:
                        errors.append(f"{verdict}: GITHUB_OUTPUT missing {key}")
        finally:
            if old_github_output is None:
                os.environ.pop("GITHUB_OUTPUT", None)
            else:
                os.environ["GITHUB_OUTPUT"] = old_github_output

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_ci exit and GitHub output contracts")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ci exit contract: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
