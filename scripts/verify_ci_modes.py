#!/usr/bin/env python3
"""Verify CI orchestration contracts for every supported mode.

This is a deterministic smoke for the orchestrator itself. It stubs only the
LLM/tool-use heavy steps and lets the real state, sync, comparator, analyzer,
gate, and publish code run so mode coverage stays cheap and stable.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import sentry_ci
import sentry_state
from sentry_pipeline import pipeline_for_mode


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


FIXTURE_CASES = [
    {
        "id": "eval-1",
        "type": "happy_path",
        "name": "fixture pass",
        "prompt": "请输出 OK",
        "assertions": [
            {"name": "contains OK", "type": "exact_match", "expected": "OK", "rule_ref": "fixture"}
        ],
    }
]


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_session(root: Path, mode: str) -> Path:
    session_dir = root / mode
    session_dir.mkdir(parents=True)
    sentry_state.save_session(
        session_dir,
        {
            "skill": "ci-mode-fixture",
            "mode": mode,
            "skill_type": "text_generation",
            "skill_hash": "fixture",
            "runtime": "ci",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "last_step": "init",
            "pipeline": pipeline_for_mode(mode),
            "completed_steps": [],
            "milestones": {},
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
            "ci": True,
        },
    )
    return session_dir


def write_evals(session_dir: Path) -> None:
    save_json(session_dir / "evals.json", FIXTURE_CASES)
    sentry_ci.record_case_feasibility(session_dir, FIXTURE_CASES)
    sentry_ci.merge_session(session_dir, {"cases": {"total": len(FIXTURE_CASES), "types": {}, "reused": False}})


def fake_static(session_dir: Path, skill_path: Path, args) -> bool:
    sentry_ci.merge_session(
        session_dir,
        {
            "lint": {"L1": "pass", "L2": "pass", "L3": 0, "P0": 0, "P1": 0, "P2": 0, "issues": []},
            "trigger": {"tp": 5, "tn": 5, "confidence": "high", "issues": []},
        },
    )
    save_json(session_dir / "trigger_eval.json", {"tp": 5, "tn": 5})
    return True


def fake_cases(session_dir: Path, skill_path: Path, args, existing_cases: Path | None = None) -> bool:
    if existing_cases:
        return sentry_ci.prepare_existing_cases(session_dir, existing_cases)
    write_evals(session_dir)
    return True


def write_executor_outputs(session_dir: Path, variant: str) -> dict:
    eval_dir = session_dir / "eval-1" / variant / "outputs"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "response.md").write_text("OK\n", encoding="utf-8")
    (eval_dir / "transcript.md").write_text("fixture transcript\n", encoding="utf-8")
    return {"total": 1, "success": 1, "failed": 0, "results": [{"eval_id": "eval-1", "status": "success"}]}


def fake_executor_with(session_dir: Path, skill_path: Path, args) -> bool:
    if not (session_dir / "evals.json").exists():
        return False
    summary = write_executor_outputs(session_dir, "with_skill")
    save_json(session_dir / "executor_results.json", summary)
    sentry_ci.merge_session(session_dir, {"executor": {"with_skill": summary, "success": 1, "total": 1}})
    return True


def fake_executor_without(session_dir: Path, skill_path: Path, args) -> bool:
    if not (session_dir / "evals.json").exists():
        return False
    summary = write_executor_outputs(session_dir, "without_skill")
    save_json(session_dir / "executor_without_skill_results.json", summary)
    sentry_ci.merge_session(session_dir, {"without_skill": {"status": "completed", "summary": summary}})
    return True


def fake_grader_report(session_dir: Path, skill_path: Path, args) -> bool:
    grading = {
        "eval_id": "eval-1",
        "runs": {
            "run-1": {
                "pass": True,
                "assertions": [
                    {
                        "id": "contains OK",
                        "type": "exact_match",
                        "expect": "OK",
                        "pass": True,
                        "evidence": "fixture",
                    }
                ],
            }
        },
        "summary": {
            "pass": 1,
            "fail": 0,
            "total": 1,
            "precision_breakdown": {"exact_match": {"pass": 1, "total": 1}},
            "authoritative_pass_rate": 1.0,
        },
    }
    save_json(session_dir / "eval-1" / "grading.json", grading)
    gate = sentry_ci.build_gate(session_dir)
    save_json(session_dir / "grading-summary.json", {"status": "fixture", "verdict": gate.get("verdict")})
    sentry_ci.write_minimal_report(session_dir, gate)
    sentry_ci.merge_session(session_dir, {"grader_report": {"status": "completed"}})
    return True


def patch_heavy_steps():
    originals = {
        "run_static": sentry_ci.run_static,
        "run_cases": sentry_ci.run_cases,
        "run_executor_with": sentry_ci.run_executor_with,
        "run_executor_without": sentry_ci.run_executor_without,
        "run_grader_report": sentry_ci.run_grader_report,
    }
    sentry_ci.run_static = fake_static
    sentry_ci.run_cases = fake_cases
    sentry_ci.run_executor_with = fake_executor_with
    sentry_ci.run_executor_without = fake_executor_without
    sentry_ci.run_grader_report = fake_grader_report
    return originals


def restore_heavy_steps(originals: dict) -> None:
    for name, func in originals.items():
        setattr(sentry_ci, name, func)


def verify_mode(mode: str, root: Path, skill_path: Path, cases_file: Path) -> dict:
    session_dir = make_session(root, mode)
    args = SimpleNamespace(
        mode=mode,
        model="fixture",
        executor_model="fixture",
        timeout_per_eval=1,
        verbose=False,
    )
    if mode == "regression":
        ok = sentry_ci.prepare_existing_cases(session_dir, cases_file)
        if not ok:
            return {"mode": mode, "status": "FAIL", "error": "prepare_existing_cases failed"}

    originals = patch_heavy_steps()
    try:
        for step in pipeline_for_mode(mode):
            ok = sentry_ci.run_step(step, session_dir, skill_path, args)
            if not ok:
                return {"mode": mode, "status": "FAIL", "error": f"step failed: {step}"}
            transition = sentry_state.transition(SimpleNamespace(session_dir=str(session_dir), step=step, allow_skip=False))
            if transition.get("status") != "OK":
                return {"mode": mode, "status": "FAIL", "error": f"transition failed: {transition}"}
    finally:
        restore_heavy_steps(originals)

    session = sentry_state.load_session(session_dir)
    expected = pipeline_for_mode(mode)
    missing = [step for step in expected if step not in session.get("completed_steps", [])]
    required_files = ["evals.json", "grading-summary.json", "report.html", "publish-result.json"]
    if "gate" in expected:
        required_files.append("gate-result.json")
    missing_files = [name for name in required_files if not (session_dir / name).exists()]
    if missing or missing_files or session.get("last_step") != expected[-1]:
        return {
            "mode": mode,
            "status": "FAIL",
            "missing_steps": missing,
            "missing_files": missing_files,
            "last_step": session.get("last_step"),
        }
    return {
        "mode": mode,
        "status": "PASS",
        "last_step": session.get("last_step"),
        "completed_steps": session.get("completed_steps", []),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify sentry_ci orchestration for every mode")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    modes = ["smoke", "quick", "regression", "standard", "full"]
    with tempfile.TemporaryDirectory(prefix="skillsentry-ci-modes-") as tmp:
        root = Path(tmp)
        skill_dir = root / "fixture-skill"
        skill_dir.mkdir()
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(
            "---\nname: ci-mode-fixture\ndescription: fixture\n---\n# Fixture Skill\n",
            encoding="utf-8",
        )
        cases_file = root / "evals.json"
        save_json(cases_file, FIXTURE_CASES)

        results = [verify_mode(mode, root, skill_path, cases_file) for mode in modes]

    failures = [item for item in results if item["status"] != "PASS"]
    if args.format == "json":
        print(json.dumps({"status": "PASS" if not failures else "FAIL", "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"ci modes: {len(results)} checked, {len(failures)} failed")
        for item in results:
            print(f"{item['status']} {item['mode']} -> {item.get('last_step', item.get('error'))}")
            for key in ("missing_steps", "missing_files"):
                if item.get(key):
                    print(f"  {key}: {item[key]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
