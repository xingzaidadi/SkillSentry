#!/usr/bin/env python3
"""Profile-based SkillSentry runner.

This is the lightweight user-facing composer. It does not replace sentry_ci.py:
CI/release profiles delegate to sentry_ci.py, while daily profiles compose the
small tools directly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_case_lint
import sentry_artifacts
import sentry_diagnostics
import sentry_grader
import sentry_preflight
import sentry_report
import sentry_reuse
import sentry_state
from sentry_executor import execute_executor_step
from sentry_gate import build_gate
from sentry_pipeline import PIPELINES, plan as pipeline_plan


LIGHT_PROFILES = {"preflight", "lint", "debug", "plan"}
HEAVY_PROFILES = {"local", "ci", "release"}
PROFILES = sorted(LIGHT_PROFILES | HEAVY_PROFILES)

PROFILE_STEPS: dict[str, list[dict]] = {
    "preflight": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
    ],
    "lint": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
        {"step": "session", "tool": "sentry-state", "step_type": "deterministic"},
        {"step": "prepare_cases", "tool": "sentry-case-lint", "step_type": "deterministic"},
    ],
    "debug": [
        {"step": "gate", "tool": "sentry-gate", "step_type": "deterministic"},
        {"step": "diagnostics", "tool": "sentry-diagnostics", "step_type": "deterministic"},
        {"step": "report", "tool": "sentry-report", "step_type": "deterministic"},
    ],
    "local": [
        {"step": "preflight", "tool": "sentry-preflight", "step_type": "deterministic"},
        {"step": "session", "tool": "sentry-state", "step_type": "deterministic"},
        {"step": "prepare_cases", "tool": "sentry-case-lint", "step_type": "deterministic"},
        {"step": "executor-with", "tool": "sentry-executor", "step_type": "llm_required"},
        {"step": "grader-report", "tool": "sentry-grader", "step_type": "llm_required"},
        {"step": "diagnostics", "tool": "sentry-diagnostics", "step_type": "deterministic"},
    ],
}


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


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def session_root() -> Path:
    root = Path(os.environ.get("SKILLSENTRY_SESSION_ROOT", "")).expanduser()
    if str(root):
        return root
    return Path.home() / ".claude" / "skills" / "SkillSentry" / "sessions"


def manifest_path(session_dir: Path) -> Path:
    return sentry_artifacts.ArtifactRegistry(session_dir).manifest_path()


def load_manifest(session_dir: Path) -> dict:
    path = manifest_path(session_dir)
    if not path.exists():
        return {"version": 1, "steps": {}}
    try:
        data = load_json(path)
    except Exception as exc:
        return {"version": 1, "steps": {}, "load_error": str(exc)}
    if not isinstance(data, dict):
        return {"version": 1, "steps": {}, "load_error": "manifest is not a JSON object"}
    data.setdefault("version", 1)
    if not isinstance(data.get("steps"), dict):
        data["steps"] = {}
        data["load_error"] = "manifest steps is not a JSON object"
    return data


def save_manifest(session_dir: Path, manifest: dict) -> None:
    manifest.pop("load_error", None)
    manifest["updated_at"] = utc_now()
    save_json(manifest_path(session_dir), manifest)


def step_reuse_state(session_dir: Path, step: str, input_hash: str, required: list[Path]) -> dict:
    manifest = load_manifest(session_dir)
    step_data = manifest.get("steps", {}).get(step, {})
    state = {
        "step": step,
        "reusable": False,
        "reason": "missing_manifest_step",
        "missing_outputs": [],
    }
    if not isinstance(step_data, dict):
        state["reason"] = "manifest_step_invalid"
        state["recorded_type"] = type(step_data).__name__
        return state
    if not step_data:
        if manifest.get("load_error"):
            state["reason"] = "manifest_load_error"
            state["manifest_error"] = manifest.get("load_error")
        return state
    recorded_status = step_data.get("status")
    if recorded_status != "OK":
        state["reason"] = "manifest_status_not_ok"
        state["recorded_status"] = recorded_status
        return state
    if step_data.get("input_hash") != input_hash:
        state["reason"] = "input_hash_changed"
        state["recorded_input_hash"] = step_data.get("input_hash")
        state["expected_input_hash"] = input_hash
        return state
    missing = [str(path) for path in sentry_artifacts.ArtifactRegistry.missing_outputs(required)]
    if missing:
        state["reason"] = "missing_outputs"
        state["missing_outputs"] = missing
        return state
    state["reusable"] = True
    state["reason"] = "matched"
    return state


def step_reusable(session_dir: Path, step: str, input_hash: str, required: list[Path]) -> bool:
    return bool(step_reuse_state(session_dir, step, input_hash, required).get("reusable"))


def record_manifest_step(session_dir: Path, step: str, *, status: str, input_hash: str, outputs: list[Path], extra: dict | None = None) -> dict:
    manifest = load_manifest(session_dir)
    payload = {
        "status": status,
        "input_hash": input_hash,
        "outputs": [str(path) for path in unique_paths(outputs)],
        "updated_at": utc_now(),
    }
    if extra:
        payload.update(extra)
    manifest.setdefault("steps", {})[step] = payload
    save_manifest(session_dir, manifest)
    return payload


def summarize_reuse_decisions(*sections: dict) -> dict:
    steps = []
    miss_reasons: dict[str, int] = {}
    hints = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        reuse = section.get("reuse")
        if not isinstance(reuse, dict):
            reuse = {}
        step = section.get("step") or reuse.get("step")
        if not step:
            continue
        reused = bool(section.get("reused"))
        reason = reuse.get("reason") or ("matched" if reused else "unknown")
        entry = {
            "step": step,
            "reused": reused,
            "reusable": reuse.get("reusable"),
            "reason": reason,
        }
        missing_outputs = reuse.get("missing_outputs")
        if isinstance(missing_outputs, list) and missing_outputs:
            entry["missing_outputs_count"] = len(missing_outputs)
            entry["missing_outputs_sample"] = missing_outputs[:5]
        for key in (
            "recorded_input_hash",
            "expected_input_hash",
            "prepared_cases_hash",
            "expected_cases_hash",
            "recorded_status",
            "recorded_type",
        ):
            if reuse.get(key) is not None:
                entry[key] = reuse.get(key)
        steps.append(entry)
        if not reused:
            hint = sentry_reuse.hint_for_reason(reason)
            if hint and hint not in hints:
                hints.append(hint)
            miss_reasons[reason] = miss_reasons.get(reason, 0) + 1

    return {
        "steps": steps,
        "reused_steps": [item["step"] for item in steps if item.get("reused")],
        "rerun_steps": [item["step"] for item in steps if not item.get("reused")],
        "miss_reasons": miss_reasons,
        "all_reused": bool(steps) and all(item.get("reused") for item in steps),
        "hints": hints,
    }


def unique_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    unique = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def combine_hash(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        if part is None:
            h.update(b"<none>")
        elif isinstance(part, (dict, list)):
            h.update(json.dumps(part, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        else:
            h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def profile_payload(profile: str, status: str, **extra) -> dict:
    payload = {
        "status": status,
        "profile": profile,
        "updated_at": utc_now(),
    }
    payload.update(extra)
    return payload


def enrich_plan_step(step: dict) -> dict:
    item = dict(step)
    step_type = str(item.get("step_type") or "")
    requires_llm = step_type == "llm_required"
    requires_network = step_type == "sync"
    item["heavy"] = bool(requires_llm)
    item["requires_llm"] = requires_llm
    item["requires_network"] = requires_network
    return item


def summarize_plan_steps(steps: list[dict]) -> dict:
    heavy_steps = [item.get("step") for item in steps if item.get("heavy")]
    network_steps = [item.get("step") for item in steps if item.get("requires_network")]
    llm_steps = [item.get("step") for item in steps if item.get("requires_llm")]
    return {
        "heavy_steps": heavy_steps,
        "llm_steps": llm_steps,
        "network_steps": network_steps,
        "requires_llm": bool(llm_steps),
        "requires_network": bool(network_steps),
    }


def build_mode_plan(mode: str) -> dict:
    raw = pipeline_plan(mode)
    steps = [enrich_plan_step(item) for item in raw.get("steps", []) if isinstance(item, dict)]
    payload = {
        "kind": "pipeline",
        "mode": mode,
        "pipeline": raw.get("pipeline", []),
        "steps": steps,
    }
    payload.update(summarize_plan_steps(steps))
    return payload


def build_profile_plan(profile: str) -> dict:
    steps = [enrich_plan_step(item) for item in PROFILE_STEPS.get(profile, [])]
    payload = {
        "kind": "profile",
        "profile": profile,
        "pipeline": [item.get("step") for item in steps],
        "steps": steps,
    }
    payload.update(summarize_plan_steps(steps))
    return payload


def local_dry_run_reuse(session_dir: Path, cases_file: Path, args, preflight: dict) -> dict:
    evals_file = session_dir / "evals.json"
    cases_hash = file_hash(cases_file)
    decisions = []
    try:
        prepared = prepared_cases_reuse_state(session_dir, evals_file, cases_hash)
    except (FileNotFoundError, json.JSONDecodeError):
        prepared = {"step": "prepare_cases", "reusable": False, "reason": "missing_prepared_cases"}
    decisions.append(prepared)

    if not evals_file.exists():
        return {
            "session_dir": str(session_dir),
            "steps": decisions,
            "summary": summarize_reuse_decisions({"step": "prepare_cases", "reused": False, "reuse": prepared}),
        }

    model = args.executor_model or args.model
    skill_path = Path(preflight["skill_path"])
    executor_hash = combine_hash(
        "executor-with",
        file_hash(evals_file),
        file_hash(skill_path),
        model,
        args.timeout_per_eval,
    )
    registry = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file)
    executor_reuse = step_reuse_state(session_dir, "executor-with", executor_hash, registry.required_outputs("executor-with"))
    if args.force_executor:
        executor_reuse = {"step": "executor-with", "reusable": False, "reason": "force_executor"}
    decisions.append(executor_reuse)

    response_hashes = [(str(path), file_hash(path)) for path in expected_response_outputs(evals_file, session_dir)]
    grader_hash = combine_hash("grader-report", file_hash(evals_file), response_hashes, args.model)
    grader_reuse = step_reuse_state(session_dir, "grader-report", grader_hash, registry.required_outputs("grader-report"))
    if args.force_grader:
        grader_reuse = {"step": "grader-report", "reusable": False, "reason": "force_grader"}
    decisions.append(grader_reuse)

    sections = [
        {"step": item.get("step"), "reused": item.get("reusable"), "reuse": item}
        for item in decisions
    ]
    return {
        "session_dir": str(session_dir),
        "steps": decisions,
        "summary": summarize_reuse_decisions(*sections),
    }


def find_auto_reuse_session(args, preflight: dict, cases_file: Path) -> dict:
    base = session_root() / str(preflight.get("skill_dir_name") or "")
    result = {
        "mode": "auto",
        "selected": False,
        "session_dir": None,
        "candidates": [],
    }
    if not base.exists():
        result["reason"] = "session_root_missing"
        return result

    candidates = sorted((item for item in base.iterdir() if item.is_dir()), key=lambda item: item.name, reverse=True)
    for candidate in candidates[:20]:
        if not (candidate / "session.json").exists():
            continue
        try:
            forecast = local_dry_run_reuse(candidate, cases_file, args, preflight)
        except Exception as exc:
            result["candidates"].append({
                "session_dir": str(candidate),
                "reusable": False,
                "reason": f"error:{type(exc).__name__}",
            })
            continue
        summary = forecast.get("summary", {}) if isinstance(forecast, dict) else {}
        reusable = bool(summary.get("all_reused"))
        candidate_result = {
            "session_dir": str(candidate),
            "reusable": reusable,
            "rerun_steps": summary.get("rerun_steps", []),
            "miss_reasons": summary.get("miss_reasons", {}),
        }
        result["candidates"].append(candidate_result)
        if reusable:
            result["selected"] = True
            result["session_dir"] = str(candidate)
            result["reason"] = "matched"
            return result

    result["reason"] = "no_reusable_session"
    return result


def run_preflight(args) -> tuple[int, dict]:
    preflight_args = argparse.Namespace(
        skill=args.skill,
        mode=args.mode,
        runtime=args.runtime,
        config=args.config,
        format="json",
    )
    return sentry_preflight.build_result(preflight_args)


def init_session(skill_name: str, skill_hash: str, skill_type: str, mode: str, preflight: dict, runtime: str) -> Path:
    root = session_root()
    base = root / skill_name
    base.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    existing_numbers = []
    for item in base.iterdir():
        if not item.is_dir():
            continue
        prefix = f"{today}_"
        if not item.name.startswith(prefix):
            continue
        suffix = item.name[len(prefix):]
        if suffix.isdigit():
            existing_numbers.append(int(suffix))
    next_num = max(existing_numbers, default=0) + 1
    session_name = f"{today}_{next_num:03d}"
    session_dir = base / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    sentry_state.save_session(
        session_dir,
        {
            "skill": skill_name,
            "mode": mode,
            "skill_type": skill_type,
            "skill_hash": skill_hash,
            "runtime": runtime,
            "preflight": preflight,
            "mcp_backend": "unavailable",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "last_step": "init",
            "completed_steps": [],
            "milestones": {},
            "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
            "profile_run": True,
        },
    )
    return session_dir


def resolve_local_session(args, preflight: dict) -> Path:
    if args.reuse_session:
        session_dir = Path(args.reuse_session).expanduser()
        if not session_dir.exists():
            raise FileNotFoundError(f"reuse session not found: {session_dir}")
        return session_dir
    return init_session(
        preflight["skill_dir_name"],
        preflight["skill_hash"],
        preflight["skill_type"],
        args.mode,
        preflight,
        preflight.get("runtime", args.runtime),
    )


def refresh_session_metadata(session_dir: Path, args, preflight: dict) -> None:
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return
    session = sentry_state.load_session(session_dir)
    session.update(
        {
            "skill": preflight["skill_dir_name"],
            "mode": args.mode,
            "skill_type": preflight["skill_type"],
            "skill_hash": preflight["skill_hash"],
            "runtime": preflight.get("runtime", args.runtime),
            "preflight": preflight,
            "profile_run": True,
            "updated_at": utc_now(),
        }
    )
    sentry_state.save_session(session_dir, session)


def cached_cases_from_preflight(preflight: dict) -> Path | None:
    cache = preflight.get("cases_cache", {}) if isinstance(preflight, dict) else {}
    inputs_dir = Path(cache.get("inputs_dir", "")).expanduser()
    for name in ("cases.cache.json", "evals.json"):
        candidate = inputs_dir / name
        if candidate.exists():
            return candidate
    return None


def resolve_cases(args, preflight: dict) -> Path | None:
    if args.cases:
        return Path(args.cases).expanduser()
    return cached_cases_from_preflight(preflight)


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def prepared_cases_reuse_state(session_dir: Path, target: Path, cases_hash: str | None) -> dict:
    state = {
        "step": "prepare_cases",
        "reusable": False,
        "reason": "missing_cases_hash",
    }
    if cases_hash is None:
        return state
    if not target.exists():
        state["reason"] = "missing_prepared_cases"
        return state
    target_hash = file_hash(target)
    if target_hash != cases_hash:
        state["reason"] = "cases_hash_changed"
        state["prepared_cases_hash"] = target_hash
        state["expected_cases_hash"] = cases_hash
        return state
    session = sentry_state.load_session(session_dir)
    case_lint = session.get("case_lint")
    if not isinstance(case_lint, dict):
        state["reason"] = "case_lint_missing"
        return state
    if case_lint.get("version") != sentry_case_lint.LINT_VERSION:
        state["reason"] = "case_lint_version_changed"
        state["recorded_version"] = case_lint.get("version")
        state["expected_version"] = sentry_case_lint.LINT_VERSION
        return state
    state["reusable"] = True
    state["reason"] = "matched"
    return state


def reusable_prepared_cases(session_dir: Path, cases_file: Path, target: Path, cases_hash: str | None, reuse_state: dict) -> dict | None:
    if not reuse_state.get("reusable"):
        return None
    session = sentry_state.load_session(session_dir)
    case_lint = session.get("case_lint")
    case_lint = dict(case_lint)
    case_lint["cases_file"] = str(target)
    case_lint["warnings"] = session.get("case_warnings", [])
    cases_meta = session.get("cases") if isinstance(session.get("cases"), dict) else {}
    cases_meta = dict(cases_meta)
    cases_meta["reused"] = True
    session["cases"] = cases_meta
    session["updated_at"] = utc_now()
    sentry_state.save_session(session_dir, session)
    return {
        "status": "OK",
        "cases_file": str(target),
        "source": str(cases_file),
        "cases_hash": cases_hash,
        "case_lint": case_lint,
        "step": "prepare_cases",
        "reused": True,
        "reuse": reuse_state,
    }


def prepare_cases(session_dir: Path, cases_file: Path) -> dict:
    if not cases_file.exists():
        return {
            "status": "ERROR",
            "error": f"cases file not found: {cases_file}",
            "step": "prepare_cases",
            "reused": False,
            "reuse": {"step": "prepare_cases", "reusable": False, "reason": "cases_file_not_found"},
        }
    target = session_dir / "evals.json"
    cases_hash = file_hash(cases_file)
    reuse_state = prepared_cases_reuse_state(session_dir, target, cases_hash)
    reused = reusable_prepared_cases(session_dir, cases_file, target, cases_hash, reuse_state)
    if reused is not None:
        return reused

    if not (target.exists() and same_path(cases_file, target)):
        shutil.copy2(cases_file, target)
    lint = sentry_case_lint.lint_cases_file(target)
    sentry_case_lint.record_case_lint_result(session_dir, lint)
    cases_total = lint.get("total", 0)
    session = sentry_state.load_session(session_dir)
    session["cases"] = {"total": cases_total, "types": {}, "reused": False}
    session["updated_at"] = utc_now()
    sentry_state.save_session(session_dir, session)
    return {
        "status": "OK",
        "cases_file": str(target),
        "source": str(cases_file),
        "cases_hash": cases_hash,
        "case_lint": lint,
        "step": "prepare_cases",
        "reused": False,
        "reuse": reuse_state,
    }


def expected_response_outputs(evals_file: Path, session_dir: Path, variant: str = "with_skill") -> list[Path]:
    return sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).response_outputs(variant)


def expected_grading_outputs(evals_file: Path, session_dir: Path) -> list[Path]:
    return sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).grading_outputs()


def run_profile_preflight(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    return code, profile_payload("preflight", "OK" if code == 0 else "ERROR", preflight=preflight, timings=timings.snapshot())


def run_profile_lint(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    if code != 0:
        return code, profile_payload("lint", "ERROR", preflight=preflight, timings=timings.snapshot())

    with timings.phase("session"):
        session_dir = init_session(
            preflight["skill_dir_name"],
            preflight["skill_hash"],
            preflight["skill_type"],
            args.mode,
            preflight,
            preflight.get("runtime", args.runtime),
        )
    cases_file = resolve_cases(args, preflight)
    if not cases_file:
        payload = profile_payload(
            "lint",
            "WARN",
            session_dir=str(session_dir),
            preflight=preflight,
            warning="No evals.json/cases.cache.json found; only preflight completed.",
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 0, payload

    with timings.phase("prepare_cases"):
        prepared = prepare_cases(session_dir, cases_file)
    status = "OK" if prepared.get("status") == "OK" and prepared.get("case_lint", {}).get("warning_count", 0) == 0 else "WARN"
    payload = profile_payload(
        "lint",
        status,
        session_dir=str(session_dir),
        preflight=preflight,
        cases=prepared,
        reuse_summary=summarize_reuse_decisions(prepared),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if prepared.get("status") == "OK" else 1, payload


def run_profile_plan(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    plan = build_mode_plan(args.mode)
    payload = profile_payload(
        "plan",
        "OK" if code == 0 else "ERROR",
        mode=args.mode,
        preflight=preflight,
        plan=plan,
        dry_run=True,
        timings=timings.snapshot(),
    )
    return code, payload


def run_profile_debug(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    if not args.session_dir:
        return 2, profile_payload("debug", "ERROR", error="--session-dir is required for profile=debug", timings=timings.snapshot())
    session_dir = Path(args.session_dir).expanduser()
    if not session_dir.exists():
        return 2, profile_payload("debug", "ERROR", error=f"session dir not found: {session_dir}", timings=timings.snapshot())

    with timings.phase("gate"):
        gate = build_gate(session_dir)
    save_json(session_dir / "gate-result.json", gate)
    with timings.phase("diagnostics"):
        diagnostics = sentry_diagnostics.collect_diagnostics(session_dir, gate)
    save_json(session_dir / "diagnostics.json", diagnostics)
    with timings.phase("report"):
        report = sentry_report.ensure_session_report(
            session_dir,
            gate,
            title="SkillSentry Debug Report",
            generated_by="sentry_run.py",
            footer="Debug profile recalculates gate, diagnostics, and report from existing artifacts.",
            replace_generated_only=False,
        )
    payload = profile_payload(
        "debug",
        "OK",
        session_dir=str(session_dir),
        gate=gate,
        diagnostics=diagnostics,
        artifacts={"report_html": str(report), "diagnostics_json": str(session_dir / "diagnostics.json")},
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0, payload


def run_profile_local(args) -> tuple[int, dict]:
    timings = ProfileTimings()
    with timings.phase("preflight"):
        code, preflight = run_preflight(args)
    if code != 0:
        return code, profile_payload("local", "ERROR", preflight=preflight, timings=timings.snapshot())
    cases_file = resolve_cases(args, preflight)
    if not cases_file:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error="profile=local requires --cases or cached evals", timings=timings.snapshot())
    if args.dry_run:
        plan = build_profile_plan("local")
        reuse_forecast = None
        if args.reuse_session:
            if args.reuse_session == "auto":
                reuse_forecast = find_auto_reuse_session(args, preflight, cases_file)
            else:
                session_dir = Path(args.reuse_session).expanduser()
                if not session_dir.exists():
                    return 2, profile_payload("local", "ERROR", preflight=preflight, error=f"reuse session not found: {session_dir}", timings=timings.snapshot())
                reuse_forecast = local_dry_run_reuse(session_dir, cases_file, args, preflight)
        payload = profile_payload(
            "local",
            "OK",
            preflight=preflight,
            cases_file=str(cases_file),
            dry_run=True,
            plan=plan,
            reuse_forecast=reuse_forecast,
            timings=timings.snapshot(),
        )
        return 0, payload

    auto_reuse = None
    try:
        with timings.phase("session"):
            if args.reuse_session == "auto":
                auto_reuse = find_auto_reuse_session(args, preflight, cases_file)
                if auto_reuse.get("selected") and auto_reuse.get("session_dir"):
                    session_dir = Path(str(auto_reuse["session_dir"]))
                else:
                    session_dir = init_session(
                        preflight["skill_dir_name"],
                        preflight["skill_hash"],
                        preflight["skill_type"],
                        args.mode,
                        preflight,
                        preflight.get("runtime", args.runtime),
                    )
            else:
                session_dir = resolve_local_session(args, preflight)
    except FileNotFoundError as exc:
        return 2, profile_payload("local", "ERROR", preflight=preflight, error=str(exc), timings=timings.snapshot())
    with timings.phase("session_metadata"):
        refresh_session_metadata(session_dir, args, preflight)

    with timings.phase("prepare_cases"):
        prepared = prepare_cases(session_dir, cases_file)
    if prepared.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            reuse_summary=summarize_reuse_decisions(prepared),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("executor"):
        model = args.executor_model or args.model
        evals_file = session_dir / "evals.json"
        skill_path = Path(preflight["skill_path"])
        executor_hash = combine_hash(
            "executor-with",
            file_hash(evals_file),
            file_hash(skill_path),
            model,
            args.timeout_per_eval,
        )
        executor_outputs = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).required_outputs("executor-with")
        executor_reuse = step_reuse_state(session_dir, "executor-with", executor_hash, executor_outputs)
        if not args.force_executor and executor_reuse.get("reusable"):
            executor = {
                "status": "OK",
                "step": "executor-with",
                "variant": "with_skill",
                "reused": True,
                "reuse": executor_reuse,
                "summary_file": str(session_dir / "executor_results.json"),
                "summary": load_json(session_dir / "executor_results.json"),
            }
        else:
            executor = execute_executor_step(
                evals_file=evals_file,
                skill_path=skill_path,
                session_dir=session_dir,
                model=model,
                timeout_per_eval=args.timeout_per_eval,
                variant="with_skill",
                verbose=args.verbose,
                update_session=True,
            )
            executor["reused"] = False
            executor["reuse"] = {"step": "executor-with", "reusable": False, "reason": "force_executor"} if args.force_executor else executor_reuse
            record_manifest_step(
                session_dir,
                "executor-with",
                status=executor.get("status", "ERROR"),
                input_hash=executor_hash,
                outputs=executor_outputs,
                extra={"model": model, "timeout_per_eval": args.timeout_per_eval},
            )
    if executor.get("status") != "OK":
        payload = profile_payload(
            "local",
            "ERROR",
            session_dir=str(session_dir),
            preflight=preflight,
            cases=prepared,
            executor=executor,
            reuse_summary=summarize_reuse_decisions(prepared, executor),
            timings=timings.snapshot(),
        )
        save_json(session_dir / "sentry-run-result.json", payload)
        return 1, payload

    with timings.phase("grader"):
        response_hashes = [(str(path), file_hash(path)) for path in expected_response_outputs(evals_file, session_dir)]
        grader_hash = combine_hash("grader-report", file_hash(evals_file), response_hashes, args.model)
        grader_outputs = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file).required_outputs("grader-report")
        grader_reuse = step_reuse_state(session_dir, "grader-report", grader_hash, grader_outputs)
        if not args.force_grader and grader_reuse.get("reusable"):
            gate = build_gate(session_dir)
            grader = {
                "status": "OK",
                "step": "grader-report",
                "model": args.model,
                "reused": True,
                "reuse": grader_reuse,
                "artifacts": {
                    "grading_summary": str(session_dir / "grading-summary.json"),
                    "report_html": str(session_dir / "report.html"),
                },
                "gate": gate,
            }
        else:
            grader = sentry_grader.execute_grader_report(
                evals_file=evals_file,
                session_dir=session_dir,
                model=args.model,
                verbose=args.verbose,
                update_session=True,
                write_report=True,
            )
            grader["reused"] = False
            grader["reuse"] = {"step": "grader-report", "reusable": False, "reason": "force_grader"} if args.force_grader else grader_reuse
            record_manifest_step(
                session_dir,
                "grader-report",
                status=grader.get("status", "ERROR"),
                input_hash=grader_hash,
                outputs=grader_outputs,
                extra={"model": args.model},
            )
    with timings.phase("diagnostics"):
        gate = grader.get("gate") or build_gate(session_dir)
        diagnostics = sentry_diagnostics.collect_diagnostics(session_dir, gate)
    save_json(session_dir / "diagnostics.json", diagnostics)
    payload = profile_payload(
        "local",
        "OK" if grader.get("status") == "OK" else "ERROR",
        session_dir=str(session_dir),
        auto_reuse=auto_reuse,
        preflight=preflight,
        cases=prepared,
        executor=executor,
        grader=grader,
        reuse_summary=summarize_reuse_decisions(prepared, executor, grader),
        gate=gate,
        diagnostics=diagnostics,
        manifest=str(manifest_path(session_dir)),
        timings=timings.snapshot(),
    )
    save_json(session_dir / "sentry-run-result.json", payload)
    return 0 if payload["status"] == "OK" else 1, payload


def run_delegated_ci(args, release: bool = False) -> tuple[int, dict]:
    timings = ProfileTimings()
    mode = "standard" if release and args.mode == "smoke" else args.mode
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "sentry_ci.py"),
        "--skill",
        args.skill,
        "--mode",
        mode,
        "--threshold",
        str(args.threshold),
        "--output-dir",
        args.output_dir,
        "--model",
        args.model,
        "--timeout",
        str(args.timeout),
        "--timeout-per-eval",
        str(args.timeout_per_eval),
        "--runtime",
        args.runtime,
        "--config",
        args.config,
    ]
    if args.executor_model:
        cmd.extend(["--executor-model", args.executor_model])
    if args.cases:
        cmd.extend(["--cases", args.cases])
    if args.github_output:
        cmd.append("--github-output")
    if args.verbose:
        cmd.append("--verbose")
    with timings.phase("delegated_ci"):
        completed = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=args.format == "json",
        )
    extra = {}
    if args.format == "json":
        extra["delegated_stdout"] = completed.stdout or ""
        extra["delegated_stderr"] = completed.stderr or ""
    return completed.returncode, profile_payload(
        "release" if release else "ci",
        "OK" if completed.returncode == 0 else "ERROR",
        delegated_command=cmd,
        exit_code=completed.returncode,
        timings=timings.snapshot(),
        **extra,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SkillSentry by lightweight profile")
    parser.add_argument("--profile", choices=PROFILES, default="lint")
    parser.add_argument("--skill", help="Skill name, directory, or SKILL.md path")
    parser.add_argument("--session-dir", help="Existing session directory for debug profile")
    parser.add_argument("--reuse-session", help="Existing session directory for local profile artifact reuse")
    parser.add_argument("--cases", help="Existing evals.json/cases.cache.json path")
    parser.add_argument("--mode", choices=sorted(PIPELINES), default="smoke")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--output-dir", default="./ci-eval-results")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--executor-model", default=None)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--timeout-per-eval", type=int, default=120)
    parser.add_argument("--runtime", choices=["auto", "cli", "openclaw"], default="auto")
    parser.add_argument("--config", default=str(sentry_preflight.DEFAULT_CONFIG))
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Plan a local run without creating a session or running heavy steps")
    parser.add_argument("--force-executor", action="store_true", help="Rerun local executor even when manifest matches")
    parser.add_argument("--force-grader", action="store_true", help="Rerun local grader even when manifest matches")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.profile != "debug" and not args.skill:
        timings = ProfileTimings()
        payload = profile_payload(args.profile, "ERROR", error="--skill is required unless --profile debug", timings=timings.snapshot())
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json" else payload["error"])
        return 2

    if args.profile == "preflight":
        code, payload = run_profile_preflight(args)
    elif args.profile == "lint":
        code, payload = run_profile_lint(args)
    elif args.profile == "plan":
        code, payload = run_profile_plan(args)
    elif args.profile == "debug":
        code, payload = run_profile_debug(args)
    elif args.profile == "local":
        code, payload = run_profile_local(args)
    elif args.profile == "ci":
        code, payload = run_delegated_ci(args, release=False)
    elif args.profile == "release":
        code, payload = run_delegated_ci(args, release=True)
    else:
        code, payload = 2, profile_payload(args.profile, "ERROR", error=f"unknown profile: {args.profile}")

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"sentry run: {payload['status']} | profile: {payload['profile']}")
        if payload.get("session_dir"):
            print(f"session: {payload['session_dir']}")
        timings = payload.get("timings", {})
        if isinstance(timings, dict) and timings.get("total_ms") is not None:
            print(f"duration_ms: {timings['total_ms']}")
        if payload.get("error"):
            print(f"- {payload['error']}")
        if payload.get("warning"):
            print(f"- {payload['warning']}")
        plan = payload.get("plan")
        if isinstance(plan, dict) and plan.get("steps"):
            print("plan:")
            for item in plan["steps"]:
                markers = []
                if item.get("heavy"):
                    markers.append("heavy")
                if item.get("requires_llm"):
                    markers.append("llm")
                if item.get("requires_network"):
                    markers.append("network")
                suffix = f" [{', '.join(markers)}]" if markers else ""
                print(f"- {item.get('step')}: {item.get('tool')}{suffix}")
            if plan.get("heavy_steps"):
                print("heavy steps: " + ", ".join(str(item) for item in plan.get("heavy_steps", [])))
            if plan.get("network_steps"):
                print("network steps: " + ", ".join(str(item) for item in plan.get("network_steps", [])))
        reuse_summary = payload.get("reuse_summary", {})
        if isinstance(reuse_summary, dict) and reuse_summary.get("steps"):
            print("reuse:")
            for item in reuse_summary["steps"]:
                if not isinstance(item, dict):
                    continue
                action = "reused" if item.get("reused") else "reran"
                details = []
                if item.get("missing_outputs_count"):
                    details.append(f"missing_outputs={item.get('missing_outputs_count')}")
                if item.get("recorded_status") is not None:
                    details.append(f"recorded_status={item.get('recorded_status')}")
                if item.get("recorded_type") is not None:
                    details.append(f"recorded_type={item.get('recorded_type')}")
                if item.get("expected_input_hash") and item.get("recorded_input_hash"):
                    details.append("input_hash_changed")
                if item.get("expected_cases_hash") and item.get("prepared_cases_hash"):
                    details.append("cases_hash_changed")
                suffix = f"; {', '.join(details)}" if details else ""
                print(f"- {item.get('step')}: {action} ({item.get('reason')}{suffix})")
            hints = reuse_summary.get("hints")
            if isinstance(hints, list) and hints:
                print("reuse hints:")
                for hint in hints:
                    print(f"- {hint}")
        reuse_forecast = payload.get("reuse_forecast")
        if isinstance(reuse_forecast, dict) and isinstance(reuse_forecast.get("summary"), dict):
            forecast_summary = reuse_forecast["summary"]
            if forecast_summary.get("steps"):
                print("reuse forecast:")
                for item in forecast_summary["steps"]:
                    action = "would reuse" if item.get("reused") else "would rerun"
                    print(f"- {item.get('step')}: {action} ({item.get('reason')})")
        artifacts = payload.get("artifacts", {})
        if isinstance(artifacts, dict) and artifacts.get("report_html"):
            print(f"report: {artifacts['report_html']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
