#!/usr/bin/env python3
"""Lightweight planning helpers for sentry_run profiles."""

from __future__ import annotations

from sentry_pipeline import plan as pipeline_plan


PROFILE_STEPS: dict[str, list[dict]] = {
    "preflight": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
    ],
    "lint": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
        {"step": "session", "tool": "sentry-state", "step_type": "deterministic"},
        {"step": "prepare_cases", "tool": "sentry-case-lint", "step_type": "deterministic"},
    ],
    "debug": [
        {"step": "gate", "tool": "sentry-gate", "step_type": "deterministic"},
        {"step": "diagnostics", "tool": "sentry-diagnostics", "step_type": "deterministic"},
        {"step": "report", "tool": "sentry-report", "step_type": "deterministic"},
    ],
    "local": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
        {"step": "session", "tool": "sentry-state", "step_type": "deterministic"},
        {"step": "prepare_cases", "tool": "sentry-case-lint", "step_type": "deterministic"},
        {"step": "executor-with", "tool": "sentry-executor", "step_type": "llm_required"},
        {"step": "grader-report", "tool": "sentry-grader", "step_type": "llm_required"},
        {"step": "diagnostics", "tool": "sentry-diagnostics", "step_type": "deterministic"},
    ],
}


def enrich_plan_step(step: dict) -> dict:
    item = dict(step)
    step_type = str(item.get("step_type") or "")
    requires_llm = step_type == "llm_required"
    requires_network = step_type == "sync"
    item["heavy"] = bool(requires_llm)
    item["requires_llm"] = requires_llm
    item["requires_network"] = requires_network
    return item


def summarize_plan_steps(steps: list[dict]) -> dict:
    heavy_steps = [item.get("step") for item in steps if item.get("heavy")]
    network_steps = [item.get("step") for item in steps if item.get("requires_network")]
    llm_steps = [item.get("step") for item in steps if item.get("requires_llm")]
    return {
        "heavy_steps": heavy_steps,
        "llm_steps": llm_steps,
        "network_steps": network_steps,
        "requires_llm": bool(llm_steps),
        "requires_network": bool(network_steps),
    }


def build_mode_plan(mode: str) -> dict:
    raw = pipeline_plan(mode)
    steps = [enrich_plan_step(item) for item in raw.get("steps", []) if isinstance(item, dict)]
    payload = {
        "kind": "pipeline",
        "mode": mode,
        "pipeline": raw.get("pipeline", []),
        "steps": steps,
    }
    payload.update(summarize_plan_steps(steps))
    return payload


def build_profile_plan(profile: str) -> dict:
    steps = [enrich_plan_step(item) for item in PROFILE_STEPS.get(profile, [])]
    payload = {
        "kind": "profile",
        "profile": profile,
        "pipeline": [item.get("step") for item in steps],
        "steps": steps,
    }
    payload.update(summarize_plan_steps(steps))
    return payload
