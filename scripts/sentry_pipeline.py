#!/usr/bin/env python3
"""SkillSentry shared pipeline contract.

This module is the single source of truth for current SkillSentry pipeline
steps. Interactive runs, CI, state management, and validators should import
this file instead of copying pipeline arrays into their own code.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


PIPELINES: dict[str, list[str]] = {
    "smoke": ["cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
    "quick": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
    "regression": ["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"],
    "standard": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"],
    "full": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"],
}


@dataclass(frozen=True)
class StepDefinition:
    step: str
    step_type: str
    tool: str
    can_skip: bool
    skip_policy: str
    required_artifacts: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["required_artifacts"] = list(self.required_artifacts)
        return data


STEP_DEFINITIONS: dict[str, StepDefinition] = {
    "static": StepDefinition(
        step="static",
        step_type="llm_required",
        tool="sentry-static",
        can_skip=False,
        skip_policy="Static checks are required for quick/standard/full modes.",
        required_artifacts=("session.json:lint", "trigger_eval.json"),
    ),
    "cases": StepDefinition(
        step="cases",
        step_type="llm_required",
        tool="sentry-cases",
        can_skip=False,
        skip_policy="Cases may be cache-reused, but evals.json must exist.",
        required_artifacts=("evals.json",),
    ),
    "sync-pull": StepDefinition(
        step="sync-pull",
        step_type="sync",
        tool="sentry-sync",
        can_skip=True,
        skip_policy="No Feishu config -> record skipped_no_config, do not silently omit the step.",
        required_artifacts=("session.json:sync.pull",),
    ),
    "sync-push-cases": StepDefinition(
        step="sync-push-cases",
        step_type="sync",
        tool="sentry-sync",
        can_skip=True,
        skip_policy="No Feishu config -> record skipped_no_config, do not silently omit the step.",
        required_artifacts=("session.json:sync.push_cases",),
    ),
    "executor-with": StepDefinition(
        step="executor-with",
        step_type="llm_required",
        tool="sentry-executor",
        can_skip=False,
        skip_policy="with_skill execution is required unless the whole run is blocked.",
        required_artifacts=("eval-*/with_skill/outputs/response.md", "eval-*/with_skill/outputs/transcript.md"),
    ),
    "executor-without": StepDefinition(
        step="executor-without",
        step_type="llm_required",
        tool="sentry-executor",
        can_skip=True,
        skip_policy="If baseline is not comparable, mark individual evals skipped/partial instead of skipping the whole mode.",
        required_artifacts=("eval-*/without_skill/outputs/response.md", "eval-*/without_skill/outputs/transcript.md"),
    ),
    "comparator": StepDefinition(
        step="comparator",
        step_type="llm_required",
        tool="sentry-comparator",
        can_skip=True,
        skip_policy="If without_skill is partial/unavailable, record comparator partial/N/A with reasons.",
        required_artifacts=("comparator-results.json",),
    ),
    "analyzer": StepDefinition(
        step="analyzer",
        step_type="llm_required",
        tool="sentry-analyzer",
        can_skip=True,
        skip_policy="Full mode only; may be skipped when comparator is N/A.",
        required_artifacts=("analyzer-recommendations.json",),
    ),
    "grader-report": StepDefinition(
        step="grader-report",
        step_type="llm_required",
        tool="sentry-grader",
        can_skip=False,
        skip_policy="Main report step; must emit grading artifacts and report.html.",
        required_artifacts=("eval-*/grading.json", "grading-summary.json", "report.html"),
    ),
    "sync-push-results": StepDefinition(
        step="sync-push-results",
        step_type="sync",
        tool="sentry-sync",
        can_skip=True,
        skip_policy="No Feishu config -> record skipped_no_config, do not silently omit the step.",
        required_artifacts=("session.json:sync.push_results",),
    ),
    "gate": StepDefinition(
        step="gate",
        step_type="deterministic",
        tool="sentry-gate",
        can_skip=False,
        skip_policy="Gate is required for standard/full release decisions.",
        required_artifacts=("gate-result.json", "session.json:verdict"),
    ),
    "publish": StepDefinition(
        step="publish",
        step_type="publish",
        tool="sentry-report",
        can_skip=False,
        skip_policy="Publish must at least emit final user-facing decision or blocked status.",
        required_artifacts=("report.html", "session.json:verdict"),
    ),
}


def pipeline_for_mode(mode: str) -> list[str]:
    if mode not in PIPELINES:
        raise KeyError(f"unknown mode: {mode}")
    return list(PIPELINES[mode])


def step_definition(step: str) -> StepDefinition:
    if step not in STEP_DEFINITIONS:
        raise KeyError(f"unknown step: {step}")
    return STEP_DEFINITIONS[step]


def next_step(pipeline: list[str], last_step: str | None) -> str | None:
    if not pipeline:
        return None
    if last_step in pipeline:
        idx = pipeline.index(last_step)
        return pipeline[idx + 1] if idx + 1 < len(pipeline) else None
    return pipeline[0]


def plan(mode: str) -> dict:
    steps = pipeline_for_mode(mode)
    return {
        "mode": mode,
        "pipeline": steps,
        "steps": [step_definition(step).to_dict() for step in steps],
    }


def describe_next(mode: str, last_step: str | None) -> dict:
    steps = pipeline_for_mode(mode)
    step = next_step(steps, last_step)
    return {
        "mode": mode,
        "pipeline": steps,
        "last_step": last_step,
        "next_step": step,
        "definition": step_definition(step).to_dict() if step else None,
    }


def load_session(path: str | Path) -> dict:
    session_path = Path(path)
    if session_path.is_dir():
        session_path = session_path / "session.json"
    return json.loads(session_path.read_text(encoding="utf-8"))


def pipelines_from_contract(path: str | Path) -> dict[str, list[str]]:
    contract_path = Path(path)
    text = contract_path.read_text(encoding="utf-8")
    match = re.search(r"合法 pipeline:\s*```json\s*(.*?)```", text, re.DOTALL)
    if not match:
        raise ValueError(f"could not find legal pipeline JSON block in {contract_path}")
    data = json.loads(match.group(1))
    if not isinstance(data, dict):
        raise ValueError("contract pipeline block must be a JSON object")
    return {str(key): list(value) for key, value in data.items()}


def check_contract(path: str | Path) -> dict:
    expected = pipelines_from_contract(path)
    mismatches = []
    for mode in sorted(set(expected) | set(PIPELINES)):
        if expected.get(mode) != PIPELINES.get(mode):
            mismatches.append({
                "mode": mode,
                "contract": expected.get(mode),
                "core": PIPELINES.get(mode),
            })
    return {
        "status": "OK" if not mismatches else "ERROR",
        "contract": str(path),
        "mismatches": mismatches,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry shared pipeline contract")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="Print all pipelines")
    list_cmd.add_argument("--format", choices=["json", "text"], default="json")

    plan_cmd = sub.add_parser("plan", help="Print a mode pipeline with step definitions")
    plan_cmd.add_argument("--mode", required=True, choices=sorted(PIPELINES))
    plan_cmd.add_argument("--format", choices=["json", "text"], default="json")

    next_cmd = sub.add_parser("next", help="Print next step for a mode or session")
    next_cmd.add_argument("--mode", choices=sorted(PIPELINES))
    next_cmd.add_argument("--last-step", default=None)
    next_cmd.add_argument("--session-dir", default=None)
    next_cmd.add_argument("--format", choices=["json", "text"], default="json")

    describe_cmd = sub.add_parser("describe", help="Print one step definition")
    describe_cmd.add_argument("step", choices=sorted(STEP_DEFINITIONS))
    describe_cmd.add_argument("--format", choices=["json", "text"], default="json")

    check_cmd = sub.add_parser("check-contract", help="Compare core pipelines with current-contract.md")
    default_contract = Path(__file__).resolve().parent.parent / "references" / "current-contract.md"
    check_cmd.add_argument("--contract", default=str(default_contract))
    check_cmd.add_argument("--format", choices=["json", "text"], default="json")

    return parser.parse_args()


def emit(payload: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if "steps" in payload:
        print(f"mode: {payload['mode']}")
        print("pipeline: " + " -> ".join(payload["pipeline"]))
        for item in payload["steps"]:
            print(f"- {item['step']}: {item['step_type']} via {item['tool']}")
        return

    if "definition" in payload:
        print(f"mode: {payload['mode']}")
        print(f"last_step: {payload.get('last_step')}")
        print(f"next_step: {payload.get('next_step')}")
        if payload.get("definition"):
            print(f"tool: {payload['definition']['tool']}")
        return

    for key, value in payload.items():
        print(f"{key}: {value}")


def main() -> int:
    args = parse_args()
    if args.command == "list":
        payload = {"pipelines": PIPELINES}
        emit(payload, args.format)
    elif args.command == "plan":
        emit(plan(args.mode), args.format)
    elif args.command == "next":
        if args.session_dir:
            session = load_session(args.session_dir)
            mode = session.get("mode")
            last = session.get("last_step")
        else:
            mode = args.mode
            last = args.last_step
        if not mode:
            print("ERROR: --mode or --session-dir is required", file=sys.stderr)
            return 2
        emit(describe_next(mode, last), args.format)
    elif args.command == "describe":
        payload = step_definition(args.step).to_dict()
        emit(payload, args.format)
    elif args.command == "check-contract":
        payload = check_contract(args.contract)
        emit(payload, args.format)
        return 0 if payload["status"] == "OK" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
