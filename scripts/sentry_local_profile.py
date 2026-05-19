"""Local profile runner for SkillSentry."""

from __future__ import annotations

from pathlib import Path

import sentry_case_prepare
import sentry_diagnostics
from sentry_gate import build_gate
import sentry_light_profiles
import sentry_local_steps
from sentry_profile_runtime import ProfileTimings, profile_payload, save_json, utc_now
import sentry_profile_state
import sentry_reuse_core
import sentry_run_plan


def local_dry_run_reuse(session_dir: Path, cases_file: Path, args, preflight: dict) -> dict:
    return sentry_reuse_core.local_reuse_forecast(
        session_dir,
        cases_file,
        preflight=preflight,
        model=args.model,
        executor_model=args.executor_model,
        timeout_per_eval=args.timeout_per_eval,
        force_executor=args.force_executor,
        force_grader=args.force_grader,
    )


def find_auto_reuse_session(args, preflight: dict, cases_file: Path) -> dict:
    base = sentry_profile_state.session_root() / str(preflight.get("skill_dir_name") or "")
    return sentry_reuse_core.find_auto_reuse_session(
        base,
        cases_file,
        preflight=preflight,
        model=args.model,
        executor_model=args.executor_model,
        timeout_per_eval=args.timeout_per_eval,
        force_executor=args.force_executor,
        force_grader=args.force_grader,
    )


def _init_session(args, preflight: dict) -> Path:
    return sentry_profile_state.init_session(
        preflight["skill_dir_name"],
        preflight["skill_hash"],
        preflight["skill_type"],
        args.mode,
        preflight,
        preflight.get("runtime", args.runtime),
        utc_now(),
    )


def run_profile_local(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = sentry_light_profiles.run_preflight(args)
    if code != 0:
        return code, profile_payload("local", "ERROR", preflight=preflight, timings=timings.snapshot())
    cases_file = sentry_profile_state.resolve_cases(args, preflight)
    if not cases_file:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error="profile=local requires --cases or cached evals", timings=timings.snapshot())
    if args.dry_run:
        plan = sentry_run_plan.build_profile_plan("local")
        reuse_forecast = None
        if args.reuse_session:
            if args.reuse_session == "auto":
                reuse_forecast = find_auto_reuse_session(args, preflight, cases_file)
            else:
                session_dir = Path(args.reuse_session).expanduser()
                if not session_dir.exists():
                    return 2, profile_payload("local", "ERROR", preflight=preflight, error=f"reuse session not found: {session_dir}", timings=timings.snapshot())
                reuse_forecast = local_dry_run_reuse(session_dir, cases_file, args, preflight)
        payload = profile_payload(
            "local",
            "OK",
            preflight=preflight,
            cases_file=str(cases_file),
            dry_run=True,
            plan=plan,
            reuse_forecast=reuse_forecast,
            timings=timings.snapshot(),
        )
        return 0, payload

    auto_reuse = None
    try:
        with timings.phase("session"):
            if args.reuse_session == "auto":
                auto_reuse = find_auto_reuse_session(args, preflight, cases_file)
                if auto_reuse.get("selected") and auto_reuse.get("session_dir"):
                    session_dir = Path(str(auto_reuse["session_dir"]))
                else:
                    session_dir = _init_session(args, preflight)
            else:
                session_dir = sentry_profile_state.resolve_local_session(args, preflight, utc_now())
    except FileNotFoundError as exc:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error=str(exc), timings=timings.snapshot())
    with timings.phase("session_metadata"):
        sentry_profile_state.refresh_session_metadata(session_dir, args, preflight, utc_now())

    with timings.phase("prepare_cases"):
        prepared = sentry_case_prepare.prepare_cases(session_dir, cases_file)
    if prepared.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            reuse_summary=sentry_reuse_core.summarize_reuse_decisions(prepared),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("executor"):
        model = args.executor_model or args.model
        evals_file = session_dir / "evals.json"
        skill_path = Path(preflight["skill_path"])
        executor = sentry_local_steps.run_executor_with_reuse(
            session_dir=session_dir,
            evals_file=evals_file,
            skill_path=skill_path,
            model=model,
            timeout_per_eval=args.timeout_per_eval,
            force_executor=args.force_executor,
            verbose=args.verbose,
        )
    if executor.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            executor=executor,
            reuse_summary=sentry_reuse_core.summarize_reuse_decisions(prepared, executor),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("grader"):
        grader = sentry_local_steps.run_grader_with_reuse(
            session_dir=session_dir,
            evals_file=evals_file,
            model=args.model,
            force_grader=args.force_grader,
            verbose=args.verbose,
        )
    with timings.phase("diagnostics"):
        gate = grader.get("gate") or build_gate(session_dir)
        diagnostics = sentry_diagnostics.collect_diagnostics(session_dir, gate)
    save_json(session_dir / "diagnostics.json", diagnostics)
    payload = profile_payload(
        "local",
        "OK" if grader.get("status") == "OK" else "ERROR",
        session_dir=str(session_dir),
        auto_reuse=auto_reuse,
        preflight=preflight,
        cases=prepared,
        executor=executor,
        grader=grader,
        reuse_summary=sentry_reuse_core.summarize_reuse_decisions(prepared, executor, grader),
        gate=gate,
        diagnostics=diagnostics,
        manifest=str(sentry_reuse_core.manifest_path(session_dir)),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if payload["status"] == "OK" else 1, payload
