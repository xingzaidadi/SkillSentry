#!/usr/bin/env python3
"""Deterministic description optimization helper.

Creates a 60/40-style split over heuristic trigger prompts and suggests a
revised description. It is intentionally conservative and offline-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_static


def split_prompts(items: list[str]) -> tuple[list[str], list[str]]:
    split_index = max(1, round(len(items) * 0.6))
    return items[:split_index], items[split_index:]


def optimize_description(description: str, train_prompts: list[str], test_prompts: list[str]) -> dict:
    train_scores = []
    test_scores = []
    for prompt in train_prompts:
        score, verdict, reason = sentry_static.score_prompt(description, prompt)
        train_scores.append({"prompt": prompt, "score": score, "verdict": verdict, "reason": reason})
    for prompt in test_prompts:
        score, verdict, reason = sentry_static.score_prompt(description, prompt)
        test_scores.append({"prompt": prompt, "score": score, "verdict": verdict, "reason": reason})

    train_tp = sum(1 for item in train_scores if item["verdict"] == "trigger")
    test_tp = sum(1 for item in test_scores if item["verdict"] == "trigger")
    suggestion = description.strip()
    if "触发" not in suggestion:
        suggestion = suggestion + "。请明确说明何时触发、何时不触发、典型使用场景和边界条件。"
    if "不触发" not in suggestion and "不应触发" not in suggestion:
        suggestion = suggestion + " 同时明确不应触发的反例。"
    return {
        "split": {"train": train_prompts, "test": test_prompts, "train_ratio": 0.6, "test_ratio": 0.4},
        "train": {"trigger_hits": train_tp, "total": len(train_prompts), "items": train_scores},
        "test": {"trigger_hits": test_tp, "total": len(test_prompts), "items": test_scores},
        "suggested_description": suggestion,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic description optimization helper")
    parser.add_argument("skill", help="Skill name, directory, or SKILL.md path")
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
    train_prompts, test_prompts = split_prompts(sentry_static.TP_PROMPTS + sentry_static.TN_PROMPTS + sentry_static.BOUNDARY_PROMPTS)
    payload = {
        "status": "OK",
        "skill": str(frontmatter.get("name") or skill_path.parent.name),
        "mode": "description-optimize",
        "result": optimize_description(description, train_prompts, test_prompts),
    }

    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        train = payload["result"]["train"]
        test = payload["result"]["test"]
        print(
            f"description optimize: train={train['trigger_hits']}/{train['total']} "
            f"test={test['trigger_hits']}/{test['total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
