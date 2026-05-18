#!/usr/bin/env python3
"""Shared helpers for local artifact reuse diagnostics."""

from __future__ import annotations


REUSE_REASON_HINTS = {
    "matched": "Reuse matched; the step was skipped.",
    "missing_prepared_cases": "Prepared cases were unavailable; rerun creates evals.json and case lint state.",
    "cases_hash_changed": "Cases changed; executor and grader reuse will usually miss until artifacts are regenerated.",
    "case_lint_missing": "Case lint state is missing; rerun lint/local to refresh prepared cases.",
    "case_lint_version_changed": "Case lint version changed; rerun lint/local to refresh prepared cases.",
    "missing_manifest_step": "Manifest has no record for this step; run local once to seed reusable artifacts.",
    "manifest_load_error": "Manifest could not be read; rerun local to regenerate the manifest.",
    "manifest_status_not_ok": "Manifest recorded a non-OK step; inspect the previous failure before expecting reuse.",
    "input_hash_changed": "Inputs changed; compare cases, skill hash, model, timeout, and response artifacts.",
    "missing_outputs": "Required outputs are missing; inspect the missing_outputs sample before rerunning all steps.",
    "force_executor": "--force-executor requested an executor rerun.",
    "force_grader": "--force-grader requested a grader rerun.",
    "cases_file_not_found": "The requested cases file does not exist.",
}


def hint_for_reason(reason) -> str | None:
    return REUSE_REASON_HINTS.get(str(reason))
