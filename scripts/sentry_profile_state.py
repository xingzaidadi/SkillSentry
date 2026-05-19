#!/usr/bin/env python3
"""Session and profile state helpers for sentry_run."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import sentry_state


def session_root() -> Path:
    configured = os.environ.get("SKILLSENTRY_SESSION_ROOT")
    if configured and configured.strip():
        return Path(configured).expanduser()
    return Path.home() / ".claude" / "data" / "skill-eval" / "sessions"


def init_session(skill_name: str, skill_hash: str, skill_type: str, mode: str, preflight: dict, runtime: str, updated_at: str) -> Path:
    root = session_root()
    base = root / skill_name
    base.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    existing_numbers = []
    for item in base.iterdir():
        if not item.is_dir():
            continue
        prefix = f"{today}_"
        if not item.name.startswith(prefix):
            continue
        suffix = item.name[len(prefix):]
        if suffix.isdigit():
            existing_numbers.append(int(suffix))
    next_num = max(existing_numbers, default=0) + 1
    session_name = f"{today}_{next_num:03d}"
    session_dir = base / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    sentry_state.save_session(
        session_dir,
        {
            "skill": skill_name,
            "mode": mode,
            "skill_type": skill_type,
            "skill_hash": skill_hash,
            "runtime": runtime,
            "preflight": preflight,
            "mcp_backend": "unavailable",
            "started_at": updated_at,
            "updated_at": updated_at,
            "last_step": "init",
            "completed_steps": [],
            "milestones": {},
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
            "profile_run": True,
        },
    )
    return session_dir


def resolve_local_session(args, preflight: dict, updated_at: str) -> Path:
    if args.reuse_session:
        session_dir = Path(args.reuse_session).expanduser()
        if not session_dir.exists():
            raise FileNotFoundError(f"reuse session not found: {session_dir}")
        return session_dir
    return init_session(
        preflight["skill_dir_name"],
        preflight["skill_hash"],
        preflight["skill_type"],
        args.mode,
        preflight,
        preflight.get("runtime", args.runtime),
        updated_at,
    )


def refresh_session_metadata(session_dir: Path, args, preflight: dict, updated_at: str) -> None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    session = sentry_state.load_session(session_dir)
    session.update(
        {
            "skill": preflight["skill_dir_name"],
            "mode": args.mode,
            "skill_type": preflight["skill_type"],
            "skill_hash": preflight["skill_hash"],
            "runtime": preflight.get("runtime", args.runtime),
            "preflight": preflight,
            "profile_run": True,
            "updated_at": updated_at,
        }
    )
    sentry_state.save_session(session_dir, session)


def cached_cases_from_preflight(preflight: dict) -> Path | None:
    cache = preflight.get("cases_cache", {}) if isinstance(preflight, dict) else {}
    inputs_dir = Path(cache.get("inputs_dir", "")).expanduser()
    for name in ("cases.cache.json", "evals.json"):
        candidate = inputs_dir / name
        if candidate.exists():
            return candidate
    return None


def resolve_cases(args, preflight: dict) -> Path | None:
    if args.cases:
        return Path(args.cases).expanduser()
    return cached_cases_from_preflight(preflight)


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False
