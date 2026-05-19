#!/usr/bin/env python3
"""Profile-based SkillSentry runner.

This is the lightweight user-facing composer. It does not replace sentry_ci.py:
CI/release profiles delegate to sentry_ci.py, while daily profiles compose the
small tools directly.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_artifacts
import sentry_case_prepare
import sentry_diagnostics
import sentry_grader
import sentry_preflight
from sentry_profile_runtime import ProfileTimings, profile_payload, utc_now
import sentry_profile_state
import sentry_report
import sentry_reuse_core
import sentry_run_output
import sentry_run_plan
from sentry_executor import execute_executor_step
from sentry_gate import build_gate
from sentry_pipeline import PIPELINES


LIGHT_PROFILES = {"preflight", "lint", "debug", "plan"}
HEAVY_PROFILES = {"local", "ci", "release"}
PROFILES = sorted(LIGHT_PROFILES | HEAVY_PROFILES)


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path: Path) -> str | None:
    return sentry_reuse_core.file_hash(path)


def session_root() -> Path:
    return sentry_profile_state.session_root()


def manifest_path(session_dir: Path) -> Path:
    return sentry_reuse_core.manifest_path(session_dir)


def load_manifest(session_dir: Path) -> dict:
    return sentry_reuse_core.load_manifest(session_dir)


def save_manifest(session_dir: Path, manifest: dict) -> None:
    sentry_reuse_core.save_manifest(session_dir, manifest)


def step_reuse_state(session_dir: Path, step: str, input_hash: str, required: list[Path]) -> dict:
    return sentry_reuse_core.step_reuse_state(session_dir, step, input_hash, required)


def step_reusable(session_dir: Path, step: str, input_hash: str, required: list[Path]) -> bool:
    return sentry_reuse_core.step_reusable(session_dir, step, input_hash, required)


def record_manifest_step(session_dir: Path, step: str, *, status: str, input_hash: str, outputs: list[Path], extra: dict | None = None) -> dict:
    return sentry_reuse_core.record_manifest_step(session_dir, step, status=status, input_hash=input_hash, outputs=outputs, extra=extra)


def summarize_reuse_decisions(*sections: dict) -> dict:
    return sentry_reuse_core.summarize_reuse_decisions(*sections)


def unique_paths(paths: list[Path]) -> list[Path]:
    return sentry_reuse_core.unique_paths(paths)


def combine_hash(*parts) -> str:
    return sentry_reuse_core.combine_hash(*parts)


def build_mode_plan(mode: str) -> dict:
    return sentry_run_plan.build_mode_plan(mode)


def build_profile_plan(profile: str) -> dict:
    return sentry_run_plan.build_profile_plan(profile)


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
    base = session_root() / str(preflight.get("skill_dir_name") or "")
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


def run_preflight(args) -> tuple[int, dict]:
    preflight_args = argparse.Namespace(
        skill=args.skill,
        mode=args.mode,
        runtime=args.runtime,
        config=args.config,
        format="json",
    )
    return sentry_preflight.build_result(preflight_args)


def init_session(skill_name: str, skill_hash: str, skill_type: str, mode: str, preflight: dict, runtime: str) -> Path:
    return sentry_profile_state.init_session(skill_name, skill_hash, skill_type, mode, preflight, runtime, utc_now())


def resolve_local_session(args, preflight: dict) -> Path:
    return sentry_profile_state.resolve_local_session(args, preflight, utc_now())


def refresh_session_metadata(session_dir: Path, args, preflight: dict) -> None:
    sentry_profile_state.refresh_session_metadata(session_dir, args, preflight, utc_now())


def cached_cases_from_preflight(preflight: dict) -> Path | None:
    return sentry_profile_state.cached_cases_from_preflight(preflight)


def resolve_cases(args, preflight: dict) -> Path | None:
    return sentry_profile_state.resolve_cases(args, preflight)


def same_path(left: Path, right: Path) -> bool:
    return sentry_profile_state.same_path(left, right)


def prepared_cases_reuse_state(session_dir: Path, target: Path, cases_hash: str | None) -> dict:
    return sentry_reuse_core.prepared_cases_reuse_state(session_dir, target, cases_hash)


def reusable_prepared_cases(session_dir: Path, cases_file: Path, target: Path, cases_hash: str | None, reuse_state: dict) -> dict | None:
    return sentry_reuse_core.reusable_prepared_cases(session_dir, cases_file, target, cases_hash, reuse_state)


def prepare_cases(session_dir: Path, cases_file: Path) -> dict:
    return sentry_case_prepare.prepare_cases(session_dir, cases_file)


def expected_response_outputs(evals_file: Path, session_dir: Path, variant: str = "with_skill") -> list[Path]:
    return sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).response_outputs(variant)


def expected_grading_outputs(evals_file: Path, session_dir: Path) -> list[Path]:
    return sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).grading_outputs()


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
        session_dir = init_session(
            preflight["skill_dir_name"],
            preflight["skill_hash"],
            preflight["skill_type"],
            args.mode,
            preflight,
            preflight.get("runtime", args.runtime),
        )
    cases_file = resolve_cases(args, preflight)
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
        prepared = prepare_cases(session_dir, cases_file)
    status = "OK" if prepared.get("status") == "OK" and prepared.get("case_lint", {}).get("warning_count", 0) == 0 else "WARN"
    payload = profile_payload(
        "lint",
        status,
        session_dir=str(session_dir),
        preflight=preflight,
        cases=prepared,
        reuse_summary=summarize_reuse_decisions(prepared),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if prepared.get("status") == "OK" else 1, payload


def run_profile_plan(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    plan = build_mode_plan(args.mode)
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


def run_profile_local(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    if code != 0:
        return code, profile_payload("local", "ERROR", preflight=preflight, timings=timings.snapshot())
    cases_file = resolve_cases(args, preflight)
    if not cases_file:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error="profile=local requires --cases or cached evals", timings=timings.snapshot())
    if args.dry_run:
        plan = build_profile_plan("local")
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
                    session_dir = init_session(
                        preflight["skill_dir_name"],
                        preflight["skill_hash"],
                        preflight["skill_type"],
                        args.mode,
                        preflight,
                        preflight.get("runtime", args.runtime),
                    )
            else:
                session_dir = resolve_local_session(args, preflight)
    except FileNotFoundError as exc:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error=str(exc), timings=timings.snapshot())
    with timings.phase("session_metadata"):
        refresh_session_metadata(session_dir, args, preflight)

    with timings.phase("prepare_cases"):
        prepared = prepare_cases(session_dir, cases_file)
    if prepared.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            reuse_summary=summarize_reuse_decisions(prepared),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("executor"):
        model = args.executor_model or args.model
        evals_file = session_dir / "evals.json"
        skill_path = Path(preflight["skill_path"])
        executor_hash = combine_hash(
            "executor-with",
            file_hash(evals_file),
            file_hash(skill_path),
            model,
            args.timeout_per_eval,
        )
        executor_outputs = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).required_outputs("executor-with")
        executor_reuse = step_reuse_state(session_dir, "executor-with", executor_hash, executor_outputs)
        if not args.force_executor and executor_reuse.get("reusable"):
            executor = {
                "status": "OK",
                "step": "executor-with",
                "variant": "with_skill",
                "reused": True,
                "reuse": executor_reuse,
                "summary_file": str(session_dir / "executor_results.json"),
                "summary": load_json(session_dir / "executor_results.json"),
            }
        else:
            executor = execute_executor_step(
                evals_file=evals_file,
                skill_path=skill_path,
                session_dir=session_dir,
                model=model,
                timeout_per_eval=args.timeout_per_eval,
                variant="with_skill",
                verbose=args.verbose,
                update_session=True,
            )
            executor["reused"] = False
            executor["reuse"] = {"step": "executor-with", "reusable": False, "reason": "force_executor"} if args.force_executor else executor_reuse
            record_manifest_step(
                session_dir,
                "executor-with",
                status=executor.get("status", "ERROR"),
                input_hash=executor_hash,
                outputs=executor_outputs,
                extra={"model": model, "timeout_per_eval": args.timeout_per_eval},
            )
    if executor.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            executor=executor,
            reuse_summary=summarize_reuse_decisions(prepared, executor),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("grader"):
        response_hashes = [(str(path), file_hash(path)) for path in expected_response_outputs(evals_file, session_dir)]
        grader_hash = combine_hash("grader-report", file_hash(evals_file), response_hashes, args.model)
        grader_outputs = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).required_outputs("grader-report")
        grader_reuse = step_reuse_state(session_dir, "grader-report", grader_hash, grader_outputs)
        if not args.force_grader and grader_reuse.get("reusable"):
            gate = build_gate(session_dir)
            grader = {
                "status": "OK",
                "step": "grader-report",
                "model": args.model,
                "reused": True,
                "reuse": grader_reuse,
                "artifacts": {
                    "grading_summary": str(session_dir / "grading-summary.json"),
                    "report_html": str(session_dir / "report.html"),
                },
                "gate": gate,
            }
        else:
            grader = sentry_grader.execute_grader_report(
                evals_file=evals_file,
                session_dir=session_dir,
                model=args.model,
                verbose=args.verbose,
                update_session=True,
                write_report=True,
            )
            grader["reused"] = False
            grader["reuse"] = {"step": "grader-report", "reusable": False, "reason": "force_grader"} if args.force_grader else grader_reuse
            record_manifest_step(
                session_dir,
                "grader-report",
                status=grader.get("status", "ERROR"),
                input_hash=grader_hash,
                outputs=grader_outputs,
                extra={"model": args.model},
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
        reuse_summary=summarize_reuse_decisions(prepared, executor, grader),
        gate=gate,
        diagnostics=diagnostics,
        manifest=str(manifest_path(session_dir)),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if payload["status"] == "OK" else 1, payload


def run_delegated_ci(args, release: bool = False) -> tuple[int, dict]:
    timings = ProfileTimings()
    mode = "standard" if release and args.mode == "smoke" else args.mode
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "sentry_ci.py"),
        "--skill",
        args.skill,
        "--mode",
        mode,
        "--threshold",
        str(args.threshold),
        "--output-dir",
        args.output_dir,
        "--model",
        args.model,
        "--timeout",
        str(args.timeout),
        "--timeout-per-eval",
        str(args.timeout_per_eval),
        "--runtime",
        args.runtime,
        "--config",
        args.config,
    ]
    if args.executor_model:
        cmd.extend(["--executor-model", args.executor_model])
    if args.cases:
        cmd.extend(["--cases", args.cases])
    if args.github_output:
        cmd.append("--github-output")
    if args.verbose:
        cmd.append("--verbose")
    with timings.phase("delegated_ci"):
        completed = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=args.format == "json",
        )
    extra = {}
    if args.format == "json":
        extra["delegated_stdout"] = completed.stdout or ""
        extra["delegated_stderr"] = completed.stderr or ""
    return completed.returncode, profile_payload(
        "release" if release else "ci",
        "OK" if completed.returncode == 0 else "ERROR",
        delegated_command=cmd,
        exit_code=completed.returncode,
        timings=timings.snapshot(),
        **extra,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SkillSentry by lightweight profile")
    parser.add_argument("--profile", choices=PROFILES, default="lint")
    parser.add_argument("--skill", help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--session-dir", help="Existing session directory for debug profile")
    parser.add_argument("--reuse-session", help="Existing session directory for local profile artifact reuse")
    parser.add_argument("--cases", help="Existing evals.json/cases.cache.json path")
    parser.add_argument("--mode", choices=sorted(PIPELINES), default="smoke")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--output-dir", default="./ci-eval-results")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--executor-model", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--timeout-per-eval", type=int, default=120)
    parser.add_argument("--runtime", choices=["auto", "cli", "openclaw"], default="auto")
    parser.add_argument("--config", default=str(sentry_preflight.DEFAULT_CONFIG))
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Plan a local run without creating a session or running heavy steps")
    parser.add_argument("--force-executor", action="store_true", help="Rerun local executor even when manifest matches")
    parser.add_argument("--force-grader", action="store_true", help="Rerun local grader even when manifest matches")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.profile != "debug" and not args.skill:
        timings = ProfileTimings()
        payload = profile_payload(args.profile, "ERROR", error="--skill is required unless --profile debug", timings=timings.snapshot())
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else payload["error"])
        return 2

    if args.profile == "preflight":
        code, payload = run_profile_preflight(args)
    elif args.profile == "lint":
        code, payload = run_profile_lint(args)
    elif args.profile == "plan":
        code, payload = run_profile_plan(args)
    elif args.profile == "debug":
        code, payload = run_profile_debug(args)
    elif args.profile == "local":
        code, payload = run_profile_local(args)
    elif args.profile == "ci":
        code, payload = run_delegated_ci(args, release=False)
    elif args.profile == "release":
        code, payload = run_delegated_ci(args, release=True)
    else:
        code, payload = 2, profile_payload(args.profile, "ERROR", error=f"unknown profile: {args.profile}")

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(sentry_run_output.render_text(payload), end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
