#!/usr/bin/env python3
"""Profile-based SkillSentry runner.

This is the lightweight user-facing composer. It does not replace sentry_ci.py:
CI/release profiles delegate to sentry_ci.py, while daily profiles compose the
small tools directly.
"""

from __future__ import annotations

import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from sentry_run_compat import *  # noqa: F403


if __name__ == "__main__":
    raise SystemExit(main())
