#!/usr/bin/env python3
"""Deterministic sentry-static entrypoint.

Combines static lint, trigger estimation, and a compact summary for one
SKILL.md. This is intentionally no-LLM/no-network by default so it can be
used as a stable compatibility entrypoint while deeper optimization remains
in higher-level tools.
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

from sentry_preflight import find_skill, parse_frontmatter
from sentry_case_lint import inspect_case_feasibility


TP_PROMPTS = [
    "请帮我处理这个文件导出问题",
    "我要提交一个报销申请，请确认流程是否正确",
    "帮我写一个创建工单的技能说明",
    "这个 Skill 应该在什么场景触发",
    "请根据需求生成一份可执行的操作步骤",
]
TN_PROMPTS = [
    "请解释什么是触发率评估",
    "顺手帮我总结一下这段话",
    "帮我看一下这个概念的定义",
]
BOUNDARY_PROMPTS = [
    "这个功能看起来像审批流程，但我只是想做说明",
    "这个请求涉及敏感资源，但不确定是否该触发",
]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def score_prompt(description: str, prompt: str, *, boundary: bool = False) -> tuple[float, str]:
    score = 0.5
    reasons: list[str] = []
    desc = description.lower()
    prompt_text = prompt.lower()

    if any(keyword in desc for keyword in ("触发", "处理", "生成", "创建", "提交", "审批", "报销", "工单", "导出", "说明", "验证")):
        score += 0.18
        reasons.append("description 包含明确业务动作")
    if any(keyword in prompt_text for keyword in ("触发", "报销", "创建", "导出", "审批", "工单")):
        score += 0.12
        reasons.append("prompt 命中典型业务场景")
    if any(keyword in prompt_text for keyword in ("解释", "定义", "概念")):
        score -= 0.20
        reasons.append("prompt 更像解释而非执行任务")
    if boundary:
        score -= 0.05
        reasons.append("边界样本保留不确定性")
    if "安全" in desc or "security" in desc:
        score += 0.05
        reasons.append("description 含安全边界")

    score = max(0.0, min(1.0, score))
    if score >= 0.7:
        verdict = "trigger"
    elif score <= 0.3:
        verdict = "no_trigger"
    else:
        verdict = "uncertain"
    return score, verdict, "; ".join(reasons) if reasons else "启发式语义匹配"


def build_trigger_eval(description: str) -> dict:
    prompts = []
    tp_hits = 0
    tn_hits = 0
    boundary_count = 0

    for prompt in TP_PROMPTS:
        score, verdict, reason = score_prompt(description, prompt)
        tp_hits += int(verdict == "trigger")
        prompts.append(
            {
                "type": "true_positive",
                "prompt": prompt,
                "prediction": verdict,
                "confidence": round(score, 2),
                "reasoning": reason,
            }
        )

    for prompt in TN_PROMPTS:
        score, verdict, reason = score_prompt(description, prompt)
        tn_hits += int(verdict == "no_trigger")
        prompts.append(
            {
                "type": "true_negative",
                "prompt": prompt,
                "prediction": verdict,
                "confidence": round(1 - score, 2),
                "reasoning": reason,
            }
        )

    for prompt in BOUNDARY_PROMPTS:
        score, verdict, reason = score_prompt(description, prompt, boundary=True)
        boundary_count += int(verdict == "uncertain")
        prompts.append(
            {
                "type": "boundary",
                "prompt": prompt,
                "prediction": verdict,
                "confidence": round(score if verdict != "uncertain" else 0.5, 2),
                "reasoning": reason,
            }
        )

    tp_rate = tp_hits / len(TP_PROMPTS)
    tn_rate = tn_hits / len(TN_PROMPTS)
    confidence = "low" if boundary_count >= 2 else ("medium" if boundary_count == 1 else "high")
    return {
        "version": 1,
        "summary": {
            "tp_rate": round(tp_rate, 4),
            "tn_rate": round(tn_rate, 4),
            "overall_confidence": confidence,
            "tp_hits": tp_hits,
            "tn_hits": tn_hits,
            "boundary_count": boundary_count,
        },
        "prompts": prompts,
    }


def build_summary(skill_name: str, lint_result: dict, trigger_eval: dict) -> dict:
    trigger_summary = trigger_eval["summary"]
    static_quality = "pass" if lint_result.get("warning_count", 0) == 0 else "needs_review"
    trigger_quality = "pass" if trigger_summary["tp_rate"] >= 0.8 and trigger_summary["tn_rate"] >= 0.8 else "needs_review"
    recommendation = "publish" if static_quality == "pass" and trigger_quality == "pass" and trigger_summary["overall_confidence"] != "low" else "conditional_pass"
    return {
        "status": "OK",
        "skill": skill_name,
        "lint": lint_result,
        "trigger_eval": trigger_eval,
        "summary": {
            "static_quality": static_quality,
            "trigger_quality": trigger_quality,
            "release_recommendation": recommendation,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic sentry-static")
    parser.add_argument("skill", help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--lint-only", action="store_true", help="Only run static lint and exit")
    parser.add_argument("--trigger-only", action="store_true", help="Only run trigger estimation and exit")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_path = find_skill(args.skill)
    if not skill_path:
        payload = {"status": "BLOCKED", "error": f"skill not found: {args.skill}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else payload["error"])
        return 2

    content = load_text(skill_path)
    frontmatter = parse_frontmatter(content)
    description = str(frontmatter.get("description") or "")
    skill_name = str(frontmatter.get("name") or skill_path.parent.name)

    lint_case = {
        "id": "skill-frontmatter",
        "name": skill_name,
        "description": description,
        "prompt": content,
    }
    if "安全" in description or "security" in description.lower():
        lint_case.update(
            {
                "security_family": "normal_request_disguise",
                "risk_level": "P1",
                "attack_surface": ["frontmatter"],
                "expected_guardrail": "describe the skill clearly",
                "gate_level": "warn",
            }
        )
    lint_warnings = inspect_case_feasibility([lint_case])
    lint_result = {
        "status": "WARN" if lint_warnings else "OK",
        "warning_count": len(lint_warnings),
        "warnings": lint_warnings,
    }
    trigger_eval = build_trigger_eval(description)
    summary = build_summary(skill_name, lint_result, trigger_eval)

    if args.lint_only:
        payload = {"status": "OK", "mode": "lint", "skill": skill_name, "lint": lint_result}
    elif args.trigger_only:
        payload = {"status": "OK", "mode": "trigger", "skill": skill_name, "trigger_eval": trigger_eval}
    else:
        payload = summary

    if args.output:
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if args.lint_only:
            print(f"sentry-static lint: {lint_result['status']} | warnings={lint_result['warning_count']}")
        elif args.trigger_only:
            s = trigger_eval["summary"]
            print(f"sentry-static trigger: TP={s['tp_rate']:.0%} TN={s['tn_rate']:.0%} confidence={s['overall_confidence']}")
        else:
            s = summary["summary"]
            print(f"sentry-static: {s['static_quality']} / {s['trigger_quality']} / {s['release_recommendation']}")
    if args.format != "json":
        print(f"[sentry-proof] skill=sentry-static steps={1 if args.lint_only or args.trigger_only else 2} ts=static")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
