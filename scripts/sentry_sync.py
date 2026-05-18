#!/usr/bin/env python3
"""Stable SkillSentry sync wrapper.

This script gives the pipeline a deterministic JSON-facing sync contract while
leaving the legacy Feishu implementation in sync_cases.py untouched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG = SKILL_ROOT / "config.json"

STEP_ALIASES = {
    "pull": "sync-pull",
    "sync-pull": "sync-pull",
    "push-cases": "sync-push-cases",
    "push_cases": "sync-push-cases",
    "sync-push-cases": "sync-push-cases",
    "push-results": "sync-push-results",
    "push_results": "sync-push-results",
    "push-run": "sync-push-results",
    "sync-push-results": "sync-push-results",
}

SESSION_KEYS = {
    "sync-pull": "pull",
    "sync-push-cases": "push_cases",
    "sync-push-results": "push_results",
}

LEGACY_COMMANDS = {
    "sync-pull": "pull",
    "sync-push-cases": "push-cases",
    "sync-push-results": "push-run",
}


def normalize_step(step: str) -> str:
    try:
        return STEP_ALIASES[step]
    except KeyError as exc:
        raise ValueError(f"unknown sync step: {step}") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def result_payload(
    *,
    status: str,
    step: str,
    message: str,
    artifacts: list[str] | None = None,
    raw_error: str | None = None,
    command: list[str] | None = None,
    legacy_returncode: int | None = None,
) -> dict:
    payload = {
        "status": status,
        "step": step,
        "artifacts": artifacts or [],
        "message": message,
        "raw_error": raw_error,
        "updated_at": utc_now(),
    }
    if command is not None:
        payload["command"] = command
    if legacy_returncode is not None:
        payload["legacy_returncode"] = legacy_returncode
    return payload


def config_status(config: str | None) -> tuple[bool, Path, str | None]:
    path = Path(config).expanduser() if config else DEFAULT_CONFIG
    if not path.exists():
        return False, path, "config file not found"
    try:
        data = load_json(path)
    except Exception as exc:  # pragma: no cover - defensive, exercised by CLI.
        return False, path, f"config file is not valid JSON: {exc}"

    feishu = data.get("feishu") if isinstance(data, dict) else None
    required = {"app_id", "app_secret", "app_token"}
    if not isinstance(feishu, dict) or not required.issubset(feishu):
        return False, path, "config.feishu is missing required app fields"
    return True, path, None


def infer_skill_from_session(session_dir: Path | None) -> str | None:
    if not session_dir:
        return None
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return None
    try:
        session = load_json(session_file)
    except Exception:
        return None
    return session.get("skill")


def expected_artifacts(step: str, skill: str | None, session_dir: Path | None) -> list[str]:
    artifacts: list[str] = []
    if step == "sync-pull" and skill:
        inputs = SKILL_ROOT / "inputs" / skill
        for name in ("cases.cache.json", "evals.json"):
            candidate = inputs / name
            if candidate.exists():
                artifacts.append(str(candidate))
    if session_dir:
        session_file = session_dir / "session.json"
        if session_file.exists():
            artifacts.append(str(session_file))
    return artifacts


def write_session_sync(session_dir: Path | None, step: str, payload: dict) -> None:
    if not session_dir:
        return
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    try:
        session = load_json(session_file)
    except Exception:
        return
    sync = session.setdefault("sync", {})
    sync[SESSION_KEYS[step]] = {
        "status": payload["status"],
        "message": payload["message"],
        "artifacts": payload.get("artifacts", []),
        "updated_at": payload["updated_at"],
    }
    session["updated_at"] = utc_now()
    session_file.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_sync_step(
    step: str,
    *,
    skill: str | None = None,
    session_dir: str | Path | None = None,
    config: str | None = None,
    timeout: int = 300,
    run_legacy: bool = True,
) -> dict:
    normalized = normalize_step(step)
    session_path = Path(session_dir).resolve() if session_dir else None
    resolved_skill = skill or infer_skill_from_session(session_path)

    config_ok, config_path, config_error = config_status(config)
    if not config_ok:
        payload = result_payload(
            status="skipped_no_config",
            step=normalized,
            message=f"{normalized} skipped: {config_error} ({config_path})",
            artifacts=expected_artifacts(normalized, resolved_skill, session_path),
        )
        write_session_sync(session_path, normalized, payload)
        return payload

    if not run_legacy:
        payload = result_payload(
            status="OK",
            step=normalized,
            message=f"{normalized} preflight OK; legacy sync execution not requested.",
            artifacts=expected_artifacts(normalized, resolved_skill, session_path),
        )
        write_session_sync(session_path, normalized, payload)
        return payload

    legacy = LEGACY_COMMANDS[normalized]
    cmd = [sys.executable, str(SCRIPT_DIR / "sync_cases.py"), legacy]
    if normalized in {"sync-pull", "sync-push-cases"}:
        if not resolved_skill:
            payload = result_payload(
                status="ERROR",
                step=normalized,
                message=f"{normalized} requires --skill or session.json skill.",
                raw_error="missing skill",
            )
            write_session_sync(session_path, normalized, payload)
            return payload
        cmd.extend(["--skill", resolved_skill])
    if normalized in {"sync-push-cases", "sync-push-results"} and session_path:
        cmd.extend(["--session-dir", str(session_path)])
    if normalized == "sync-push-results":
        if not session_path:
            payload = result_payload(
                status="ERROR",
                step=normalized,
                message="sync-push-results requires --session-dir.",
                raw_error="missing session_dir",
            )
            write_session_sync(session_path, normalized, payload)
            return payload
    cmd.extend(["--config", str(config_path)])

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except Exception as exc:
        payload = result_payload(
            status="ERROR",
            step=normalized,
            message=f"{normalized} failed before legacy sync completed.",
            raw_error=str(exc),
            command=cmd,
        )
        write_session_sync(session_path, normalized, payload)
        return payload

    if completed.returncode == 0:
        payload = result_payload(
            status="OK",
            step=normalized,
            message=f"{normalized} completed via sync_cases.py {legacy}.",
            artifacts=expected_artifacts(normalized, resolved_skill, session_path),
            command=cmd,
            legacy_returncode=completed.returncode,
        )
    else:
        raw = "\n".join(part for part in (completed.stderr.strip(), completed.stdout.strip()) if part)
        payload = result_payload(
            status="ERROR",
            step=normalized,
            message=f"{normalized} failed via sync_cases.py {legacy}.",
            raw_error=raw or f"exit code {completed.returncode}",
            command=cmd,
            legacy_returncode=completed.returncode,
        )

    write_session_sync(session_path, normalized, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry stable sync wrapper")
    parser.add_argument("step", choices=sorted(STEP_ALIASES), help="sync step or legacy sync command")
    parser.add_argument("--skill", default=None, help="Skill name; inferred from session.json when possible")
    parser.add_argument("--session-dir", default=None, help="Session directory for state updates and push steps")
    parser.add_argument("--config", default=None, help="Feishu config path; defaults to SkillSentry/config.json")
    parser.add_argument("--timeout", type=int, default=300, help="Legacy sync timeout in seconds")
    parser.add_argument("--preflight-only", action="store_true", help="Check config and emit JSON without calling sync_cases.py")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args()


def emit(payload: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"{payload['step']}: {payload['status']} - {payload['message']}")
    if payload.get("raw_error"):
        print(payload["raw_error"])


def main() -> int:
    args = parse_args()
    payload = execute_sync_step(
        args.step,
        skill=args.skill,
        session_dir=args.session_dir,
        config=args.config,
        timeout=args.timeout,
        run_legacy=not args.preflight_only,
    )
    emit(payload, args.format)
    return 1 if payload["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
