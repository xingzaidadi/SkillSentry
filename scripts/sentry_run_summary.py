#!/usr/bin/env python3
"""Shared read-only summary helpers for SkillSentry run artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sentry_artifacts


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _milliseconds(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    duration = _number(value, default=-1.0)
    if duration < 0:
        return None
    return round(duration, 1)


@dataclass(frozen=True)
class RunSummary:
    path: Path
    kind: str
    timings: dict
    meta: dict

    @property
    def session_dir(self) -> Path | None:
        return resolve_session_dir(self.path, self.meta)


def summarize_reuse_decisions(reuse_decisions: list[dict]) -> dict:
    steps = [dict(item) for item in reuse_decisions if isinstance(item, dict)]
    miss_reasons: dict[str, int] = {}
    for item in steps:
        if item.get("reused"):
            continue
        reason = item.get("reason") or "unknown"
        miss_reasons[str(reason)] = miss_reasons.get(str(reason), 0) + 1
    return {
        "steps": steps,
        "reused_steps": [item.get("step") for item in steps if item.get("reused")],
        "rerun_steps": [item.get("step") for item in steps if not item.get("reused")],
        "miss_reasons": miss_reasons,
        "all_reused": bool(steps) and all(item.get("reused") for item in steps),
    }


def from_eval_result(path: Path, payload: dict | None = None) -> RunSummary:
    data = sentry_artifacts.load_json(path) if payload is None else payload
    meta = {
        "source": str(path),
        "kind": "eval_result",
        "verdict": data.get("verdict"),
        "status": data.get("status"),
        "artifacts": _as_dict(data.get("artifacts")),
    }
    return RunSummary(path=path, kind="eval_result", timings=_as_dict(data.get("timings")), meta=meta)


def from_session(path: Path) -> RunSummary:
    session_file = path / "session.json" if path.is_dir() else path
    session = sentry_artifacts.load_json(session_file)
    timing = _as_dict(session.get("ci_timing"))
    steps = _as_list(session.get("ci_step_timings"))
    phases = _as_list(session.get("ci_phase_timings"))
    run_result = session_file.parent / "sentry-run-result.json"
    if not timing and not steps and not phases and run_result.exists():
        return from_sentry_run_result(run_result)
    timings = {
        "total_ms": timing.get("total_ms"),
        "steps": steps,
        "phases": phases,
        "failed_steps": timing.get("failed_steps", []),
    }
    meta = {
        "source": str(session_file),
        "kind": "session",
        "skill": session.get("skill"),
        "mode": session.get("mode"),
        "last_step": session.get("last_step"),
    }
    return RunSummary(path=session_file, kind="session", timings=timings, meta=meta)


def from_sentry_run_result(path: Path, payload: dict | None = None) -> RunSummary:
    data = sentry_artifacts.load_json(path) if payload is None else payload
    timings = _as_dict(data.get("timings"))
    phases_ms = _as_dict(timings.get("phases_ms"))
    phases = [
        {"phase": str(name), "status": "OK", "duration_ms": _milliseconds(duration)}
        for name, duration in phases_ms.items()
        if _milliseconds(duration) is not None
    ]
    reuse_summary = _as_dict(data.get("reuse_summary"))
    reuse_decisions = _as_list(reuse_summary.get("steps"))
    for key in ("executor", "grader"):
        section = _as_dict(data.get(key))
        if not section:
            continue
        reuse = _as_dict(section.get("reuse"))
        if any(item.get("step") == (section.get("step") or key) for item in reuse_decisions):
            continue
        reuse_decisions.append(
            {
                "step": section.get("step") or key,
                "reused": section.get("reused"),
                "reason": reuse.get("reason"),
                "reusable": reuse.get("reusable"),
            }
        )
    if not reuse_summary and reuse_decisions:
        reuse_summary = summarize_reuse_decisions(reuse_decisions)
    meta = {
        "source": str(path),
        "kind": "sentry_run_result",
        "profile": data.get("profile"),
        "status": data.get("status"),
        "session_dir": data.get("session_dir"),
        "reuse_summary": reuse_summary,
        "reuse_decisions": reuse_decisions,
    }
    return RunSummary(
        path=path,
        kind="sentry_run_result",
        timings={
            "total_ms": timings.get("total_ms"),
            "steps": [],
            "phases": phases,
            "failed_steps": [],
        },
        meta=meta,
    )


def load(path: Path) -> RunSummary:
    if path.is_dir() or path.name == "session.json":
        return from_session(path)
    payload = sentry_artifacts.load_json(path)
    if "profile" in payload and "timings" in payload:
        return from_sentry_run_result(path, payload)
    if "timings" in payload:
        return from_eval_result(path, payload)
    if "ci_step_timings" in payload or "ci_timing" in payload:
        return from_session(path)
    raise ValueError(f"unsupported timing input: {path}")


def resolve_session_dir(input_path: Path, meta: dict) -> Path | None:
    if meta.get("kind") == "session":
        source = Path(str(meta.get("source") or ""))
        if source.name == "session.json":
            return source.parent
        return source if source.is_dir() else None
    if meta.get("kind") == "sentry_run_result":
        session_dir = meta.get("session_dir")
        if isinstance(session_dir, str) and session_dir:
            raw_candidate = Path(session_dir)
            candidates = [raw_candidate]
            if not raw_candidate.is_absolute():
                candidates.extend([input_path.parent / raw_candidate, Path.cwd() / raw_candidate])
            for candidate in candidates:
                if (candidate / "session.json").exists():
                    return candidate
        if (input_path.parent / "session.json").exists():
            return input_path.parent

    artifacts = _as_dict(meta.get("artifacts"))
    session_report = artifacts.get("session_report_html")
    if isinstance(session_report, str) and session_report:
        report_path = Path(session_report)
        candidates = [report_path]
        if not report_path.is_absolute():
            candidates.append(input_path.parent / report_path)
            candidates.append(Path.cwd() / report_path)
        for candidate in candidates:
            if candidate.exists() and candidate.name == "report.html":
                session_dir = candidate.parent
                if (session_dir / "session.json").exists():
                    return session_dir

    if (input_path.parent / "session.json").exists():
        return input_path.parent
    return None
