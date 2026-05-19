#!/usr/bin/env python3
"""Profile-based SkillSentry runner.

This is the lightweight user-facing composer. It does not replace sentry_ci.py:
CI/release profiles delegate to sentry_ci.py, while daily profiles compose the
small tools directly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_artifacts
import sentry_case_prepare
import sentry_debug_profile
import sentry_delegated_ci
import sentry_light_profiles
import sentry_local_profile
from sentry_profile_runtime import save_json as profile_save_json, utc_now
import sentry_profile_state
import sentry_reuse_core
import sentry_run_cli
import sentry_run_plan


LIGHT_PROFILES = sentry_run_cli.LIGHT_PROFILES
HEAVY_PROFILES = sentry_run_cli.HEAVY_PROFILES
PROFILES = sentry_run_cli.PROFILES


def save_json(path: Path, payload: dict) -> None:
    profile_save_json(path, payload)


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
    return sentry_light_profiles.run_preflight(args)


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
    return sentry_light_profiles.run_profile_preflight(args)


def run_profile_lint(args) -> tuple[int, dict]:
    return sentry_light_profiles.run_profile_lint(args)


def run_profile_plan(args) -> tuple[int, dict]:
    return sentry_light_profiles.run_profile_plan(args)


def run_profile_debug(args) -> tuple[int, dict]:
    return sentry_debug_profile.run_profile_debug(args)


def run_profile_local(args) -> tuple[int, dict]:
    return sentry_local_profile.run_profile_local(args)


def run_delegated_ci(args, release: bool = False) -> tuple[int, dict]:
    return sentry_delegated_ci.run_delegated_ci(args, SCRIPT_DIR, release=release)


def parse_args():
    return sentry_run_cli.parse_args()


def main() -> int:
    return sentry_run_cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
