#!/usr/bin/env python3
"""SkillSentry deterministic session state manager."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from sentry_pipeline import PIPELINES, next_step, pipeline_for_mode


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry session state manager")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create or overwrite session.json")
    init.add_argument("session_dir")
    init.add_argument("--skill", required=True)
    init.add_argument("--mode", required=True, choices=sorted(PIPELINES))
    init.add_argument("--skill-type", default="")
    init.add_argument("--hash", default="")
    init.add_argument("--runtime", default="cli")

    get = sub.add_parser("get", help="Get full session or dotted field")
    get.add_argument("session_dir")
    get.add_argument("field", nargs="?")

    set_cmd = sub.add_parser("set", help="Set dotted field")
    set_cmd.add_argument("session_dir")
    set_cmd.add_argument("field")
    set_cmd.add_argument("value")

    transition = sub.add_parser("transition", help="Move to next pipeline step")
    transition.add_argument("session_dir")
    transition.add_argument("step")
    transition.add_argument("--allow-skip", action="store_true")

    milestone = sub.add_parser("append-milestone", help="Append milestone evidence")
    milestone.add_argument("session_dir")
    milestone.add_argument("--step", required=True)
    milestone.add_argument("--message-id", default="")
    milestone.add_argument("--msg-type", default="text")
    milestone.add_argument("--validation", default="")
    milestone.add_argument("--artifact", action="append", default=[])
    milestone.add_argument("--file-read", action="append", default=[])
    milestone.add_argument("--tool-called", action="append", default=[])

    sub.add_parser("status", help="Print compact session status").add_argument("session_dir")
    return parser.parse_args()


def session_file(session_dir: str | Path) -> Path:
    return Path(session_dir).expanduser() / "session.json"


def load_session(session_dir: str | Path) -> dict:
    path = session_file(session_dir)
    if not path.exists():
        raise FileNotFoundError(f"session.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def backup(path: Path) -> None:
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))


def save_session(session_dir: str | Path, data: dict) -> None:
    path = session_file(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_path(data: dict, field: str | None):
    if not field:
        return data
    value = data
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def set_path(data: dict, field: str, value) -> None:
    current = data
    parts = field.split(".")
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def init_session(args: argparse.Namespace) -> dict:
    data = {
        "skill": args.skill,
        "mode": args.mode,
        "skill_type": args.skill_type,
        "skill_hash": args.hash,
        "runtime": args.runtime,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "last_step": "init",
        "pipeline": pipeline_for_mode(args.mode),
        "completed_steps": [],
        "milestones": {},
        "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
    }
    save_session(args.session_dir, data)
    return {"status": "OK", "session": data}


def transition(args: argparse.Namespace) -> dict:
    data = load_session(args.session_dir)
    pipeline = data.get("pipeline") or pipeline_for_mode(data.get("mode", ""))
    if args.step not in pipeline:
        return {"status": "ERROR", "error": "step_not_in_pipeline", "step": args.step, "pipeline": pipeline}

    last_step = data.get("last_step", "init")
    if last_step in pipeline:
        current_index = pipeline.index(last_step)
        expected = pipeline[current_index + 1] if current_index + 1 < len(pipeline) else None
    else:
        current_index = -1
        expected = pipeline[0] if pipeline else None

    if args.step != expected and not args.allow_skip:
        return {
            "status": "ERROR",
            "error": "illegal_transition",
            "last_step": last_step,
            "expected_next_step": expected,
            "requested_step": args.step,
        }

    completed = data.setdefault("completed_steps", [])
    if args.step not in completed:
        completed.append(args.step)
    data["last_step"] = args.step
    data["updated_at"] = now_iso()
    save_session(args.session_dir, data)
    return {"status": "OK", "last_step": args.step, "completed_steps": completed}


def append_milestone(args: argparse.Namespace) -> dict:
    data = load_session(args.session_dir)
    milestones = data.setdefault("milestones", {})
    milestones[args.step] = {
        "msg_type": args.msg_type,
        "message_id": args.message_id,
        "sent_at": now_iso(),
        "evidence": {
            "files_read": args.file_read,
            "tools_called": args.tool_called,
            "artifacts_created": args.artifact,
            "validation": args.validation,
        },
    }
    data["updated_at"] = now_iso()
    save_session(args.session_dir, data)
    return {"status": "OK", "step": args.step}


def status(args: argparse.Namespace) -> dict:
    data = load_session(args.session_dir)
    pipeline = data.get("pipeline", [])
    last_step = data.get("last_step")
    next_step_value = next_step(pipeline, last_step)
    return {
        "status": "OK",
        "skill": data.get("skill"),
        "mode": data.get("mode"),
        "last_step": last_step,
        "next_step": next_step_value,
        "completed_steps": data.get("completed_steps", []),
    }


def main() -> int:
    args = parse_args()
    try:
        if args.command == "init":
            result = init_session(args)
        elif args.command == "get":
            result = get_path(load_session(args.session_dir), args.field)
        elif args.command == "set":
            data = load_session(args.session_dir)
            set_path(data, args.field, parse_value(args.value))
            data["updated_at"] = now_iso()
            save_session(args.session_dir, data)
            result = {"status": "OK", "field": args.field, "value": get_path(data, args.field)}
        elif args.command == "transition":
            result = transition(args)
        elif args.command == "append-milestone":
            result = append_milestone(args)
        elif args.command == "status":
            result = status(args)
        else:
            result = {"status": "ERROR", "error": f"unknown_command: {args.command}"}
    except Exception as exc:
        result = {"status": "ERROR", "error": str(exc)}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not isinstance(result, dict) or result.get("status") != "ERROR" else 1


if __name__ == "__main__":
    sys.exit(main())
