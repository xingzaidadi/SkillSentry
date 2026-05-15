#!/usr/bin/env python3
"""SkillSentry deterministic preflight.

This script does the mechanical setup work that should not require LLM
reasoning: locate SKILL.md, read frontmatter, compute hash, infer skill_type,
detect runtime/config/case cache, and return a stable JSON object.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
INPUTS_ROOT = SKILL_ROOT / "inputs"
DEFAULT_CONFIG = SKILL_ROOT / "config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry preflight")
    parser.add_argument("--skill", required=True, help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--mode", default="quick", help="Evaluation mode")
    parser.add_argument(
        "--runtime",
        choices=["auto", "cli", "openclaw"],
        default="auto",
        help="Runtime environment",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Config JSON path")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_skill(skill_arg: str) -> Path | None:
    p = Path(skill_arg).expanduser()
    if p.is_file() and p.name == "SKILL.md":
        return p.resolve()
    if p.is_dir() and (p / "SKILL.md").exists():
        return (p / "SKILL.md").resolve()

    search_paths = [
        Path.home() / ".claude" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".config" / "opencode" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".openclaw" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".openclaw" / "workspace" / "skills" / skill_arg / "SKILL.md",
    ]
    for candidate in search_paths:
        if candidate.exists():
            return candidate.resolve()
    return None


def parse_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}

    data: dict[str, object] = {}
    current_key: str | None = None
    for raw_line in match.group(1).splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith(" ") and current_key:
            previous = data.get(current_key, "")
            data[current_key] = f"{previous}\n{line.strip()}".strip()
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
        current_key = key
    return data


def compute_hash(skill_md: Path) -> str:
    return hashlib.md5(skill_md.read_bytes()).hexdigest()


def detect_runtime(runtime_arg: str, skill_path: Path) -> str:
    if runtime_arg != "auto":
        return runtime_arg
    if os.environ.get("OPENCLAW_RUNTIME") or ".openclaw" in str(skill_path).lower():
        return "openclaw"
    return "cli"


def detect_skill_type(content: str) -> str:
    if re.search(r"[a-z][a-z0-9]*_[a-z0-9_]+\(", content) or re.search(
        r"\b(mcporter|MCP\s*(Server|Tool)|mcp__)\b", content, re.IGNORECASE
    ):
        return "mcp_based"
    if re.search(r"\b(bash|python|exec|subprocess|shell|powershell)\b", content, re.IGNORECASE):
        return "code_execution"
    return "text_generation"


def detect_mcp_servers(content: str) -> list[str]:
    servers: set[str] = set()
    for match in re.finditer(r"mcp__([a-zA-Z0-9_-]+)__", content):
        servers.add(match.group(1))
    for match in re.finditer(r"\b([a-zA-Z0-9_-]+)\s+MCP\s+Server\b", content):
        servers.add(match.group(1))
    return sorted(servers)


def config_status(config_path: Path) -> dict:
    if not config_path.exists():
        return {"exists": False, "feishu_configured": False, "path": str(config_path)}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "exists": True,
            "feishu_configured": False,
            "path": str(config_path),
            "error": f"invalid_json: {exc}",
        }

    feishu = data.get("feishu") if isinstance(data, dict) else None
    bitable = data.get("bitable") if isinstance(data, dict) else None
    if isinstance(feishu, dict):
        keys = ("app_id", "app_secret", "app_token")
        configured = all(bool(str(feishu.get(k, "")).strip()) for k in keys)
        schema = "feishu"
    elif isinstance(bitable, dict):
        configured = bool(str(bitable.get("app_token", "")).strip())
        schema = "bitable"
    else:
        keys = ("app_id", "app_secret", "app_token", "table_id")
        configured = all(bool(str(data.get(k, "")).strip()) for k in keys)
        schema = "legacy_flat"
    tables = {}
    if isinstance(data.get("tables"), dict):
        tables = data["tables"]
    elif isinstance(feishu, dict) and isinstance(feishu.get("tables"), dict):
        tables = feishu["tables"]
    elif isinstance(bitable, dict) and isinstance(bitable.get("tables"), dict):
        tables = bitable["tables"]

    return {
        "exists": True,
        "feishu_configured": configured,
        "path": str(config_path),
        "schema": schema,
        "tables": sorted(tables.keys()),
    }


def runtime_tools_status() -> dict:
    claude_cmd = shutil.which("claude.cmd") or shutil.which("claude")
    fallback = os.environ.get("SKILLSENTRY_CI_LLM_FALLBACK", "").lower()
    return {
        "claude_cli": {
            "available": bool(claude_cmd),
            "path": claude_cmd,
        },
        "anthropic_sdk": {
            "available": importlib.util.find_spec("anthropic") is not None,
        },
        "anthropic_api_key": {
            "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        },
        "llm_fallback": {
            "mode": fallback or None,
            "claude_enabled": fallback == "claude",
        },
    }


def cache_status(skill_name: str, skill_hash: str) -> dict:
    inputs_dir = INPUTS_ROOT / skill_name
    candidates = [
        inputs_dir / "cases.cache.json",
        inputs_dir / "evals.json",
    ]
    if inputs_dir.exists():
        candidates.extend(sorted(inputs_dir.glob("*.cases.md")))

    existing = [p for p in candidates if p.exists()]
    hash_matched = False
    cache_hash = None
    cache_file = inputs_dir / "cases.cache.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            cache_hash = data.get("skill_hash") or data.get("hash")
            hash_matched = cache_hash == skill_hash
        except json.JSONDecodeError:
            cache_hash = "invalid_json"

    return {
        "inputs_dir": str(inputs_dir),
        "exists": inputs_dir.exists(),
        "has_cached_cases": bool(existing),
        "cached_files": [p.name for p in existing],
        "cached_cases_hash": cache_hash,
        "hash_matched": hash_matched,
    }


def workspace_dir(runtime: str, skill_name: str) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    if runtime == "openclaw":
        base = Path.home() / ".openclaw" / "data" / "skill-eval" / "sessions"
    else:
        base = Path.home() / ".claude" / "data" / "skill-eval" / "sessions"
    return base / skill_name / f"{today}_NNN"


def build_result(args: argparse.Namespace) -> tuple[int, dict]:
    skill_path = find_skill(args.skill)
    if not skill_path:
        return 2, {
            "status": "ERROR",
            "error": "skill_not_found",
            "searched": args.skill,
        }

    content = read_text(skill_path)
    frontmatter = parse_frontmatter(content)
    skill_name = str(frontmatter.get("name") or skill_path.parent.name)
    skill_hash = compute_hash(skill_path)
    runtime = detect_runtime(args.runtime, skill_path)
    skill_type = detect_skill_type(content)

    return 0, {
        "status": "OK",
        "skill_name": skill_name,
        "skill_dir_name": skill_path.parent.name,
        "skill_path": str(skill_path),
        "skill_hash": skill_hash,
        "skill_hash_short": skill_hash[:8],
        "skill_type": skill_type,
        "mode": args.mode,
        "runtime": runtime,
        "workspace_dir_template": str(workspace_dir(runtime, skill_name)),
        "frontmatter": {
            "name": frontmatter.get("name"),
            "version": frontmatter.get("version"),
            "has_description": bool(frontmatter.get("description")),
        },
        "mcp_servers": detect_mcp_servers(content),
        "config": config_status(Path(args.config).expanduser()),
        "cases_cache": cache_status(skill_path.parent.name, skill_hash),
        "runtime_tools": runtime_tools_status(),
    }


def print_text(result: dict) -> None:
    print(f"status: {result.get('status')}")
    if result.get("status") != "OK":
        print(f"error: {result.get('error')}")
        return
    print(f"skill: {result['skill_name']} ({result['skill_path']})")
    print(f"type: {result['skill_type']} | runtime: {result['runtime']} | mode: {result['mode']}")
    print(f"hash: {result['skill_hash_short']}")
    print(f"cached_cases: {result['cases_cache']['has_cached_cases']}")
    print(f"feishu_configured: {result['config']['feishu_configured']}")
    print(f"claude_cli: {result['runtime_tools']['claude_cli']['available']}")


def main() -> int:
    args = parse_args()
    code, result = build_result(args)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)
    return code


if __name__ == "__main__":
    sys.exit(main())
