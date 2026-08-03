#!/usr/bin/env python3
"""Trigger-rate evaluator with deterministic fallback.

When `--precise` is requested and a Claude CLI is available, this script can
run prompt probes against the local CLI. Otherwise it emits an explicit
skipped_precise result plus the deterministic estimate from sentry_static.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_static


def run_precise_prompt(prompt: str, timeout: int) -> dict:
    claude = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude:
        return {"status": "skipped_no_claude_cli", "prompt": prompt}
    try:
        completed = subprocess.run(
            [claude, "--output-format", "text", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        return {"status": "error", "prompt": prompt, "error": str(exc)}
    return {
        "status": "OK" if completed.returncode == 0 else "error",
        "prompt": prompt,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout.strip()[-500:],
        "stderr_tail": completed.stderr.strip()[-500:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry trigger-rate evaluator")
    parser.add_argument("skill", help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--precise", action="store_true", help="Try real Claude CLI probes")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_path = sentry_static.find_skill(args.skill)
    if not skill_path:
        payload = {"status": "BLOCKED", "error": f"skill not found: {args.skill}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else payload["error"])
        return 2

    content = skill_path.read_text(encoding="utf-8")
    frontmatter = sentry_static.parse_frontmatter(content)
    description = str(frontmatter.get("description") or "")
    estimate = sentry_static.build_trigger_eval(description)
    payload = {
        "status": "OK",
        "skill": str(frontmatter.get("name") or skill_path.parent.name),
        "mode": "precise" if args.precise else "estimate",
        "estimate": estimate,
        "precise": None,
    }
    if args.precise:
        probes = [run_precise_prompt(prompt, args.timeout) for prompt in sentry_static.TP_PROMPTS + sentry_static.TN_PROMPTS]
        payload["precise"] = {
            "available": any(item.get("status") == "OK" for item in probes),
            "probes": probes,
            "status": "OK" if any(item.get("status") == "OK" for item in probes) else "skipped",
        }
    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = estimate["summary"]
        print(f"trigger eval: TP={summary['tp_rate']:.0%} TN={summary['tn_rate']:.0%} confidence={summary['overall_confidence']}")
        if args.precise and payload["precise"]:
            print(f"precise: {payload['precise']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
