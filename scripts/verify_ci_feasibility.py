#!/usr/bin/env python3
"""Verify deterministic CI case feasibility warnings."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import sentry_state
from sentry_ci import inspect_case_feasibility, record_case_feasibility


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def load_session(session_dir: Path) -> dict:
    return json.loads((session_dir / "session.json").read_text(encoding="utf-8"))


def main() -> int:
    missing_cases = [
        {
            "id": "eval-missing",
            "prompt": r"请读取 C:\SkillSentryMissingFixture\not-there.docx 后生成代码",
        }
    ]
    warnings = inspect_case_feasibility(missing_cases)
    assert_equal(len(warnings), 1, "missing local path warning count")
    assert_equal(warnings[0]["case_id"], "eval-missing", "warning case id")
    assert_equal(warnings[0]["type"], "missing_local_path", "warning type")

    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-") as tmp:
        session_dir = Path(tmp) / "session"
        session_dir.mkdir()
        sentry_state.save_session(session_dir, {"skill": "fixture", "case_warnings": [{"stale": True}]})

        record_case_feasibility(session_dir, missing_cases)
        session = load_session(session_dir)
        assert_equal(len(session["case_warnings"]), 1, "recorded warning count")

        existing_path = session_dir / "exists.docx"
        existing_path.write_text("fixture", encoding="utf-8")
        clean_cases = [{"id": "eval-clean", "prompt": f"请读取 {existing_path} 后说明处理方式"}]
        assert_equal(inspect_case_feasibility(clean_cases), [], "clean case warnings")

        record_case_feasibility(session_dir, clean_cases)
        session = load_session(session_dir)
        assert_equal(session["case_warnings"], [], "clean cases clear stale warnings")

    print("ci feasibility: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
