#!/usr/bin/env python3
"""Verify dashboard session scanning."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import dashboard


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def save_json(path: Path, payload: dict, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="skillsentry-dashboard-") as tmp:
        sessions_dir = Path(tmp) / "sessions"
        save_json(
            sessions_dir / "skill-a" / "001" / "session.json",
            {
                "skill": "bom-skill",
                "mode": "smoke",
                "last_step": "publish",
                "started_at": "2026-05-18T10:00:00",
                "verdict": {"grade": "PASS", "pass_rate": 1.0},
            },
            encoding="utf-8-sig",
        )
        save_json(
            sessions_dir / "skill-b" / "002" / "session.json",
            {
                "skill": "plain-skill",
                "mode": "quick",
                "last_step": "grader-report",
                "started_at": "2026-05-18T11:00:00",
                "verdict": {"grade": "FAIL", "pass_rate": 0.0},
            },
        )

        sessions = dashboard.scan_sessions(sessions_dir)
        assert_equal(len(sessions), 2, "dashboard scanned session count")
        skills = sorted(item["skill"] for item in sessions)
        assert_equal(skills, ["bom-skill", "plain-skill"], "dashboard scanned BOM session")

        rendered = dashboard.generate_dashboard(sessions)
        if "- Total sessions: 2" not in rendered or "- Completed (publish): 1" not in rendered:
            raise AssertionError("dashboard summary did not include expected totals")

        completed = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "dashboard.py"), "--sessions-dir", str(sessions_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert_equal(completed.returncode, 0, "dashboard.py exit code")
        if "- Total sessions: 2" not in completed.stdout:
            raise AssertionError("dashboard CLI did not include BOM session in total")

    print("dashboard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
