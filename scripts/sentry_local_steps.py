"""Reusable local profile executor and grader steps."""

from __future__ import annotations

from pathlib import Path

import sentry_artifacts
from sentry_executor import execute_executor_step
from sentry_gate import build_gate
import sentry_grader
import sentry_reuse_core


def run_executor_with_reuse(
    *,
    session_dir: Path,
    evals_file: Path,
    skill_path: Path,
    model: str,
    timeout_per_eval: int,
    force_executor: bool = False,
    verbose: bool = False,
) -> dict:
    executor_hash = sentry_reuse_core.combine_hash(
        "executor-with",
        sentry_reuse_core.file_hash(evals_file),
        sentry_reuse_core.file_hash(skill_path),
        model,
        timeout_per_eval,
    )
    executor_outputs = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).required_outputs("executor-with")
    executor_reuse = sentry_reuse_core.step_reuse_state(session_dir, "executor-with", executor_hash, executor_outputs)
    if not force_executor and executor_reuse.get("reusable"):
        return {
            "status": "OK",
            "step": "executor-with",
            "variant": "with_skill",
            "reused": True,
            "reuse": executor_reuse,
            "summary_file": str(session_dir / "executor_results.json"),
            "summary": sentry_artifacts.load_json(session_dir / "executor_results.json"),
        }

    executor = execute_executor_step(
        evals_file=evals_file,
        skill_path=skill_path,
        session_dir=session_dir,
        model=model,
        timeout_per_eval=timeout_per_eval,
        variant="with_skill",
        verbose=verbose,
        update_session=True,
    )
    executor["reused"] = False
    executor["reuse"] = {"step": "executor-with", "reusable": False, "reason": "force_executor"} if force_executor else executor_reuse
    sentry_reuse_core.record_manifest_step(
        session_dir,
        "executor-with",
        status=executor.get("status", "ERROR"),
        input_hash=executor_hash,
        outputs=executor_outputs,
        extra={"model": model, "timeout_per_eval": timeout_per_eval},
    )
    return executor


def run_grader_with_reuse(
    *,
    session_dir: Path,
    evals_file: Path,
    model: str,
    force_grader: bool = False,
    verbose: bool = False,
) -> dict:
    registry = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file)
    response_hashes = [(str(path), sentry_reuse_core.file_hash(path)) for path in registry.response_outputs("with_skill")]
    grader_hash = sentry_reuse_core.combine_hash("grader-report", sentry_reuse_core.file_hash(evals_file), response_hashes, model)
    grader_outputs = registry.required_outputs("grader-report")
    grader_reuse = sentry_reuse_core.step_reuse_state(session_dir, "grader-report", grader_hash, grader_outputs)
    if not force_grader and grader_reuse.get("reusable"):
        gate = build_gate(session_dir)
        return {
            "status": "OK",
            "step": "grader-report",
            "model": model,
            "reused": True,
            "reuse": grader_reuse,
            "artifacts": {
                "grading_summary": str(session_dir / "grading-summary.json"),
                "report_html": str(session_dir / "report.html"),
            },
            "gate": gate,
        }

    grader = sentry_grader.execute_grader_report(
        evals_file=evals_file,
        session_dir=session_dir,
        model=model,
        verbose=verbose,
        update_session=True,
        write_report=True,
    )
    grader["reused"] = False
    grader["reuse"] = {"step": "grader-report", "reusable": False, "reason": "force_grader"} if force_grader else grader_reuse
    sentry_reuse_core.record_manifest_step(
        session_dir,
        "grader-report",
        status=grader.get("status", "ERROR"),
        input_hash=grader_hash,
        outputs=grader_outputs,
        extra={"model": model},
    )
    return grader
