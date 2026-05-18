#!/usr/bin/env python3
"""Analyze SkillSentry timing artifacts.

This is a light tool: no LLM calls, no network calls. It reads existing
eval_result.json or session artifacts and summarizes slow CI steps/phases.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def timing_from_eval_result(path: Path) -> tuple[dict, dict]:
    payload = load_json(path)
    return _as_dict(payload.get("timings")), {
        "source": str(path),
        "kind": "eval_result",
        "verdict": payload.get("verdict"),
        "status": payload.get("status"),
    }


def timing_from_session(path: Path) -> tuple[dict, dict]:
    session_file = path / "session.json" if path.is_dir() else path
    session = load_json(session_file)
    timing = _as_dict(session.get("ci_timing"))
    steps = _as_list(session.get("ci_step_timings"))
    phases = _as_list(session.get("ci_phase_timings"))
    return {
        "total_ms": timing.get("total_ms"),
        "steps": steps,
        "phases": phases,
        "failed_steps": timing.get("failed_steps", []),
    }, {
        "source": str(session_file),
        "kind": "session",
        "skill": session.get("skill"),
        "mode": session.get("mode"),
        "last_step": session.get("last_step"),
    }


def load_timing(path: Path) -> tuple[dict, dict]:
    if path.is_dir() or path.name == "session.json":
        return timing_from_session(path)
    payload = load_json(path)
    if "timings" in payload:
        return _as_dict(payload.get("timings")), {
            "source": str(path),
            "kind": "eval_result",
            "verdict": payload.get("verdict"),
            "status": payload.get("status"),
        }
    if "ci_step_timings" in payload or "ci_timing" in payload:
        return timing_from_session(path)
    raise ValueError(f"unsupported timing input: {path}")


def sorted_items(items: list, name_key: str) -> list[dict]:
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(dict(item))
    return sorted(normalized, key=lambda item: _number(item.get("duration_ms")), reverse=True)


def recommendation(step: dict) -> str:
    name = str(step.get("step") or step.get("phase") or "")
    duration = _number(step.get("duration_ms"))
    if not name:
        return "No timing data available."
    if name == "executor-with" or name == "executor-without":
        return "Executor dominates; reduce eval count, reuse local profile artifacts, or inspect per-eval runner time before adding cache."
    if name == "grader-report":
        return "Grader dominates; inspect assertion count and LLM fallback/API latency before changing scoring."
    if name == "cases":
        return "Cases dominate; prefer cached cases or lint/preflight profiles when case design is not being tested."
    if name.startswith("sync-"):
        return "Sync dominates; check Feishu/network configuration and keep skipped_no_config explicit when offline."
    if name == "publish":
        return "Publish dominates; use no-network report regeneration for local inspection when external publishing is not needed."
    if duration < 100:
        return "No single expensive step was observed in this deterministic sample."
    return "Investigate this stage before adding skip or cache behavior."


def analyze(path: Path, top: int = 5) -> dict:
    timings, meta = load_timing(path)
    steps = sorted_items(_as_list(timings.get("steps")), "step")
    phases = sorted_items(_as_list(timings.get("phases")), "phase")
    slowest = steps[0] if steps else (phases[0] if phases else {})
    return {
        "status": "OK",
        "source": meta,
        "total_ms": timings.get("total_ms"),
        "top_steps": steps[:top],
        "top_phases": phases[:top],
        "failed_steps": timings.get("failed_steps", []),
        "recommendation": recommendation(slowest),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze SkillSentry timing artifacts")
    parser.add_argument("--input", required=True, help="Path to eval_result.json, session.json, or session directory")
    parser.add_argument("--top", type=int, default=5, help="Number of slow steps/phases to show")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = analyze(Path(args.input), top=args.top)
    except Exception as exc:
        payload = {"status": "ERROR", "error": str(exc), "source": str(args.input)}
        if args.format == "json":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"sentry timing: ERROR\n- {payload['error']}")
        return 2

    if args.output:
        save_json(Path(args.output), payload)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry timing: {payload['status']} | total: {payload.get('total_ms', 'N/A')}ms")
        print(f"source: {payload['source'].get('source')}")
        print("top steps:")
        for item in payload["top_steps"]:
            print(f"- {item.get('step')}: {item.get('duration_ms')}ms ({item.get('status', 'N/A')})")
        print("top phases:")
        for item in payload["top_phases"]:
            print(f"- {item.get('phase')}: {item.get('duration_ms')}ms ({item.get('status', 'N/A')})")
        print(f"recommendation: {payload['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
