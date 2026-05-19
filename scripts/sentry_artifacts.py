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

    def __init__(self, session_dir: Path):
        self.session_dir = Path(session_dir)

    def load_evals(self) -> Any | None:
        try:
            return load_json(self.session_dir / "evals.json")
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
        filename = "executor_results.json" if variant == "with_skill" else f"executor_{variant}_results.json"
        payload = load_json(self.session_dir / filename)
        if not isinstance(payload, dict):
            return {}
        return payload

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
