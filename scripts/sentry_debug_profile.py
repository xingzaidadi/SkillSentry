"""Debug profile runner for existing SkillSentry sessions."""

from __future__ import annotations

from pathlib import Path

import sentry_diagnostics
from sentry_gate import build_gate
from sentry_profile_runtime import ProfileTimings, profile_payload, save_json
import sentry_report


def run_profile_debug(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    if not args.session_dir:
        return 2, profile_payload("debug", "ERROR", error="--session-dir is required for profile=debug", timings=timings.snapshot())
    session_dir = Path(args.session_dir).expanduser()
    if not session_dir.exists():
        return 2, profile_payload("debug", "ERROR", error=f"session dir not found: {session_dir}", timings=timings.snapshot())

    with timings.phase("gate"):
        gate = build_gate(session_dir)
    save_json(session_dir / "gate-result.json", gate)
    with timings.phase("diagnostics"):
        diagnostics = sentry_diagnostics.collect_diagnostics(session_dir, gate)
    save_json(session_dir / "diagnostics.json", diagnostics)
    with timings.phase("report"):
        report = sentry_report.ensure_session_report(
            session_dir,
            gate,
            title="SkillSentry Debug Report",
            generated_by="sentry_run.py",
            footer="Debug profile recalculates gate, diagnostics, and report from existing artifacts.",
            replace_generated_only=False,
        )
    payload = profile_payload(
        "debug",
        "OK",
        session_dir=str(session_dir),
        gate=gate,
        diagnostics=diagnostics,
        artifacts={"report_html": str(report), "diagnostics_json": str(session_dir / "diagnostics.json")},
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0, payload
