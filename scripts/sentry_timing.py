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


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 1)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _duration_ms(value) -> float | None:
    if isinstance(value, bool):
        return None
    if value is None:
        return None
    duration = _number(value, default=-1.0)
    if duration < 0:
        return None
    return round(duration * 1000, 1)


def _milliseconds(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    duration = _number(value, default=-1.0)
    if duration < 0:
        return None
    return round(duration, 1)


def timing_from_eval_result(path: Path) -> tuple[dict, dict]:
    payload = load_json(path)
    return _as_dict(payload.get("timings")), {
        "source": str(path),
        "kind": "eval_result",
        "verdict": payload.get("verdict"),
        "status": payload.get("status"),
        "artifacts": _as_dict(payload.get("artifacts")),
    }


def timing_from_session(path: Path) -> tuple[dict, dict]:
    session_file = path / "session.json" if path.is_dir() else path
    session = load_json(session_file)
    timing = _as_dict(session.get("ci_timing"))
    steps = _as_list(session.get("ci_step_timings"))
    phases = _as_list(session.get("ci_phase_timings"))
    run_result = session_file.parent / "sentry-run-result.json"
    if not timing and not steps and not phases and run_result.exists():
        return timing_from_sentry_run_result(run_result, load_json(run_result))
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


def timing_from_sentry_run_result(path: Path, payload: dict) -> tuple[dict, dict]:
    timings = _as_dict(payload.get("timings"))
    phases_ms = _as_dict(timings.get("phases_ms"))
    phases = [
        {"phase": str(name), "status": "OK", "duration_ms": _milliseconds(duration)}
        for name, duration in phases_ms.items()
        if _milliseconds(duration) is not None
    ]
    reuse_decisions = []
    for key in ("executor", "grader"):
        section = _as_dict(payload.get(key))
        if not section:
            continue
        reuse = _as_dict(section.get("reuse"))
        reuse_decisions.append(
            {
                "step": section.get("step") or key,
                "reused": section.get("reused"),
                "reason": reuse.get("reason"),
                "reusable": reuse.get("reusable"),
            }
        )
    return {
        "total_ms": timings.get("total_ms"),
        "steps": [],
        "phases": phases,
        "failed_steps": [],
    }, {
        "source": str(path),
        "kind": "sentry_run_result",
        "profile": payload.get("profile"),
        "status": payload.get("status"),
        "session_dir": payload.get("session_dir"),
        "reuse_decisions": reuse_decisions,
    }


def load_timing(path: Path) -> tuple[dict, dict]:
    if path.is_dir() or path.name == "session.json":
        return timing_from_session(path)
    payload = load_json(path)
    if "profile" in payload and "timings" in payload:
        return timing_from_sentry_run_result(path, payload)
    if "timings" in payload:
        return _as_dict(payload.get("timings")), {
            "source": str(path),
            "kind": "eval_result",
            "verdict": payload.get("verdict"),
            "status": payload.get("status"),
            "artifacts": _as_dict(payload.get("artifacts")),
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


def resolve_session_dir(input_path: Path, meta: dict) -> Path | None:
    if meta.get("kind") == "session":
        source = Path(str(meta.get("source") or ""))
        if source.name == "session.json":
            return source.parent
        return source if source.is_dir() else None
    if meta.get("kind") == "sentry_run_result":
        session_dir = meta.get("session_dir")
        if isinstance(session_dir, str) and session_dir:
            raw_candidate = Path(session_dir)
            candidates = [raw_candidate]
            if not raw_candidate.is_absolute():
                candidates.extend([input_path.parent / raw_candidate, Path.cwd() / raw_candidate])
            for candidate in candidates:
                if (candidate / "session.json").exists():
                    return candidate
        if (input_path.parent / "session.json").exists():
            return input_path.parent

    artifacts = _as_dict(meta.get("artifacts"))
    session_report = artifacts.get("session_report_html")
    if isinstance(session_report, str) and session_report:
        report_path = Path(session_report)
        candidates = [report_path]
        if not report_path.is_absolute():
            candidates.append(input_path.parent / report_path)
            candidates.append(Path.cwd() / report_path)
        for candidate in candidates:
            if candidate.exists() and candidate.name == "report.html":
                session_dir = candidate.parent
                if (session_dir / "session.json").exists():
                    return session_dir

    if (input_path.parent / "session.json").exists():
        return input_path.parent
    return None


def load_executor_summary(session_dir: Path, variant: str) -> dict:
    filename = "executor_results.json" if variant == "with_skill" else f"executor_{variant}_results.json"
    path = session_dir / filename
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {}
    return payload


def summarize_executor_variant(summary: dict, variant: str, top: int) -> dict:
    rows = []
    for item in _as_list(summary.get("results")):
        if not isinstance(item, dict):
            continue
        duration_ms = _duration_ms(item.get("duration"))
        if duration_ms is None:
            continue
        rows.append(
            {
                "variant": variant,
                "eval_id": item.get("eval_id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "duration_ms": duration_ms,
            }
        )

    durations = [item["duration_ms"] for item in rows]
    slowest = sorted(rows, key=lambda item: item.get("duration_ms", 0), reverse=True)
    total = _number(summary.get("total"), len(_as_list(summary.get("results"))))
    success = _number(summary.get("success"), 0)
    failed = _number(summary.get("failed"), max(total - success, 0))
    duration_total = sum(durations)
    return {
        "variant": variant,
        "total": int(total),
        "success": int(success),
        "failed": int(failed),
        "timed": len(rows),
        "duration_ms": {
            "total": _round(duration_total),
            "avg": _round(duration_total / len(durations)) if durations else None,
            "p50": _round(_percentile(durations, 0.50)),
            "p95": _round(_percentile(durations, 0.95)),
            "max": _round(max(durations)) if durations else None,
        },
        "slowest_cases": slowest[:top],
    }


def summarize_duration_rows(rows: list[dict], total: int, top: int) -> dict:
    durations = [item["duration_ms"] for item in rows]
    slowest = sorted(rows, key=lambda item: item.get("duration_ms", 0), reverse=True)
    duration_total = sum(durations)
    return {
        "total": total,
        "timed": len(rows),
        "duration_ms": {
            "total": _round(duration_total),
            "avg": _round(duration_total / len(durations)) if durations else None,
            "p50": _round(_percentile(durations, 0.50)),
            "p95": _round(_percentile(durations, 0.95)),
            "max": _round(max(durations)) if durations else None,
        },
        "slowest_cases": slowest[:top],
    }


def executor_timing(session_dir: Path | None, top: int) -> dict:
    if session_dir is None:
        return {"available": False, "reason": "session_dir_unavailable"}

    variants = []
    for variant in ("with_skill", "without_skill"):
        try:
            summary = load_executor_summary(session_dir, variant)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if summary:
            variants.append(summarize_executor_variant(summary, variant, top))

    if not variants:
        return {"available": False, "reason": "executor_results_unavailable", "session_dir": str(session_dir)}

    slowest_cases = []
    for variant in variants:
        slowest_cases.extend(_as_list(variant.get("slowest_cases")))
    slowest_cases = sorted(slowest_cases, key=lambda item: item.get("duration_ms", 0), reverse=True)[:top]
    return {
        "available": True,
        "session_dir": str(session_dir),
        "variants": variants,
        "slowest_cases": slowest_cases,
    }


def find_grading_files(session_dir: Path) -> list[Path]:
    files = []
    for path in session_dir.rglob("grading.json"):
        if "without_skill" in set(path.parts):
            continue
        files.append(path)
    return sorted(files)


def grading_duration_ms(payload: dict) -> float | None:
    for source in (payload, _as_dict(payload.get("summary")), _as_dict(payload.get("timing"))):
        for key in ("duration_ms", "grader_duration_ms", "grading_duration_ms"):
            duration = _milliseconds(source.get(key))
            if duration is not None:
                return duration
        for key in ("duration_seconds", "grader_duration_seconds", "grading_duration_seconds"):
            duration = _duration_ms(source.get(key))
            if duration is not None:
                return duration
    return None


def grader_timing(session_dir: Path | None, top: int) -> dict:
    if session_dir is None:
        return {"available": False, "reason": "session_dir_unavailable"}

    grading_files = find_grading_files(session_dir)
    if not grading_files:
        return {"available": False, "reason": "grading_files_unavailable", "session_dir": str(session_dir)}

    rows = []
    for path in grading_files:
        try:
            payload = load_json(path)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        duration_ms = grading_duration_ms(payload)
        if duration_ms is None:
            continue
        summary = _as_dict(payload.get("summary"))
        rows.append(
            {
                "eval_id": payload.get("eval_id") or path.parent.name,
                "source": str(path.relative_to(session_dir)),
                "status": "ERROR" if summary.get("grader_error") or payload.get("grader_error") else "OK",
                "duration_ms": duration_ms,
                "assertions": summary.get("total"),
                "passed": summary.get("pass") if "pass" in summary else summary.get("passed"),
                "failed": summary.get("fail") if "fail" in summary else summary.get("failed"),
            }
        )

    if not rows:
        return {
            "available": False,
            "reason": "grader_timing_unavailable",
            "session_dir": str(session_dir),
            "grading_files": len(grading_files),
            "timed": 0,
        }

    summary = summarize_duration_rows(rows, total=len(grading_files), top=top)
    summary.update({"available": True, "session_dir": str(session_dir), "grading_files": len(grading_files)})
    return summary


def recommendation(step: dict) -> str:
    name = str(step.get("step") or step.get("phase") or "")
    duration = _number(step.get("duration_ms"))
    if not name:
        return "No timing data available."
    if name in {"executor-with", "executor-without", "executor"}:
        return "Executor dominates; reduce eval count, reuse local profile artifacts, or inspect per-eval runner time before adding cache."
    if name in {"grader-report", "grader"}:
        return "Grader dominates; inspect assertion count and LLM fallback/API latency before changing scoring."
    if name in {"cases", "prepare_cases"}:
        return "Cases dominate; prefer cached cases or lint/preflight profiles when case design is not being tested."
    if name == "diagnostics":
        return "Diagnostics dominates; inspect artifact size and report regeneration cost before changing pipeline behavior."
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
    session_dir = resolve_session_dir(path, meta)
    return {
        "status": "OK",
        "source": meta,
        "total_ms": timings.get("total_ms"),
        "top_steps": steps[:top],
        "top_phases": phases[:top],
        "failed_steps": timings.get("failed_steps", []),
        "reuse_decisions": _as_list(meta.get("reuse_decisions")),
        "executor_timing": executor_timing(session_dir, top),
        "grader_timing": grader_timing(session_dir, top),
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
        reuse_decisions = _as_list(payload.get("reuse_decisions"))
        if reuse_decisions:
            print("reuse decisions:")
            for item in reuse_decisions:
                print(f"- {item.get('step')}: reused={item.get('reused')} reason={item.get('reason')}")
        executor = _as_dict(payload.get("executor_timing"))
        if executor.get("available"):
            print("executor timing:")
            for variant in _as_list(executor.get("variants")):
                duration = _as_dict(variant.get("duration_ms"))
                print(
                    f"- {variant.get('variant')}: timed {variant.get('timed')}/{variant.get('total')} "
                    f"avg={duration.get('avg')}ms p50={duration.get('p50')}ms "
                    f"p95={duration.get('p95')}ms max={duration.get('max')}ms"
                )
            print("slowest executor cases:")
            for item in _as_list(executor.get("slowest_cases")):
                print(
                    f"- {item.get('variant')} {item.get('eval_id')}: "
                    f"{item.get('duration_ms')}ms ({item.get('status', 'N/A')})"
                )
        grader = _as_dict(payload.get("grader_timing"))
        if grader.get("available"):
            duration = _as_dict(grader.get("duration_ms"))
            print(
                "grader timing: "
                f"timed {grader.get('timed')}/{grader.get('total')} "
                f"avg={duration.get('avg')}ms p50={duration.get('p50')}ms "
                f"p95={duration.get('p95')}ms max={duration.get('max')}ms"
            )
            print("slowest grader cases:")
            for item in _as_list(grader.get("slowest_cases")):
                print(f"- {item.get('eval_id')}: {item.get('duration_ms')}ms ({item.get('status', 'N/A')})")
        elif grader.get("session_dir"):
            print(f"grader timing: unavailable ({grader.get('reason')})")
        print(f"recommendation: {payload['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
