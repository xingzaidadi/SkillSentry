"""Text rendering helpers for sentry_run profile payloads."""

from __future__ import annotations


def render_text(payload: dict) -> str:
    """Render a profile payload in the stable human-readable CLI format."""
    lines = [f"sentry run: {payload['status']} | profile: {payload['profile']}"]
    if payload.get("session_dir"):
        lines.append(f"session: {payload['session_dir']}")

    timings = payload.get("timings", {})
    if isinstance(timings, dict) and timings.get("total_ms") is not None:
        lines.append(f"duration_ms: {timings['total_ms']}")

    if payload.get("error"):
        lines.append(f"- {payload['error']}")
    if payload.get("warning"):
        lines.append(f"- {payload['warning']}")

    if payload.get("dry_run"):
        lines.append("dry-run: inspected inputs and rendered the plan only; no executor/grader/CI heavy steps were started")
    lines.extend(_render_plan_lines(payload.get("plan")))
    lines.extend(_render_reuse_summary_lines(payload.get("reuse_summary", {})))
    lines.extend(_render_reuse_forecast_lines(payload.get("reuse_forecast")))

    artifacts = payload.get("artifacts", {})
    if isinstance(artifacts, dict) and artifacts.get("report_html"):
        lines.append(f"report: {artifacts['report_html']}")

    return "\n".join(lines) + "\n"


def _render_plan_lines(plan) -> list[str]:
    if not isinstance(plan, dict) or not plan.get("steps"):
        return []

    lines = ["plan:"]
    summary = plan.get("summary")
    if isinstance(summary, dict):
        lines.append(
            "summary: "
            f"{summary.get('step_count', 0)} steps; "
            f"{summary.get('llm_step_count', 0)} llm-heavy; "
            f"{summary.get('network_step_count', 0)} network; "
            f"cost_level={plan.get('cost_level', 'unknown')}"
        )
    for item in plan["steps"]:
        markers = []
        if item.get("heavy"):
            markers.append("heavy")
        if item.get("requires_llm"):
            markers.append("llm")
        if item.get("requires_network"):
            markers.append("network")
        suffix = f" [{', '.join(markers)}]" if markers else ""
        lines.append(f"- {item.get('step')}: {item.get('tool')}{suffix}")

    if plan.get("heavy_steps"):
        lines.append("heavy steps: " + ", ".join(str(item) for item in plan.get("heavy_steps", [])))
    if plan.get("network_steps"):
        lines.append("network steps: " + ", ".join(str(item) for item in plan.get("network_steps", [])))
    return lines


def _render_reuse_summary_lines(reuse_summary) -> list[str]:
    if not isinstance(reuse_summary, dict) or not reuse_summary.get("steps"):
        return []

    lines = ["reuse:"]
    for item in reuse_summary["steps"]:
        if not isinstance(item, dict):
            continue
        action = "reused" if item.get("reused") else "reran"
        details = []
        if item.get("missing_outputs_count"):
            details.append(f"missing_outputs={item.get('missing_outputs_count')}")
        if item.get("recorded_status") is not None:
            details.append(f"recorded_status={item.get('recorded_status')}")
        if item.get("recorded_type") is not None:
            details.append(f"recorded_type={item.get('recorded_type')}")
        if item.get("expected_input_hash") and item.get("recorded_input_hash"):
            details.append("input_hash_changed")
        if item.get("expected_cases_hash") and item.get("prepared_cases_hash"):
            details.append("cases_hash_changed")
        suffix = f"; {', '.join(details)}" if details else ""
        lines.append(f"- {item.get('step')}: {action} ({item.get('reason')}{suffix})")

    hints = reuse_summary.get("hints")
    if isinstance(hints, list) and hints:
        lines.append("reuse hints:")
        for hint in hints:
            lines.append(f"- {hint}")
    return lines


def _render_reuse_forecast_lines(reuse_forecast) -> list[str]:
    if not isinstance(reuse_forecast, dict) or not isinstance(reuse_forecast.get("summary"), dict):
        return []

    forecast_summary = reuse_forecast["summary"]
    if not forecast_summary.get("steps"):
        return []

    lines = ["reuse forecast:"]
    for item in forecast_summary["steps"]:
        action = "would reuse" if item.get("reused") else "would rerun"
        lines.append(f"- {item.get('step')}: {action} ({item.get('reason')})")
    return lines
