"""Prepare eval cases for a profile session."""

from __future__ import annotations

import shutil
from pathlib import Path

import sentry_case_lint
from sentry_profile_runtime import utc_now
import sentry_profile_state
import sentry_reuse_core
import sentry_state


def prepare_cases(session_dir: Path, cases_file: Path) -> dict:
    if not cases_file.exists():
        return {
            "status": "ERROR",
            "error": f"cases file not found: {cases_file}",
            "step": "prepare_cases",
            "reused": False,
            "reuse": {"step": "prepare_cases", "reusable": False, "reason": "cases_file_not_found"},
        }

    target = session_dir / "evals.json"
    cases_hash = sentry_reuse_core.file_hash(cases_file)
    reuse_state = sentry_reuse_core.prepared_cases_reuse_state(session_dir, target, cases_hash)
    reused = sentry_reuse_core.reusable_prepared_cases(session_dir, cases_file, target, cases_hash, reuse_state)
    if reused is not None:
        return reused

    if not (target.exists() and sentry_profile_state.same_path(cases_file, target)):
        shutil.copy2(cases_file, target)
    lint = sentry_case_lint.lint_cases_file(target)
    sentry_case_lint.record_case_lint_result(session_dir, lint)
    cases_total = lint.get("total", 0)
    session = sentry_state.load_session(session_dir)
    session["cases"] = {"total": cases_total, "types": {}, "reused": False}
    session["updated_at"] = utc_now()
    sentry_state.save_session(session_dir, session)
    return {
        "status": "OK",
        "cases_file": str(target),
        "source": str(cases_file),
        "cases_hash": cases_hash,
        "case_lint": lint,
        "step": "prepare_cases",
        "reused": False,
        "reuse": reuse_state,
    }
