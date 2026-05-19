#!/usr/bin/env python3
"""Verify the deterministic self-test GitHub Actions workflow template stays lightweight."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "references" / "workflows" / "skillsentry-self-test.yml"
EVAL_WORKFLOW = ROOT / ".github" / "workflows" / "skill-eval.yml"


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not WORKFLOW.exists():
        return False, [f"self-test workflow template missing: {WORKFLOW.relative_to(ROOT)}"]

    text = WORKFLOW.read_text(encoding="utf-8")
    required = [
        "name: SkillSentry Self-Test",
        "workflow_dispatch:",
        "scripts/**",
        "references/**",
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "python-version: '3.11'",
        "github.event.inputs.full",
        "python scripts/verify_deterministic.py --format json",
        "python scripts/verify_deterministic.py --full --format json",
    ]
    for marker in required:
        if marker not in text:
            errors.append(f"self-test workflow missing {marker!r}")

    forbidden = [
        "--real",
        "ANTHROPIC_API_KEY",
        "claude --version",
        "npm install -g @anthropic-ai/claude-code",
        "scripts/sentry_ci.py",
    ]
    for marker in forbidden:
        if marker in text:
            errors.append(f"self-test workflow template should not contain {marker!r}")

    if EVAL_WORKFLOW.exists():
        eval_text = EVAL_WORKFLOW.read_text(encoding="utf-8")
        if "verify_deterministic.py" in eval_text:
            errors.append("skill-eval workflow should not run SkillSentry self-tests")

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify SkillSentry self-test workflow template")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"self-test workflow: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
