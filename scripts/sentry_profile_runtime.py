"""Shared runtime helpers for SkillSentry profile commands."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileTimings:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.phases: dict[str, float] = {}

    @contextmanager
    def phase(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = round((time.perf_counter() - started) * 1000, 1)

    def snapshot(self) -> dict:
        return {
            "total_ms": round((time.perf_counter() - self.started) * 1000, 1),
            "phases_ms": dict(self.phases),
        }


def profile_payload(profile: str, status: str, **extra) -> dict:
    payload = {
        "status": status,
        "profile": profile,
        "updated_at": utc_now(),
    }
    payload.update(extra)
    return payload


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
