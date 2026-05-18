#!/usr/bin/env python3
"""Stable SkillSentry publish wrapper.

The interactive publish.py entrypoint remains available. This wrapper gives
pipeline and CI callers a deterministic local publish result even when Feishu
upload credentials or an interactive upload path are unavailable.
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
sys.path.insert(0, str(SCRIPT_DIR))

from sentry_gate import build_gate
import sentry_report


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def result_payload(
    *,
    status: str,
    message: str,
    artifacts: list[str] | None = None,
    raw_error: str | None = None,
    command: list[str] | None = None,
) -> dict:
    payload = {
        "status": status,
        "step": "publish",
        "artifacts": artifacts or [],
        "message": message,
        "raw_error": raw_error,
        "updated_at": utc_now(),
    }
    if command is not None:
        payload["command"] = command
    return payload


def ensure_gate(session_dir: Path) -> dict:
    gate_file = session_dir / "gate-result.json"
    if gate_file.exists():
        return load_json(gate_file)
    gate = build_gate(session_dir)
    save_json(gate_file, gate)
    return gate


def should_write_minimal_report(report: Path) -> bool:
    return sentry_report.should_replace_generated_report(report)


def ensure_report(session_dir: Path, gate: dict) -> Path:
    return sentry_report.ensure_session_report(
        session_dir,
        gate,
        title="SkillSentry Publish Result",
        generated_by="sentry_publish.py",
        footer="Interactive publishing can still use publish.py.",
    )


def update_session(session_dir: Path, publish_payload: dict, gate: dict) -> None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    try:
        session = load_json(session_file)
    except Exception:
        return
    session["publish"] = {
        "status": publish_payload["status"],
        "message": publish_payload["message"],
        "artifacts": publish_payload.get("artifacts", []),
        "updated_at": publish_payload["updated_at"],
    }
    session.setdefault("verdict", {
        "status": gate.get("verdict"),
        "grade": gate.get("grade"),
        "authoritative_pass_rate": gate.get("authoritative_pass_rate"),
        "delta": gate.get("delta"),
        "ifr": gate.get("ifr"),
        "vetoes": gate.get("vetoes", []),
        "reasons": gate.get("decision_reasons", []),
    })
    session["updated_at"] = utc_now()
    save_json(session_file, session)


def infer_session_fields(session_dir: Path) -> tuple[str, str]:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return session_dir.parent.name, "quick"
    try:
        session = load_json(session_file)
    except Exception:
        return session_dir.parent.name, "quick"
    return session.get("skill") or session_dir.parent.name, session.get("mode") or "quick"


def run_legacy_publish(
    session_dir: Path,
    *,
    skill_name: str,
    mode: str,
    user_open_id: str,
    risk_level: str,
    skip_feishu: bool,
    skip_history: bool,
    timeout: int,
) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "publish.py"),
        "--workspace-dir",
        str(session_dir),
        "--skill-name",
        skill_name,
        "--user-open-id",
        user_open_id,
        "--mode",
        mode,
        "--risk-level",
        risk_level,
    ]
    if skip_feishu:
        cmd.append("--skip-feishu")
    if skip_history:
        cmd.append("--skip-history")

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
        return result_payload(
            status="ERROR",
            message="legacy publish.py failed before completion.",
            raw_error=str(exc),
            command=cmd,
        )

    if completed.returncode == 0:
        artifacts = [str(session_dir / "eval-report.html")]
        return result_payload(
            status="OK",
            message="legacy publish.py completed.",
            artifacts=[p for p in artifacts if Path(p).exists()],
            command=cmd,
        )
    raw = "\n".join(part for part in (completed.stderr.strip(), completed.stdout.strip()) if part)
    return result_payload(
        status="ERROR",
        message=f"legacy publish.py exited with {completed.returncode}.",
        raw_error=raw or f"exit code {completed.returncode}",
        command=cmd,
    )


def execute_publish(
    session_dir: str | Path,
    *,
    skill_name: str | None = None,
    mode: str | None = None,
    user_open_id: str | None = None,
    risk_level: str = "B",
    legacy_publish: bool = False,
    skip_feishu: bool = True,
    skip_history: bool = True,
    timeout: int = 300,
) -> dict:
    session_path = Path(session_dir).resolve()
    if not session_path.is_dir():
        return result_payload(
            status="ERROR",
            message=f"session directory not found: {session_path}",
            raw_error="missing session_dir",
        )

    inferred_skill, inferred_mode = infer_session_fields(session_path)
    resolved_skill = skill_name or inferred_skill
    resolved_mode = mode or inferred_mode

    if legacy_publish:
        if not user_open_id:
            payload = result_payload(
                status="ERROR",
                message="legacy publish requires --user-open-id.",
                raw_error="missing user_open_id",
            )
            save_json(session_path / "publish-result.json", payload)
            return payload
        payload = run_legacy_publish(
            session_path,
            skill_name=resolved_skill,
            mode=resolved_mode,
            user_open_id=user_open_id,
            risk_level=risk_level,
            skip_feishu=skip_feishu,
            skip_history=skip_history,
            timeout=timeout,
        )
        save_json(session_path / "publish-result.json", payload)
        return payload

    try:
        gate = ensure_gate(session_path)
        report = ensure_report(session_path, gate)
        artifacts = [str(report), str(session_path / "gate-result.json")]
        payload = result_payload(
            status="OK",
            message=(
                f"local publish result ready: {gate.get('verdict', 'UNKNOWN')} "
                f"/ grade {gate.get('grade', 'N/A')}. Feishu upload not attempted by this wrapper."
            ),
            artifacts=artifacts,
        )
        save_json(session_path / "publish-result.json", payload)
        update_session(session_path, payload, gate)
        report = ensure_report(session_path, gate)
        payload["artifacts"] = [str(report), str(session_path / "gate-result.json")]
        save_json(session_path / "publish-result.json", payload)
        update_session(session_path, payload, gate)
        return payload
    except Exception as exc:
        payload = result_payload(
            status="ERROR",
            message="local publish failed.",
            raw_error=str(exc),
        )
        save_json(session_path / "publish-result.json", payload)
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry stable publish wrapper")
    parser.add_argument("--session-dir", required=True, help="Session directory")
    parser.add_argument("--skill-name", default=None, help="Skill name; inferred from session.json when omitted")
    parser.add_argument("--mode", default=None, help="Mode; inferred from session.json when omitted")
    parser.add_argument("--risk-level", default="B", choices=["S", "A", "B", "C"])
    parser.add_argument("--legacy-publish", action="store_true", help="Call legacy publish.py")
    parser.add_argument("--user-open-id", default=None, help="Required only with --legacy-publish")
    parser.add_argument("--with-feishu", action="store_true", help="Allow legacy publish.py to emit Feishu upload instructions")
    parser.add_argument("--with-history", action="store_true", help="Allow legacy publish.py to update history")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args()


def emit(payload: dict, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"publish: {payload['status']} - {payload['message']}")
    if payload.get("raw_error"):
        print(payload["raw_error"])


def main() -> int:
    args = parse_args()
    payload = execute_publish(
        args.session_dir,
        skill_name=args.skill_name,
        mode=args.mode,
        user_open_id=args.user_open_id,
        risk_level=args.risk_level,
        legacy_publish=args.legacy_publish,
        skip_feishu=not args.with_feishu,
        skip_history=not args.with_history,
        timeout=args.timeout,
    )
    emit(payload, args.format)
    return 1 if payload["status"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
