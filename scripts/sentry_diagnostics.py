#!/usr/bin/env python3
"""Deterministic diagnostics for SkillSentry CI and publish outputs."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _status(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("status")
    if isinstance(value, str):
        return value
    return None


def _int_value(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _short_error(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip().replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def collect_executor(session_dir: Path, session: dict) -> dict:
    summary = load_json(session_dir / "executor_results.json")
    if not isinstance(summary, dict):
        summary = _as_dict(_as_dict(session.get("executor")).get("with_skill"))

    results = _as_list(summary.get("results"))
    status_counts: dict[str, int] = {}
    failed_cases = []
    for item in results:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != "success":
            failed_cases.append(
                {
                    "eval_id": item.get("eval_id"),
                    "status": status,
                    "error": _short_error(item.get("error")),
                }
            )

    total = _int_value(summary.get("total"), len(results))
    success = _int_value(summary.get("success"), status_counts.get("success", 0))
    failed = _int_value(summary.get("failed"), max(total - success, 0))
    timeouts = status_counts.get("timeout", 0)
    errors = status_counts.get("error", 0)
    failed_processes = status_counts.get("failed", 0)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "timeouts": timeouts,
        "errors": errors,
        "failed_processes": failed_processes,
        "status_counts": status_counts,
        "failed_cases": failed_cases[:10],
    }


def collect_grader_errors(session_dir: Path) -> list[dict]:
    errors = []
    for path in sorted(session_dir.rglob("grading.json")):
        if "without_skill" in set(path.parts):
            continue
        data = load_json(path)
        if not isinstance(data, dict):
            errors.append(
                {
                    "source": str(path.relative_to(session_dir)),
                    "reason": "grading.json is missing or invalid JSON",
                }
            )
            continue
        summary = _as_dict(data.get("summary"))
        reason = data.get("grader_error") or summary.get("grader_error")
        if reason:
            errors.append(
                {
                    "source": str(path.relative_to(session_dir)),
                    "eval_id": data.get("eval_id"),
                    "reason": _short_error(reason),
                }
            )

    summary = load_json(session_dir / "grading-summary.json")
    if isinstance(summary, dict):
        reason = summary.get("grader_error") or summary.get("error")
        if reason:
            errors.append({"source": "grading-summary.json", "reason": _short_error(reason)})
    return errors


def collect_sync(session: dict) -> dict:
    sync = _as_dict(session.get("sync"))
    return {
        "pull": _status(sync.get("pull")),
        "push_cases": _status(sync.get("push_cases")),
        "push_results": _status(sync.get("push_results")),
        "push_run": _status(sync.get("push_run")),
    }


def collect_publish(session_dir: Path, session: dict) -> dict:
    publish = _as_dict(session.get("publish"))
    payload = load_json(session_dir / "publish-result.json")
    if isinstance(payload, dict):
        publish = payload
    return {
        "status": publish.get("status"),
        "message": _short_error(publish.get("message")),
    }


def collect_preflight(session: dict) -> dict:
    preflight = _as_dict(session.get("preflight"))
    tools = _as_dict(preflight.get("runtime_tools"))
    claude_cli = _as_dict(tools.get("claude_cli"))
    anthropic_sdk = _as_dict(tools.get("anthropic_sdk"))
    anthropic_api_key = _as_dict(tools.get("anthropic_api_key"))
    fallback = _as_dict(tools.get("llm_fallback"))
    cache = _as_dict(preflight.get("cases_cache"))
    config = _as_dict(preflight.get("config"))
    return {
        "status": preflight.get("status"),
        "skill_path": preflight.get("skill_path"),
        "skill_type": preflight.get("skill_type"),
        "skill_hash_short": preflight.get("skill_hash_short"),
        "runtime": preflight.get("runtime"),
        "cached_cases": cache.get("has_cached_cases"),
        "cache_hash_matched": cache.get("hash_matched"),
        "feishu_configured": config.get("feishu_configured"),
        "claude_cli_available": claude_cli.get("available"),
        "claude_cli_path": claude_cli.get("path"),
        "anthropic_sdk_available": anthropic_sdk.get("available"),
        "anthropic_api_key_configured": anthropic_api_key.get("configured"),
        "llm_fallback": fallback.get("mode"),
        "error": preflight.get("error"),
    }


def collect_timing(session: dict) -> dict:
    phases = []
    for item in _as_list(session.get("ci_phase_timings")):
        if not isinstance(item, dict):
            continue
        phases.append(
            {
                "phase": item.get("phase"),
                "status": item.get("status"),
                "duration_ms": item.get("duration_ms"),
                "completed_at": item.get("completed_at"),
            }
        )
    steps = []
    for item in _as_list(session.get("ci_step_timings")):
        if not isinstance(item, dict):
            continue
        steps.append(
            {
                "step": item.get("step"),
                "tool": item.get("tool"),
                "status": item.get("status"),
                "duration_ms": item.get("duration_ms"),
                "completed_at": item.get("completed_at"),
                "error": item.get("error"),
            }
        )
    pipeline = _as_dict(session.get("ci_timing"))
    total = pipeline.get("total_ms")
    if total is None and steps:
        total = round(sum(float(item.get("duration_ms") or 0) for item in steps), 1)
    slowest = sorted(
        [item for item in steps if isinstance(item.get("duration_ms"), (int, float))],
        key=lambda item: item.get("duration_ms", 0),
        reverse=True,
    )[:5]
    return {
        "total_ms": total,
        "phases": phases,
        "steps": steps,
        "slowest_steps": slowest,
        "failed_steps": pipeline.get("failed_steps", []),
    }


def collect_diagnostics(session_dir: str | Path, gate: dict | None = None) -> dict:
    session_path = Path(session_dir)
    session = _as_dict(load_json(session_path / "session.json"))
    gate_data = gate if isinstance(gate, dict) else _as_dict(load_json(session_path / "gate-result.json"))

    case_warnings = _as_list(session.get("case_warnings"))
    executor = collect_executor(session_path, session)
    grader_errors = collect_grader_errors(session_path)
    sync = collect_sync(session)
    publish = collect_publish(session_path, session)
    preflight = collect_preflight(session)
    timings = collect_timing(session)
    delta = _as_dict(gate_data.get("delta"))

    categories = []
    notes = []

    if preflight.get("status") and preflight.get("status") != "OK":
        categories.append("preflight_error")
        notes.append(f"Preflight failed: {preflight.get('error') or preflight.get('status')}.")

    if preflight.get("status") == "OK":
        if preflight.get("claude_cli_available") is False:
            categories.append("runner_unavailable")
            notes.append("Claude CLI was not found during preflight; executor steps cannot run in real CI.")
        if (
            preflight.get("anthropic_sdk_available") is False
            and preflight.get("llm_fallback") != "claude"
        ):
            categories.append("llm_unavailable")
            notes.append("Anthropic SDK is unavailable and Claude CLI fallback is not enabled.")
        elif (
            preflight.get("anthropic_api_key_configured") is False
            and preflight.get("llm_fallback") != "claude"
        ):
            categories.append("llm_unavailable")
            notes.append("ANTHROPIC_API_KEY is not configured and Claude CLI fallback is not enabled.")

    if case_warnings:
        categories.append("case_unusable")
        notes.append(f"{len(case_warnings)} case feasibility warning(s) recorded.")

    if executor["timeouts"]:
        categories.append("runner_timeout")
        notes.append(f"{executor['timeouts']} executor run(s) timed out.")
    elif executor["failed_processes"] or executor["errors"]:
        categories.append("runner_error")
        notes.append(
            f"{executor['failed_processes'] + executor['errors']} executor run(s) failed before grading."
        )

    if grader_errors:
        categories.append("grader_error")
        notes.append(f"{len(grader_errors)} grader error(s) recorded.")

    skipped_sync = [key for key, value in sync.items() if value == "skipped_no_config"]
    if skipped_sync:
        categories.append("environment_skipped")
        notes.append("Sync skipped because Feishu configuration is unavailable: " + ", ".join(skipped_sync) + ".")

    without_skill = _as_dict(session.get("without_skill"))
    if without_skill.get("status") == "partial":
        if "environment_skipped" not in categories:
            categories.append("environment_skipped")
        reason = without_skill.get("reason") or "without_skill baseline is partial."
        notes.append(_short_error(reason))

    verdict = gate_data.get("verdict")
    rate = gate_data.get("authoritative_pass_rate")
    counts = _as_dict(gate_data.get("counts"))
    technical_blockers = {
        "preflight_error",
        "runner_unavailable",
        "llm_unavailable",
        "case_unusable",
        "runner_timeout",
        "runner_error",
        "grader_error",
    }
    if (
        verdict == "FAIL"
        and rate is not None
        and _int_value(counts.get("total_total")) > 0
        and not any(category in technical_blockers for category in categories)
    ):
        categories.append("quality_failure")
        notes.append("Gate failed with grading data available; inspect assertion failures for skill-quality issues.")

    if not categories:
        notes.append("No CI execution diagnostics were recorded.")

    return {
        "case_warnings_count": len(case_warnings),
        "case_warnings": case_warnings[:10],
        "preflight": preflight,
        "executor": executor,
        "grader_errors": grader_errors,
        "sync": sync,
        "delta": {
            "status": delta.get("status"),
            "value": delta.get("value"),
            "reason": delta.get("reason"),
        },
        "publish": publish,
        "timings": timings,
        "categories": categories,
        "notes": notes,
    }


def render_markdown(diagnostics: dict) -> str:
    preflight = _as_dict(diagnostics.get("preflight"))
    executor = _as_dict(diagnostics.get("executor"))
    sync = _as_dict(diagnostics.get("sync"))
    delta = _as_dict(diagnostics.get("delta"))
    publish = _as_dict(diagnostics.get("publish"))
    timings = _as_dict(diagnostics.get("timings"))
    total_ms = timings.get("total_ms")
    total_text = str(total_ms) if total_ms is not None else "N/A"
    slowest = _as_list(timings.get("slowest_steps"))
    phases = _as_list(timings.get("phases"))
    slowest_text = ", ".join(
        f"{item.get('step')}={item.get('duration_ms')}ms" for item in slowest[:3] if isinstance(item, dict)
    ) or "N/A"
    phases_text = ", ".join(
        f"{item.get('phase')}={item.get('duration_ms')}ms" for item in phases[:3] if isinstance(item, dict)
    ) or "N/A"
    lines = [
        "### Execution Diagnostics",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Categories | {', '.join(diagnostics.get('categories') or ['none'])} |",
        (
            "| Preflight | "
            f"{preflight.get('status') or 'N/A'}, "
            f"type={preflight.get('skill_type') or 'N/A'}, "
            f"claude_cli={preflight.get('claude_cli_available') if preflight else 'N/A'} |"
        ),
        f"| Case warnings | {diagnostics.get('case_warnings_count', 0)} |",
        (
            "| Executor | "
            f"{executor.get('success', 0)}/{executor.get('total', 0)} success, "
            f"{executor.get('failed', 0)} failed, {executor.get('timeouts', 0)} timeout(s) |"
        ),
        f"| Grader errors | {len(_as_list(diagnostics.get('grader_errors')))} |",
        (
            "| Sync | "
            f"pull={sync.get('pull') or 'N/A'}, "
            f"push_cases={sync.get('push_cases') or 'N/A'}, "
            f"push_results={sync.get('push_results') or 'N/A'} |"
        ),
        f"| Delta | {delta.get('status') or 'N/A'} |",
        f"| Publish | {publish.get('status') or 'N/A'} |",
        f"| CI timing | total={total_text}ms; slowest={slowest_text} |",
        f"| CI phases | {phases_text} |",
        "",
    ]

    for note in _as_list(diagnostics.get("notes")):
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def render_html_section(diagnostics: dict) -> str:
    preflight = _as_dict(diagnostics.get("preflight"))
    executor = _as_dict(diagnostics.get("executor"))
    sync = _as_dict(diagnostics.get("sync"))
    delta = _as_dict(diagnostics.get("delta"))
    publish = _as_dict(diagnostics.get("publish"))
    timings = _as_dict(diagnostics.get("timings"))
    total_ms = timings.get("total_ms")
    total_text = str(total_ms) if total_ms is not None else "N/A"
    categories = ", ".join(diagnostics.get("categories") or ["none"])
    notes = "".join(f"<li>{html.escape(str(note))}</li>" for note in _as_list(diagnostics.get("notes")))
    grader_errors = _as_list(diagnostics.get("grader_errors"))
    grader_items = "".join(
        "<li>"
        + html.escape(str(item.get("source", "grading")))
        + ": "
        + html.escape(str(item.get("reason", "")))
        + "</li>"
        for item in grader_errors[:10]
        if isinstance(item, dict)
    )
    if not grader_items:
        grader_items = "<li>none</li>"
    timing_items = "".join(
        "<li>"
        + html.escape(str(item.get("step", "unknown")))
        + ": "
        + html.escape(str(item.get("duration_ms", "N/A")))
        + "ms ("
        + html.escape(str(item.get("status", "N/A")))
        + ")</li>"
        for item in _as_list(timings.get("steps"))[:20]
        if isinstance(item, dict)
    )
    if not timing_items:
        timing_items = "<li>N/A</li>"
    phase_items = "".join(
        "<li>"
        + html.escape(str(item.get("phase", "unknown")))
        + ": "
        + html.escape(str(item.get("duration_ms", "N/A")))
        + "ms ("
        + html.escape(str(item.get("status", "N/A")))
        + ")</li>"
        for item in _as_list(timings.get("phases"))[:20]
        if isinstance(item, dict)
    )
    if not phase_items:
        phase_items = "<li>N/A</li>"

    return f"""
  <h2>Execution Diagnostics</h2>
  <table>
    <tr><th>Categories</th><td>{html.escape(categories)}</td></tr>
    <tr><th>Preflight</th><td>{html.escape(str(preflight.get("status") or "N/A"))}, type={html.escape(str(preflight.get("skill_type") or "N/A"))}, claude_cli={html.escape(str(preflight.get("claude_cli_available") if preflight else "N/A"))}</td></tr>
    <tr><th>Case warnings</th><td>{diagnostics.get("case_warnings_count", 0)}</td></tr>
    <tr><th>Executor</th><td>{executor.get("success", 0)}/{executor.get("total", 0)} success, {executor.get("failed", 0)} failed, {executor.get("timeouts", 0)} timeout(s)</td></tr>
    <tr><th>Sync</th><td>pull={html.escape(str(sync.get("pull") or "N/A"))}, push_cases={html.escape(str(sync.get("push_cases") or "N/A"))}, push_results={html.escape(str(sync.get("push_results") or "N/A"))}</td></tr>
    <tr><th>Delta</th><td>{html.escape(str(delta.get("status") or "N/A"))}</td></tr>
    <tr><th>Publish</th><td>{html.escape(str(publish.get("status") or "N/A"))}</td></tr>
    <tr><th>CI timing</th><td>{html.escape(total_text)}ms</td></tr>
  </table>
  <h3>Notes</h3>
  <ul>{notes}</ul>
  <h3>Grader errors</h3>
  <ul>{grader_items}</ul>
  <h3>Step timings</h3>
  <ul>{timing_items}</ul>
  <h3>Phase timings</h3>
  <ul>{phase_items}</ul>
"""
