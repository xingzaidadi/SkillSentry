#!/usr/bin/env python3
"""Verify the local dogfood path: local run, artifact reuse, and session root.

The default mode is deterministic and uses a fake Claude CLI, so it can run in
CI without network or account balance. Pass --real to run against a real local
skill and real Claude CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_REAL_SKILL = Path.home() / ".claude" / "skills" / "obsidian-skills" / "skills" / "obsidian-markdown" / "SKILL.md"


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fake_claude_script() -> str:
    return r'''
import json
import os
import re
import sys
from pathlib import Path

args = sys.argv[1:]
args_log = os.environ.get("SKILLSENTRY_FAKE_CLAUDE_ARGS")
if args_log:
    Path(args_log).parent.mkdir(parents=True, exist_ok=True)
    with open(args_log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")

count_log = os.environ.get("SKILLSENTRY_FAKE_CLAUDE_COUNT")
if count_log:
    Path(count_log).parent.mkdir(parents=True, exist_ok=True)
    with open(count_log, "a", encoding="utf-8") as handle:
        handle.write("hit\n")

prompt = sys.stdin.read()
if "--max-budget-usd" in args or "待评审断言" in prompt:
    match = re.search(r"## 待评审断言\s*```json\s*(.*?)\s*```", prompt, re.S)
    assertions = json.loads(match.group(1)) if match else [
        {"name": "has_wikilink", "type": "exact_match", "expected": "[[Dogfood Note]]"},
        {"name": "has_callout", "type": "exact_match", "expected": "> [!info]"},
        {"name": "has_embed", "type": "exact_match", "expected": "![[dogfood.png|300]]"},
    ]
    payload = {
        "assertions": [
            {
                "name": item.get("name", f"A{idx + 1}"),
                "type": item.get("type", "exact_match"),
                "expected": item.get("expected", ""),
                "pass": True,
                "evidence": item.get("expected", "")[:50],
            }
            for idx, item in enumerate(assertions)
        ],
        "summary": {"pass": len(assertions), "fail": 0, "total": len(assertions)},
    }
    print(json.dumps(payload, ensure_ascii=False))
else:
    print("---")
    print("title: Dogfood Note")
    print("tags:")
    print("  - dogfood")
    print("---")
    print("[[Dogfood Note]]")
    print("> [!info]")
    print("![[dogfood.png|300]]")
'''


def make_fake_claude(bin_dir: Path) -> None:
    fake = bin_dir / "fake_claude.py"
    fake.write_text(fake_claude_script(), encoding="utf-8")
    cmd = bin_dir / "claude.cmd"
    cmd.write_text(f"@echo off\r\npython \"{fake}\" %*\r\n", encoding="utf-8")
    sh = bin_dir / "claude"
    sh.write_text(f"#!/bin/sh\npython \"{fake}\" \"$@\"\n", encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)


def make_fixture(root: Path) -> tuple[Path, Path]:
    skill_dir = root / "dogfood-skill"
    skill_dir.mkdir()
    skill = skill_dir / "SKILL.md"
    skill.write_text(
        "---\nname: dogfood-skill\ndescription: Fixture skill for local dogfood verification\n---\n"
        "Return an Obsidian-flavored Markdown note with wikilinks, callouts, and embeds.",
        encoding="utf-8",
    )
    cases = root / "evals.json"
    save_json(
        cases,
        [
            {
                "id": "dogfood-note",
                "name": "Dogfood Obsidian note",
                "prompt": "Create a dogfood Obsidian note.",
                "assertions": [
                    {"name": "has_wikilink", "type": "exact_match", "expected": "[[Dogfood Note]]"},
                    {"name": "has_callout", "type": "exact_match", "expected": "> [!info]"},
                    {"name": "has_embed", "type": "exact_match", "expected": "![[dogfood.png|300]]"},
                ],
            }
        ],
    )
    return skill, cases


def make_real_cases(root: Path) -> Path:
    cases = root / "obsidian-markdown-evals.json"
    save_json(
        cases,
        [
            {
                "id": "obsidian-dogfood-note",
                "name": "Obsidian dogfood note",
                "prompt": "Create an Obsidian note. Include YAML frontmatter with title Dogfood Note, an internal wikilink to Dogfood Note, an info callout, and an image embed dogfood.png with width 300. Return only Markdown.",
                "assertions": [
                    {"name": "has_wikilink", "type": "exact_match", "expected": "[[Dogfood Note]]"},
                    {"name": "has_callout", "type": "exact_match", "expected": "> [!info]"},
                    {"name": "has_embed", "type": "exact_match", "expected": "![[dogfood.png|300]]"},
                ],
            }
        ],
    )
    return cases


def run_local(skill: Path, cases: Path, env: dict, *, reuse_session: str = "auto") -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentry_run.py"),
            "--skill",
            str(skill),
            "--profile",
            "local",
            "--cases",
            str(cases),
            "--reuse-session",
            reuse_session,
            "--timeout-per-eval",
            "180",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def fake_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def assert_first_run(payload: dict, session_root: Path, errors: list[str]) -> None:
    session_dir = Path(str(payload.get("session_dir", "")))
    if payload.get("status") != "OK":
        errors.append(f"first run status expected OK, got {payload.get('status')}")
    if not session_dir.exists():
        errors.append(f"first run session_dir missing: {session_dir}")
        return
    try:
        session_dir.relative_to(session_root)
    except ValueError:
        errors.append(f"session_dir should be under session root {session_root}, got {session_dir}")
    if session_dir == ROOT or ROOT in session_dir.parents:
        errors.append(f"session_dir should not be inside repo root, got {session_dir}")
    for name in ("evals.json", "executor_results.json", "grading-summary.json", "manifest.json", "report.html", "sentry-run-result.json"):
        if not (session_dir / name).exists():
            errors.append(f"first run missing artifact: {name}")
    gate = payload.get("gate", {})
    if gate.get("verdict") != "PASS" or gate.get("grade") != "S":
        errors.append(f"first run expected PASS/S, got {gate.get('verdict')}/{gate.get('grade')}")
    if payload.get("executor", {}).get("summary", {}).get("success", 0) < 1:
        errors.append("first run executor did not record success")
    if payload.get("executor", {}).get("reused") is True:
        errors.append("first run should not reuse executor")
    if payload.get("grader", {}).get("reused") is True:
        errors.append("first run should not reuse grader")


def assert_reuse_run(payload: dict, session_dir: Path, errors: list[str]) -> None:
    if payload.get("status") != "OK":
        errors.append(f"reuse run status expected OK, got {payload.get('status')}")
    if Path(str(payload.get("session_dir", ""))) != session_dir:
        errors.append("auto reuse should select the first run session")
    if payload.get("auto_reuse", {}).get("selected") is not True:
        errors.append("auto reuse should mark selected=true")
    if payload.get("executor", {}).get("reused") is not True:
        errors.append("auto reuse should reuse executor")
    if payload.get("grader", {}).get("reused") is not True:
        errors.append("auto reuse should reuse grader")
    if payload.get("cases", {}).get("reused") is not True:
        errors.append("auto reuse should reuse prepared cases")
    reuse_summary = payload.get("reuse_summary", {})
    if reuse_summary.get("all_reused") is not True:
        errors.append("auto reuse summary should mark all_reused=true")
    if reuse_summary.get("rerun_steps") != []:
        errors.append(f"auto reuse should have no rerun_steps, got {reuse_summary.get('rerun_steps')!r}")


def verify(real: bool, keep_artifacts: bool, skill_arg: str | None) -> tuple[bool, list[str], dict]:
    errors: list[str] = []
    root = Path(tempfile.mkdtemp(prefix="skillsentry-local-dogfood-"))
    try:
        session_root = root / "sessions"
        env = os.environ.copy()
        env["SKILLSENTRY_SESSION_ROOT"] = str(session_root)
        env["SKILLSENTRY_CI_LLM_FALLBACK"] = "claude"
        env.setdefault("SKILLSENTRY_CI_CLAUDE_MODEL", "sonnet")
        count_file = root / "fake-claude-count.txt"
        args_file = root / "fake-claude-args.txt"

        if real:
            skill = Path(skill_arg).expanduser() if skill_arg else DEFAULT_REAL_SKILL
            cases = make_real_cases(root)
            if not skill.exists():
                errors.append(f"real dogfood skill not found: {skill}")
            if not (shutil.which("claude.cmd") or shutil.which("claude")):
                errors.append("real dogfood requires Claude CLI on PATH")
        else:
            bin_dir = root / "bin"
            bin_dir.mkdir()
            make_fake_claude(bin_dir)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["ANTHROPIC_API_KEY"] = ""
            env["SKILLSENTRY_FAKE_CLAUDE_COUNT"] = str(count_file)
            env["SKILLSENTRY_FAKE_CLAUDE_ARGS"] = str(args_file)
            skill, cases = make_fixture(root)

        if not errors:
            first = run_local(skill, cases, env)
            if first.returncode != 0:
                errors.append(f"first local run exited {first.returncode}: {first.stderr.strip()} {first.stdout.strip()}")
                first_payload = {}
            else:
                first_payload = json.loads(first.stdout)
                assert_first_run(first_payload, session_root, errors)

            session_dir = Path(str(first_payload.get("session_dir", "")))
            before = fake_count(count_file) if not real else None
            second = run_local(skill, cases, env)
            if second.returncode != 0:
                errors.append(f"reuse local run exited {second.returncode}: {second.stderr.strip()} {second.stdout.strip()}")
                second_payload = {}
            else:
                second_payload = json.loads(second.stdout)
                assert_reuse_run(second_payload, session_dir, errors)
            if not real:
                after = fake_count(count_file)
                if before is not None and after != before:
                    errors.append(f"reuse run should not call fake Claude again: before={before}, after={after}")
                args_text = args_file.read_text(encoding="utf-8") if args_file.exists() else ""
                if "--model sonnet" not in args_text:
                    errors.append("dogfood executor should pass normalized --model sonnet to Claude CLI")
                if "claude-sonnet-4-6" in args_text:
                    errors.append("dogfood executor should not pass unsupported default model to Claude CLI")
        else:
            first_payload = {}
            second_payload = {}
            session_dir = Path()

        details = {
            "mode": "real" if real else "fake",
            "session_root": str(session_root),
            "session_dir": str(session_dir) if str(session_dir) else None,
            "first_status": first_payload.get("status") if isinstance(first_payload, dict) else None,
            "reuse_selected": second_payload.get("auto_reuse", {}).get("selected") if isinstance(second_payload, dict) else None,
            "reuse_all_reused": second_payload.get("reuse_summary", {}).get("all_reused") if isinstance(second_payload, dict) else None,
            "report_html": str(session_dir / "report.html") if session_dir else None,
        }
        return not errors, errors, details
    finally:
        if keep_artifacts:
            print(f"kept dogfood workspace: {root}", file=sys.stderr)
        else:
            shutil.rmtree(root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify SkillSentry local dogfood path")
    parser.add_argument("--real", action="store_true", help="Use real Claude CLI and a real installed skill")
    parser.add_argument("--skill", help="SKILL.md path for --real mode")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep temporary dogfood workspace")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors, details = verify(args.real, args.keep_artifacts, args.skill)
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors, "details": details}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"local dogfood: {payload['status']}")
        print(f"mode: {details.get('mode')}")
        print(f"session: {details.get('session_dir')}")
        print(f"report: {details.get('report_html')}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
