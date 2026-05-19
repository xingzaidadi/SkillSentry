#!/usr/bin/env python3
"""Shared deterministic reuse helpers for SkillSentry local artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sentry_artifacts
import sentry_case_lint
import sentry_reuse
import sentry_state


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def combine_hash(*parts: Any) -> str:
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


def manifest_path(session_dir: Path) -> Path:
    return sentry_artifacts.ArtifactRegistry(session_dir).manifest_path()


def load_manifest(session_dir: Path) -> dict:
    path = manifest_path(session_dir)
    if not path.exists():
        return {"version": 1, "steps": {}}
    try:
        data = sentry_artifacts.load_json(path)
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
    path = manifest_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def local_reuse_forecast(
    session_dir: Path,
    cases_file: Path,
    *,
    preflight: dict,
    model: str,
    executor_model: str | None,
    timeout_per_eval: int,
    force_executor: bool = False,
    force_grader: bool = False,
) -> dict:
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

    executor_model_name = executor_model or model
    skill_path = Path(preflight["skill_path"])
    registry = sentry_artifacts.ArtifactRegistry(session_dir, evals_file=evals_file)
    executor_hash = combine_hash(
        "executor-with",
        file_hash(evals_file),
        file_hash(skill_path),
        executor_model_name,
        timeout_per_eval,
    )
    executor_reuse = step_reuse_state(session_dir, "executor-with", executor_hash, registry.required_outputs("executor-with"))
    if force_executor:
        executor_reuse = {"step": "executor-with", "reusable": False, "reason": "force_executor"}
    decisions.append(executor_reuse)

    response_hashes = [(str(path), file_hash(path)) for path in registry.response_outputs("with_skill")]
    grader_hash = combine_hash("grader-report", file_hash(evals_file), response_hashes, model)
    grader_reuse = step_reuse_state(session_dir, "grader-report", grader_hash, registry.required_outputs("grader-report"))
    if force_grader:
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


def find_auto_reuse_session(
    base: Path,
    cases_file: Path,
    *,
    preflight: dict,
    model: str,
    executor_model: str | None,
    timeout_per_eval: int,
    force_executor: bool = False,
    force_grader: bool = False,
) -> dict:
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
            forecast = local_reuse_forecast(
                candidate,
                cases_file,
                preflight=preflight,
                model=model,
                executor_model=executor_model,
                timeout_per_eval=timeout_per_eval,
                force_executor=force_executor,
                force_grader=force_grader,
            )
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
