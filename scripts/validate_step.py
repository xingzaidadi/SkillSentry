#!/usr/bin/env python3
"""Validate SkillSentry step artifacts against the shared pipeline contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sentry_pipeline import STEP_DEFINITIONS, step_definition


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def load_session(session_dir: Path) -> dict:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        raise FileNotFoundError(f"session.json not found: {session_file}")
    return json.loads(session_file.read_text(encoding="utf-8"))


def dotted_get(data: dict, field: str):
    value = data
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def has_glob(session_dir: Path, pattern: str) -> bool:
    return any(session_dir.glob(pattern))


def validate_artifact(session_dir: Path, session: dict, artifact: str) -> tuple[bool, str]:
    if artifact.startswith("session.json:"):
        field = artifact.split(":", 1)[1]
        value = dotted_get(session, field)
        if value is None or value == {}:
            return False, f"session.json.{field} is empty"
        return True, artifact

    if "*" in artifact:
        if has_glob(session_dir, artifact):
            return True, artifact
        return False, f"missing artifact glob: {artifact}"

    path = session_dir / artifact
    if path.exists():
        return True, artifact
    return False, f"missing artifact: {artifact}"


def validate(session_dir: str | Path, step: str) -> bool:
    session_dir = Path(session_dir)
    session = load_session(session_dir)

    errors: list[str] = []
    warnings: list[str] = []

    if step not in STEP_DEFINITIONS:
        errors.append(f"unknown current pipeline step: {step}")
    else:
        definition = step_definition(step)
        for artifact in definition.required_artifacts:
            ok, message = validate_artifact(session_dir, session, artifact)
            if not ok:
                if definition.can_skip and definition.step_type in {"sync", "llm_required"}:
                    warnings.append(message)
                else:
                    errors.append(message)

    pipeline = session.get("pipeline", [])
    if pipeline and step not in pipeline:
        errors.append(f"{step} is not in session pipeline: {pipeline}")

    last_step = session.get("last_step")
    completed = session.get("completed_steps", [])
    if last_step != step and step not in completed:
        warnings.append(f"{step} is not recorded as last_step or completed_steps")

    if errors:
        print(f"FAIL after {step}:")
        for error in errors:
            print(f"  {error}")
        for warning in warnings:
            print(f"  WARN: {warning}")
        return False

    if warnings:
        print(f"PASS with warnings after {step}:")
        for warning in warnings:
            print(f"  {warning}")
        return True

    print(f"PASS after {step}")
    return True


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] in {"-h", "--help"}:
        valid = ", ".join(sorted(STEP_DEFINITIONS))
        print(f"Usage: python validate_step.py <session_dir> <step>\nValid steps: {valid}")
        return 0
    if len(sys.argv) < 3:
        valid = ", ".join(sorted(STEP_DEFINITIONS))
        print(f"Usage: python validate_step.py <session_dir> <step>\nValid steps: {valid}")
        return 1
    try:
        ok = validate(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
