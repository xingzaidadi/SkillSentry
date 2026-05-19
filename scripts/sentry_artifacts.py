#!/usr/bin/env python3
"""Shared artifact access helpers for SkillSentry session outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sentry_case_identity


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ArtifactRegistry:
    """Read session artifacts through the current compatibility contract."""

    def __init__(self, session_dir: Path, evals_file: Path | None = None):
        self.session_dir = Path(session_dir)
        self.evals_file = Path(evals_file) if evals_file is not None else self.session_dir / "evals.json"

    def load_evals(self) -> Any | None:
        try:
            return load_json(self.evals_file)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def case_identities(self) -> list[sentry_case_identity.CaseIdentity]:
        payload = self.load_evals()
        if payload is None:
            return []
        return sentry_case_identity.identities_from_payload(payload)

    def case_info(self) -> dict:
        identities = self.case_identities()
        return {
            "case_ids": sentry_case_identity.case_ids(identities),
            "fallback_case_ids": sentry_case_identity.fallback_case_ids(identities),
        }

    def case_ids(self) -> list[str]:
        return sentry_case_identity.case_ids(self.case_identities())

    def fallback_case_ids(self) -> list[str]:
        return sentry_case_identity.fallback_case_ids(self.case_identities())

    def executor_summary(self, variant: str) -> dict:
        payload = load_json(self.executor_summary_path(variant))
        if not isinstance(payload, dict):
            return {}
        return payload

    def executor_summary_path(self, variant: str) -> Path:
        filename = "executor_results.json" if variant == "with_skill" else f"executor_{variant}_results.json"
        return self.session_dir / filename

    def grading_summary_path(self) -> Path:
        return self.session_dir / "grading-summary.json"

    def report_html_path(self) -> Path:
        return self.session_dir / "report.html"

    def run_result_path(self) -> Path:
        return self.session_dir / "sentry-run-result.json"

    def manifest_path(self) -> Path:
        return self.session_dir / "manifest.json"

    def response_outputs(self, variant: str = "with_skill") -> list[Path]:
        return [
            self.session_dir / item.artifact_id / variant / "outputs" / "response.md"
            for item in self.case_identities()
        ]

    def grading_outputs(self) -> list[Path]:
        return sentry_case_identity.artifact_paths(self.session_dir, self.case_identities(), "grading.json")

    def required_outputs(self, step: str) -> list[Path]:
        if step == "executor-with":
            return [self.executor_summary_path("with_skill")] + self.response_outputs("with_skill")
        if step == "executor-without":
            return [self.executor_summary_path("without_skill")] + self.response_outputs("without_skill")
        if step == "grader-report":
            return [self.grading_summary_path(), self.report_html_path()] + self.grading_outputs()
        return []

    @staticmethod
    def missing_outputs(paths: list[Path]) -> list[Path]:
        return [path for path in paths if not path.exists()]

    def current_grading_files(self) -> list[Path]:
        identities = self.case_identities()
        if identities:
            files = sentry_case_identity.artifact_paths(self.session_dir, identities, "grading.json")
            return sorted(path for path in files if path.exists())

        files = []
        for path in self.session_dir.rglob("grading.json"):
            if "without_skill" in set(path.parts):
                continue
            files.append(path)
        return sorted(files)
