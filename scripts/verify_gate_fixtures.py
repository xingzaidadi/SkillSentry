#!/usr/bin/env python3
"""Replay deterministic gate against historical fixture expectations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sentry_gate import build_gate, compare_expected


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "gate"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_gate historical fixtures")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURE_DIR), help="Fixture directory")
    parser.add_argument("--tolerance", type=float, default=0.0001)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def verify_fixture(path: Path, tolerance: float) -> dict:
    expected = json.loads(path.read_text(encoding="utf-8"))
    session_dir = ROOT / expected["session_dir"]
    if not session_dir.exists():
        return {
            "fixture": str(path),
            "session_dir": str(session_dir),
            "status": "FAIL",
            "errors": [f"session_dir not found: {session_dir}"],
        }

    result = build_gate(session_dir)
    ok, errors = compare_expected(result, path, tolerance)
    return {
        "fixture": str(path.relative_to(ROOT)),
        "session_dir": expected["session_dir"],
        "status": "PASS" if ok else "FAIL",
        "errors": errors,
        "actual": {
            "verdict": result.get("verdict"),
            "grade": result.get("grade"),
            "authoritative_pass_rate": result.get("authoritative_pass_rate"),
            "exact_pass_rate": result.get("exact_pass_rate"),
            "overall_pass_rate": result.get("overall_pass_rate"),
            "delta.status": (result.get("delta") or {}).get("status"),
        },
    }


def main() -> int:
    args = parse_args()
    fixture_dir = Path(args.fixtures).expanduser()
    if not fixture_dir.is_absolute():
        fixture_dir = ROOT / fixture_dir

    fixtures = sorted(fixture_dir.glob("*.expected.json"))
    if not fixtures:
        print(f"No gate fixtures found: {fixture_dir}", file=sys.stderr)
        return 2

    results = [verify_fixture(path, args.tolerance) for path in fixtures]
    failures = [item for item in results if item["status"] != "PASS"]

    if args.format == "json":
        print(json.dumps({"status": "PASS" if not failures else "FAIL", "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"gate fixtures: {len(results)} checked, {len(failures)} failed")
        for item in results:
            print(f"{item['status']} {item['session_dir']}")
            for error in item["errors"]:
                print(f"  {error}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
