#!/usr/bin/env python3
"""Verify workflow actions use the Node 24 compatible major versions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIRS = [
    ROOT / ".github" / "workflows",
    ROOT / "references" / "workflows",
]
REQUIRED_MAJOR = {
    "actions/checkout": "v6",
    "actions/setup-python": "v6",
}


def workflow_files() -> list[Path]:
    paths: list[Path] = []
    for directory in WORKFLOW_DIRS:
        if not directory.exists():
            continue
        paths.extend(sorted(directory.glob("*.yml")))
        paths.extend(sorted(directory.glob("*.yaml")))
    return paths


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    files = workflow_files()
    if not files:
        return False, ["no workflow files found"]

    pattern = re.compile(r"uses:\s*['\"]?(actions/(?:checkout|setup-python))@([^'\"\s]+)")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for action, version in pattern.findall(text):
            expected = REQUIRED_MAJOR[action]
            if version != expected:
                errors.append(f"{path.relative_to(ROOT)} uses {action}@{version}; expected {action}@{expected}")

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify GitHub workflow action versions")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"workflow action versions: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
