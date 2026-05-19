"""Lightweight preflight, lint, and plan profile runners."""

from __future__ import annotations

import argparse

import sentry_case_prepare
import sentry_preflight
from sentry_profile_runtime import ProfileTimings, profile_payload, save_json, utc_now
import sentry_profile_state
import sentry_reuse_core
import sentry_run_plan


def run_preflight(args) -> tuple[int, dict]:
    preflight_args = argparse.Namespace(
        skill=args.skill,
        mode=args.mode,
        runtime=args.runtime,
        config=args.config,
        format="json",
    )
    return sentry_preflight.build_result(preflight_args)


def run_profile_preflight(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    return code, profile_payload("preflight", "OK" if code == 0 else "ERROR", preflight=preflight, timings=timings.snapshot())


def run_profile_lint(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    if code != 0:
        return code, profile_payload("lint", "ERROR", preflight=preflight, timings=timings.snapshot())

    with timings.phase("session"):
        session_dir = sentry_profile_state.init_session(
            preflight["skill_dir_name"],
            preflight["skill_hash"],
            preflight["skill_type"],
            args.mode,
            preflight,
            preflight.get("runtime", args.runtime),
            utc_now(),
        )
    cases_file = sentry_profile_state.resolve_cases(args, preflight)
    if not cases_file:
        payload = profile_payload(
            "lint",
            "WARN",
            session_dir=str(session_dir),
            preflight=preflight,
            warning="No evals.json/cases.cache.json found; only preflight completed.",
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 0, payload

    with timings.phase("prepare_cases"):
        prepared = sentry_case_prepare.prepare_cases(session_dir, cases_file)
    status = "OK" if prepared.get("status") == "OK" and prepared.get("case_lint", {}).get("warning_count", 0) == 0 else "WARN"
    payload = profile_payload(
        "lint",
        status,
        session_dir=str(session_dir),
        preflight=preflight,
        cases=prepared,
        reuse_summary=sentry_reuse_core.summarize_reuse_decisions(prepared),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if prepared.get("status") == "OK" else 1, payload


def run_profile_plan(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    plan = sentry_run_plan.build_mode_plan(args.mode)
    payload = profile_payload(
        "plan",
        "OK" if code == 0 else "ERROR",
        mode=args.mode,
        preflight=preflight,
        plan=plan,
        dry_run=True,
        timings=timings.snapshot(),
    )
    return code, payload
