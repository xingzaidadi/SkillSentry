#!/usr/bin/env python3
"""Shared case identity helpers for SkillSentry artifacts.

This module centralizes the current compatibility rule:
- case.id is the artifact/eval id when present.
- cases without id use eval-N artifact directories.
- case_id without id remains a logical id, not an artifact directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sentry_case_lint


@dataclass(frozen=True)
class CaseIdentity:
    index: int
    eval_id: str
    artifact_id: str
    logical_id: str | None = None
    display_name: str | None = None
    uses_fallback_id: bool = False


def identities_from_payload(payload: Any) -> list[CaseIdentity]:
    identities: list[CaseIdentity] = []
    seen_artifact_ids: set[str] = set()
    for idx, case in enumerate(sentry_case_lint.extract_cases(payload), 1):
        if not isinstance(case, dict):
            continue
        raw_id = case.get("id")
        logical_id = str(case.get("case_id")) if case.get("case_id") else None
        if raw_id:
            eval_id = str(raw_id)
            uses_fallback = False
        else:
            eval_id = f"eval-{idx}"
            uses_fallback = True
        if eval_id in seen_artifact_ids:
            continue
        seen_artifact_ids.add(eval_id)
        display_name = str(case.get("name")) if case.get("name") else None
        identities.append(
            CaseIdentity(
                index=idx,
                eval_id=eval_id,
                artifact_id=eval_id,
                logical_id=logical_id,
                display_name=display_name,
                uses_fallback_id=uses_fallback,
            )
        )
    return identities


def case_ids(identities: list[CaseIdentity]) -> list[str]:
    return [item.artifact_id for item in identities]


def fallback_case_ids(identities: list[CaseIdentity]) -> list[str]:
    return [
        item.logical_id
        for item in identities
        if item.uses_fallback_id and item.logical_id
    ]


def artifact_paths(session_dir: Path, identities: list[CaseIdentity], filename: str) -> list[Path]:
    return [session_dir / item.artifact_id / filename for item in identities]
