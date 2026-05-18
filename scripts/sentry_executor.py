#!/usr/bin/env python3
"""Stable SkillSentry executor wrapper.

This wrapper keeps the existing ci_executor.py runner as the implementation,
and adds a small CLI plus deterministic JSON/session contracts around it.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_state
from ci_executor import execute_all_evals


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summary_file_for_variant(session_dir: Path, variant: str) -> Path:
    if variant == "with_skill":
        return session_dir / "executor_results.json"
    return session_dir / f"executor_{variant}_results.json"


def load_summary(session_dir: Path, variant: str) -> dict:
    summary_file = summary_file_for_variant(session_dir, variant)
    if not summary_file.exists():
        return {}
    try:
        return load_json(summary_file)
    except Exception as exc:
        return {"error": f"summary_parse_failed: {exc}"}


def update_session_for_executor(session_dir: Path, variant: str, payload: dict) -> None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    session = sentry_state.load_session(session_dir)
    summary = payload.get("summary", {})
    if variant == "with_skill":
        session["executor"] = {
            "with_skill": summary,
            "success": summary.get("success", 0) if isinstance(summary, dict) else 0,
            "total": summary.get("total", 0) if isinstance(summary, dict) else 0,
        }
    elif variant == "without_skill":
        session["without_skill"] = {
            "status": "completed" if payload.get("status") == "OK" else "failed",
            "summary": summary,
        }
    else:
        session.setdefault("executor_variants", {})[variant] = payload
    session["updated_at"] = utc_now()
    sentry_state.save_session(session_dir, session)


def skip_without_skill_for_mcp(session_dir: Path) -> dict | None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return None
    session = sentry_state.load_session(session_dir)
    if session.get("skill_type") != "mcp_based":
        return None
    payload = {
        "status": "PARTIAL",
        "step": "executor-without",
        "variant": "without_skill",
        "reason": "mcp_based baseline is not executed in CI until MCP sandbox parity is available",
        "summary": {},
        "updated_at": utc_now(),
    }
    session["without_skill"] = {
        "status": "partial",
        "reason": payload["reason"],
    }
    session["updated_at"] = payload["updated_at"]
    sentry_state.save_session(session_dir, session)
    return payload


def execute_executor_step(
    *,
    evals_file: Path,
    skill_path: Path,
    session_dir: Path,
    model: str,
    timeout_per_eval: int,
    variant: str,
    verbose: bool = False,
    update_session: bool = True,
    allow_mcp_without_skip: bool = True,
) -> dict:
    """Run one executor variant and return a stable JSON payload."""
    session_dir.mkdir(parents=True, exist_ok=True)
    if not evals_file.exists():
        return {
            "status": "ERROR",
            "step": f"executor-{variant.replace('_skill', '').replace('_', '-')}",
            "variant": variant,
            "error": f"evals file not found: {evals_file}",
            "summary": {},
            "updated_at": utc_now(),
        }
    if not skill_path.exists():
        return {
            "status": "ERROR",
            "step": f"executor-{variant.replace('_skill', '').replace('_', '-')}",
            "variant": variant,
            "error": f"skill file not found: {skill_path}",
            "summary": {},
            "updated_at": utc_now(),
        }

    if variant == "without_skill" and allow_mcp_without_skip:
        skipped = skip_without_skill_for_mcp(session_dir)
        if skipped is not None:
            return skipped

    success = execute_all_evals(
        evals_file=evals_file,
        skill_path=skill_path,
        session_dir=session_dir,
        model=model,
        timeout_per_eval=timeout_per_eval,
        verbose=verbose,
        variant=variant,
    )
    summary = load_summary(session_dir, variant)
    payload = {
        "status": "OK" if success else "ERROR",
        "step": "executor-with" if variant == "with_skill" else "executor-without",
        "variant": variant,
        "summary_file": str(summary_file_for_variant(session_dir, variant)),
        "summary": summary,
        "updated_at": utc_now(),
    }
    if update_session:
        update_session_for_executor(session_dir, variant, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one SkillSentry executor variant")
    parser.add_argument("--evals", required=True, help="evals.json path")
    parser.add_argument("--skill", required=True, help="SKILL.md path")
    parser.add_argument("--session-dir", required=True, help="Session directory")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--timeout-per-eval", "--timeout", type=int, default=120)
    parser.add_argument("--variant", choices=["with_skill", "without_skill"], default="with_skill")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--no-session-update", action="store_true", help="Do not update session.json")
    parser.add_argument("--no-mcp-skip", action="store_true", help="Run without_skill even for mcp_based sessions")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = execute_executor_step(
        evals_file=Path(args.evals),
        skill_path=Path(args.skill),
        session_dir=Path(args.session_dir),
        model=args.model,
        timeout_per_eval=args.timeout_per_eval,
        variant=args.variant,
        verbose=args.verbose,
        update_session=not args.no_session_update,
        allow_mcp_without_skip=not args.no_mcp_skip,
    )
    if args.output:
        save_json(Path(args.output), payload)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload.get("summary", {})
        success = summary.get("success", 0) if isinstance(summary, dict) else 0
        total = summary.get("total", 0) if isinstance(summary, dict) else 0
        print(f"sentry executor: {payload['status']} | variant: {payload['variant']} | success: {success}/{total}")
        if payload.get("reason"):
            print(f"- {payload['reason']}")
        if payload.get("error"):
            print(f"- {payload['error']}")
    if payload["status"] in {"OK", "PARTIAL"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
