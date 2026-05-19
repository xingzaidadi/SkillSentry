"""CLI parsing and profile dispatch for sentry_run.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sentry_debug_profile
import sentry_delegated_ci
import sentry_light_profiles
import sentry_local_profile
import sentry_preflight
from sentry_pipeline import PIPELINES
from sentry_profile_runtime import ProfileTimings, profile_payload
import sentry_run_output


SCRIPT_DIR = Path(__file__).resolve().parent
LIGHT_PROFILES = {"preflight", "lint", "debug", "plan"}
HEAVY_PROFILES = {"local", "ci", "release"}
PROFILES = sorted(LIGHT_PROFILES | HEAVY_PROFILES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SkillSentry by profile: light local checks, reusable local runs, or delegated CI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python scripts/sentry_run.py --skill <skill> --profile preflight
  python scripts/sentry_run.py --skill <skill> --profile plan --mode quick
  python scripts/sentry_run.py --skill <skill> --profile local --cases evals.json --dry-run
  python scripts/sentry_run.py --skill <skill> --profile local --cases evals.json --reuse-session auto
  python scripts/sentry_run.py --skill <skill> --profile ci --mode quick

Profile weight:
  preflight/lint/plan/debug avoid executor/grader.
  local runs with_skill executor + grader/report, and can reuse matching artifacts.
  ci/release delegate to sentry_ci.py for the full release contract.
""",
    )
    parser.add_argument("--profile", choices=PROFILES, default="lint", help="Profile to run; default lint is deterministic and light")
    parser.add_argument("--skill", help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--session-dir", help="Existing session directory for debug profile")
    parser.add_argument("--reuse-session", help="Existing session directory, or 'auto', for local profile artifact reuse")
    parser.add_argument("--cases", help="Existing evals.json/cases.cache.json path")
    parser.add_argument("--mode", choices=sorted(PIPELINES), default="smoke", help="Pipeline mode for plan/ci/release profiles")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--output-dir", default="./ci-eval-results")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--executor-model", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--timeout-per-eval", type=int, default=120)
    parser.add_argument("--runtime", choices=["auto", "cli", "openclaw"], default="auto")
    parser.add_argument("--config", default=str(sentry_preflight.DEFAULT_CONFIG))
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Render the plan/reuse forecast without starting executor/grader/CI heavy steps")
    parser.add_argument("--force-executor", action="store_true", help="Rerun local executor even when manifest matches")
    parser.add_argument("--force-grader", action="store_true", help="Rerun local grader even when manifest matches")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def run_profile(args) -> tuple[int, dict]:
    if args.profile == "preflight":
        return sentry_light_profiles.run_profile_preflight(args)
    if args.profile == "lint":
        return sentry_light_profiles.run_profile_lint(args)
    if args.profile == "plan":
        return sentry_light_profiles.run_profile_plan(args)
    if args.profile == "debug":
        return sentry_debug_profile.run_profile_debug(args)
    if args.profile == "local":
        return sentry_local_profile.run_profile_local(args)
    if args.profile == "ci":
        return sentry_delegated_ci.run_delegated_ci(args, SCRIPT_DIR, release=False)
    if args.profile == "release":
        return sentry_delegated_ci.run_delegated_ci(args, SCRIPT_DIR, release=True)
    return 2, profile_payload(args.profile, "ERROR", error=f"unknown profile: {args.profile}")


def main() -> int:
    args = parse_args()
    if args.profile != "debug" and not args.skill:
        timings = ProfileTimings()
        payload = profile_payload(args.profile, "ERROR", error="--skill is required unless --profile debug", timings=timings.snapshot())
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else payload["error"])
        return 2

    code, payload = run_profile(args)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(sentry_run_output.render_text(payload), end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
