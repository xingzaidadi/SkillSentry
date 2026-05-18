#!/usr/bin/env python3
"""Verify CI preflight is captured as session and diagnostics evidence."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sentry_ci
import sentry_preflight
import sentry_state
from sentry_diagnostics import collect_diagnostics, render_markdown


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def make_skill(root: Path) -> Path:
    skill_dir = root / "fixture-skill"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: fixture-skill\n"
        "description: Fixture skill for preflight verification.\n"
        "---\n"
        "# Fixture Skill\n\n"
        "Use this skill to answer concise text-generation prompts.\n",
        encoding="utf-8",
    )
    return skill_path


def verify() -> tuple[bool, list[str]]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-preflight-") as tmp:
        root = Path(tmp)
        skill_path = make_skill(root)
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps({"feishu": {"app_id": "id", "app_secret": "secret", "app_token": "token"}}, ensure_ascii=False)
            + "\n",
            encoding="utf-8-sig",
        )
        old_inputs_root = sentry_preflight.INPUTS_ROOT
        sentry_preflight.INPUTS_ROOT = root / "inputs"
        try:
            cache_dir = sentry_preflight.INPUTS_ROOT / skill_path.parent.name
            cache_dir.mkdir(parents=True, exist_ok=True)
            args = SimpleNamespace(
                skill=str(skill_path),
                mode="regression",
                runtime="auto",
                config=str(config_path),
            )

            code, preflight = sentry_ci.run_preflight(args)
            cache_file = cache_dir / "cases.cache.json"
            cache_file.write_text(
                json.dumps({"skill_hash": preflight.get("skill_hash"), "evals": []}, ensure_ascii=False) + "\n",
                encoding="utf-8-sig",
            )
            code, preflight = sentry_ci.run_preflight(args)
        finally:
            sentry_preflight.INPUTS_ROOT = old_inputs_root
        if code != 0:
            errors.append(f"run_preflight returned {code}: {preflight}")
            return False, errors
        if preflight.get("skill_path") != str(skill_path.resolve()):
            errors.append("preflight.skill_path did not resolve to fixture SKILL.md")
        if preflight.get("skill_type") != "text_generation":
            errors.append(f"preflight.skill_type expected text_generation, got {preflight.get('skill_type')!r}")
        if "runtime_tools" not in preflight:
            errors.append("preflight.runtime_tools missing")
        if preflight.get("config", {}).get("feishu_configured") is not True:
            errors.append("preflight should read UTF-8 BOM config.json")
        if preflight.get("cases_cache", {}).get("hash_matched") is not True:
            errors.append("preflight should read UTF-8 BOM cases.cache.json")

        session_dir = root / "session"
        session_dir.mkdir()
        sentry_state.save_session(
            session_dir,
            {
                "skill": preflight["skill_dir_name"],
                "mode": args.mode,
                "skill_type": preflight["skill_type"],
                "skill_hash": preflight["skill_hash"],
                "runtime": "ci",
                "preflight": preflight,
                "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
                "case_warnings": [],
            },
        )
        diagnostics = collect_diagnostics(session_dir)
        if diagnostics.get("preflight", {}).get("status") != "OK":
            errors.append("diagnostics.preflight.status expected OK")
        if "claude_cli_available" not in diagnostics.get("preflight", {}):
            errors.append("diagnostics.preflight.claude_cli_available missing")
        markdown = render_markdown(diagnostics)
        for marker in ("Execution Diagnostics", "Preflight", "text_generation"):
            if marker not in markdown:
                errors.append(f"diagnostics markdown missing {marker!r}")

        bad_args = SimpleNamespace(skill=str(root / "missing" / "SKILL.md"), mode="smoke", runtime="auto", config=str(config_path))
        bad_code, bad_preflight = sentry_ci.run_preflight(bad_args)
        if bad_code == 0 or bad_preflight.get("error") != "skill_not_found":
            errors.append(f"missing skill preflight should fail with skill_not_found, got {bad_code}: {bad_preflight}")

    return not errors, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_ci preflight capture")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, errors = verify()
    payload = {"status": "PASS" if ok else "FAIL", "errors": errors}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ci preflight: {payload['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
