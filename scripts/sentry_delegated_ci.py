"""Delegate ci and release profiles to sentry_ci.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sentry_profile_runtime import ProfileTimings, profile_payload


def build_delegated_command(args, script_dir: Path, release: bool = False) -> list[str]:
    mode = "standard" if release and args.mode == "smoke" else args.mode
    cmd = [
        sys.executable,
        str(script_dir / "sentry_ci.py"),
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
    return cmd


def run_delegated_ci(args, script_dir: Path, release: bool = False) -> tuple[int, dict]:
    timings = ProfileTimings()
    cmd = build_delegated_command(args, script_dir, release=release)
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
