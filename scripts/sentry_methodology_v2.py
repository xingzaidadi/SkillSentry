#!/usr/bin/env python3
"""SkillSentry methodology V2 analyzer.

This module fills the V2 planning gaps with deterministic, no-network
analysis for:

- multi-skill route evaluation
- failure taxonomy
- contamination and sampling protocol
- grader calibration
- external benchmark adapter mapping

The analyzer is intentionally conservative: when explicit predictions or
calibration artifacts are unavailable, it falls back to heuristic probe
estimates and clearly labels them as such.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from sentry_case_lint import extract_cases
from sentry_gate import counts_from_grading


ROUTE_FIELD_KEYS = (
    "route_expected",
    "expected_route",
    "expected_skill",
    "target_skill",
    "main_skill",
    "route_reason_expected",
    "route_confidence_min",
    "route_family",
    "no_route_expected",
    "allowed_skills",
    "forbidden_skills",
)

EXPLICIT_PREDICTION_KEYS = (
    "route_prediction",
    "predicted_route",
    "predicted_skill",
    "selected_skill",
    "route_selected",
    "actual_route",
    "route_choice",
)

ACTION_WORDS = (
    "处理",
    "创建",
    "提交",
    "修复",
    "执行",
    "生成",
    "调用",
    "导出",
    "审批",
    "配置",
    "更新",
    "删除",
    "分析",
    "优化",
    "检查",
)

NEGATIVE_WORDS = (
    "解释",
    "定义",
    "概念",
    "是什么",
    "科普",
    "总结",
    "说明一下",
)

FAILURE_FIXES = {
    "F1": ("skill发现", "优化 description、触发示例、正例集", "skill_author"),
    "F2": ("skill发现", "收窄适用范围、补 no-route 反例", "skill_author"),
    "F3": ("skill选择", "优化边界、优先级、相似 Skill 描述", "skill_author"),
    "F4": ("skill加载", "修复安装、路径、依赖和 preflight", "infra_owner"),
    "F5": ("计划执行", "重写步骤，提升规则显著性", "skill_author"),
    "F6": ("工具动作", "补 tool schema、示例、mock 断言", "skill_author"),
    "F7": ("结果生成", "补 schema、模板、exact 断言", "skill_author"),
    "F8": ("安全边界", "P0 veto、沙箱、人工确认", "security_owner"),
    "F9": ("效率层", "压缩 Skill、分层加载、批次优化", "infra_owner"),
    "F10": ("鲁棒层", "降低歧义、固定流程、多采样", "skill_author"),
    "F11": ("运行环境", "修环境，不计入 Skill 质量失败", "infra_owner"),
    "F12": ("评分器", "人审校准、改 rubric、增加 exact", "grader_owner"),
}

ADAPTER_NAMES = (
    "openai_evals_style",
    "bfcl_style",
    "toolbench_style",
    "agentbench_style",
    "gaia_style",
    "tau_bench_style",
    "metr_style",
    "agentdojo_style",
    "owasp_llm_top10",
)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _first_text(*values) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _combined_text(case: dict, extra_keys: tuple[str, ...] = ()) -> str:
    parts: list[str] = []
    for key in ("name", "prompt", "description", "expected_output", "expected_guardrail", *extra_keys):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            parts.extend(
                str(item).strip()
                for item in value.values()
                if isinstance(item, str) and item.strip()
            )
    return "\n".join(parts)


def _flatten_text(value) -> str:
    parts: list[str] = []
    if isinstance(value, str) and value.strip():
        parts.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            text = _flatten_text(item)
            if text:
                parts.append(text)
    elif isinstance(value, dict):
        for item in value.values():
            text = _flatten_text(item)
            if text:
                parts.append(text)
    return "\n".join(parts)


def _find_case_file(session_dir: Path) -> Path | None:
    candidates = [
        session_dir / "evals.json",
        session_dir / "cases.json",
        session_dir / "items.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_cases(session_dir: Path, session: dict | None = None) -> tuple[list[dict], str]:
    file_path = _find_case_file(session_dir)
    if file_path is not None:
        payload = load_json(file_path)
        return extract_cases(payload), str(file_path.name)
    if isinstance(session, dict):
        for key in ("evals", "cases", "items"):
            payload = session.get(key)
            cases = extract_cases(payload)
            if cases:
                return cases, f"session.{key}"
    return [], "none"


def _case_id(case: dict, fallback: str) -> str:
    return str(case.get("id") or case.get("case_id") or fallback)


def _extract_explicit_route(case: dict) -> tuple[str, str, float | None]:
    for key in EXPLICIT_PREDICTION_KEYS:
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), "explicit", None
        if isinstance(value, list) and value:
            first = _first_text(*[str(item) for item in value if isinstance(item, str)])
            if first:
                return first, "explicit", None
        if isinstance(value, dict):
            label = _first_text(
                value.get("selected_skill"),
                value.get("predicted_skill"),
                value.get("route"),
                value.get("skill"),
                value.get("label"),
            )
            if label:
                confidence = value.get("confidence")
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                    return label, "explicit", float(confidence)
                return label, "explicit", None

    route_result = case.get("route_result")
    if isinstance(route_result, dict):
        label = _first_text(
            route_result.get("selected_skill"),
            route_result.get("predicted_skill"),
            route_result.get("route"),
            route_result.get("skill"),
            route_result.get("label"),
        )
        if label:
            confidence = route_result.get("confidence")
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
                return label, "explicit", float(confidence)
            return label, "explicit", None
    return "", "", None


def _route_candidates(case: dict, skill_name: str) -> list[str]:
    labels: list[str] = []
    for key in ("route_expected", "expected_route", "expected_skill", "target_skill", "main_skill"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            labels.append(value.strip())
    for key in ("allowed_skills", "forbidden_skills"):
        value = case.get(key)
        if isinstance(value, list):
            labels.extend(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    if skill_name:
        labels.append(skill_name)
    labels.append("none")
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        normalized = label.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(label)
    return deduped


def _predict_route_probe(case: dict, candidate_labels: list[str], skill_name: str) -> tuple[str, float, list[str]]:
    prompt_text = _combined_text(case).lower()
    reason_text = _flatten_text(case.get("route_reason_expected")).lower()
    expected_label = _first_text(
        case.get("route_expected"),
        case.get("expected_route"),
        case.get("expected_skill"),
        case.get("target_skill"),
        case.get("main_skill"),
    ).lower()
    no_route_expected = bool(case.get("no_route_expected"))

    signals: list[str] = []
    if any(word in prompt_text for word in ACTION_WORDS):
        signals.append("action_word")
    if any(word in prompt_text for word in NEGATIVE_WORDS):
        signals.append("negative_word")
    if expected_label and expected_label in prompt_text:
        signals.append("label_match")
    if reason_text and expected_label and expected_label in reason_text:
        signals.append("reason_match")

    scores: dict[str, float] = {}
    for label in candidate_labels:
        normalized = label.lower()
        score = 0.35
        if normalized == "none":
            if any(word in prompt_text for word in NEGATIVE_WORDS):
                score += 0.35
            if not any(word in prompt_text for word in ACTION_WORDS):
                score += 0.10
            if no_route_expected:
                score += 0.12
        else:
            if any(word in prompt_text for word in ACTION_WORDS):
                score += 0.20
            if normalized in prompt_text:
                score += 0.30
            if expected_label and normalized == expected_label:
                score += 0.25
            if reason_text and normalized in reason_text:
                score += 0.15
            if no_route_expected:
                score -= 0.15
            if any(word in prompt_text for word in NEGATIVE_WORDS):
                score -= 0.12
            if skill_name and normalized == skill_name.lower():
                score += 0.10
        scores[label] = max(0.0, min(1.0, score))

    best_label = max(scores, key=scores.get) if scores else "none"
    best_score = scores.get(best_label, 0.0)
    second_score = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    if best_score < 0.45 or (best_score - second_score) < 0.05:
        best_label = "none"
        best_score = max(best_score, scores.get("none", 0.5))
    return best_label, round(best_score, 3), signals


def _canonical_route_label(value: str, skill_name: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return "none"
    if normalized in {"none", "no_route", "no-route", "skip", "skip_route"}:
        return "none"
    if skill_name and normalized == skill_name.lower():
        return skill_name
    return value.strip()


def analyze_route_evaluation(cases: list[dict], skill_name: str) -> dict:
    route_cases = []
    candidate_pool: list[str] = []

    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            continue
        if any(case.get(key) not in (None, "", [], {}) for key in ROUTE_FIELD_KEYS) or any(
            case.get(key) not in (None, "", [], {}) for key in EXPLICIT_PREDICTION_KEYS
        ):
            route_cases.append(case)
            candidate_pool.extend(_route_candidates(case, skill_name))

    if not route_cases:
        return {
            "status": "SKIPPED",
            "route_case_total": 0,
            "reason": "no route metadata found",
        }

    candidate_labels = []
    seen: set[str] = set()
    for label in candidate_pool or [skill_name or "none"]:
        normalized = label.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        candidate_labels.append(label)
    if "none" not in {label.lower() for label in candidate_labels}:
        candidate_labels.append("none")

    explicit_rows = []
    probe_rows = []
    route_field_cases = 0
    explicit_count = 0
    probe_count = 0
    exact_hits = 0
    probe_hits = 0
    route_expected_total = 0
    no_route_total = 0
    explicit_no_route_hits = 0
    probe_no_route_hits = 0
    route_low_confidence = []
    confusion_explicit: dict[str, Counter[str]] = defaultdict(Counter)
    confusion_probe: dict[str, Counter[str]] = defaultdict(Counter)
    misroutes = []

    for index, case in enumerate(route_cases, 1):
        case_id = _case_id(case, f"route-{index}")
        expected = _first_text(
            case.get("route_expected"),
            case.get("expected_route"),
            case.get("expected_skill"),
            case.get("target_skill"),
            case.get("main_skill"),
        )
        if not expected and case.get("no_route_expected"):
            expected = "none"
        if not expected and skill_name:
            expected = skill_name
        expected = _canonical_route_label(expected, skill_name)
        if expected:
            route_expected_total += 1
        if expected == "none":
            no_route_total += 1

        explicit_pred, explicit_mode, explicit_conf = _extract_explicit_route(case)
        if explicit_pred:
            explicit_count += 1
            pred_label = _canonical_route_label(explicit_pred, skill_name)
            if explicit_conf is not None:
                confidence = explicit_conf
            else:
                confidence = 0.95
            explicit_rows.append(
                {
                    "case_id": case_id,
                    "expected": expected,
                    "predicted": pred_label,
                    "confidence": round(confidence, 3),
                    "mode": explicit_mode,
                }
            )
            confusion_explicit[expected][pred_label] += 1
            if pred_label == expected:
                exact_hits += 1
            if expected == "none" and pred_label == "none":
                explicit_no_route_hits += 1
            if expected != pred_label:
                misroutes.append(
                    {
                        "case_id": case_id,
                        "expected": expected,
                        "predicted": pred_label,
                        "mode": explicit_mode,
                    }
                )

        probe_pred, probe_conf, signals = _predict_route_probe(case, candidate_labels, skill_name)
        probe_count += 1
        probe_rows.append(
            {
                "case_id": case_id,
                "expected": expected,
                "predicted": probe_pred,
                "confidence": round(probe_conf, 3),
                "mode": "heuristic_probe",
                "signals": signals,
            }
        )
        confusion_probe[expected][probe_pred] += 1
        if probe_pred == expected:
            probe_hits += 1
        if expected == "none" and probe_pred == "none":
            probe_no_route_hits += 1

        min_conf = case.get("route_confidence_min")
        if isinstance(min_conf, (int, float)) and probe_conf < float(min_conf):
            route_low_confidence.append(
                {
                    "case_id": case_id,
                    "expected": expected,
                    "probe_confidence": round(probe_conf, 3),
                    "threshold": float(min_conf),
                }
            )

        if any(case.get(key) not in (None, "", [], {}) for key in ROUTE_FIELD_KEYS):
            route_field_cases += 1

    explicit_accuracy = exact_hits / explicit_count if explicit_count else None
    probe_accuracy = probe_hits / probe_count if probe_count else None
    no_route_precision = None
    if no_route_total:
        no_route_precision = (explicit_no_route_hits or probe_no_route_hits) / no_route_total
    route_recall = None
    positive_total = route_expected_total - no_route_total
    if positive_total > 0:
        route_recall = (exact_hits if explicit_count else probe_hits) / positive_total

    matrix_labels = _select_matrix_labels(route_cases, skill_name)
    explicit_matrix = _build_matrix(confusion_explicit, matrix_labels)
    probe_matrix = _build_matrix(confusion_probe, matrix_labels)

    route_field_coverage = route_field_cases / len(route_cases) if route_cases else None
    gate_recommendation = _route_gate_recommendation(
        explicit_accuracy=explicit_accuracy,
        probe_accuracy=probe_accuracy,
        no_route_precision=no_route_precision,
        route_field_coverage=route_field_coverage,
        low_confidence=len(route_low_confidence),
        route_case_total=len(route_cases),
    )

    prediction_mode = "explicit" if explicit_count else "heuristic_probe"
    accuracy = explicit_accuracy if explicit_count else probe_accuracy

    return {
        "status": "OK",
        "prediction_mode": prediction_mode,
        "route_case_total": len(route_cases),
        "route_field_case_total": route_field_cases,
        "route_field_coverage_rate": round(route_field_coverage, 4) if route_field_coverage is not None else None,
        "candidate_labels": candidate_labels,
        "explicit_prediction_count": explicit_count,
        "probe_prediction_count": probe_count,
        "route_expected_total": route_expected_total,
        "no_route_total": no_route_total,
        "explicit_accuracy": round(explicit_accuracy, 4) if explicit_accuracy is not None else None,
        "probe_accuracy": round(probe_accuracy, 4) if probe_accuracy is not None else None,
        "top1_accuracy": round(accuracy, 4) if accuracy is not None else None,
        "no_route_precision": round(no_route_precision, 4) if no_route_precision is not None else None,
        "route_recall": round(route_recall, 4) if route_recall is not None else None,
        "route_low_confidence": route_low_confidence,
        "route_low_confidence_count": len(route_low_confidence),
        "matrix_labels": matrix_labels,
        "explicit_confusion_matrix": explicit_matrix,
        "probe_confusion_matrix": probe_matrix,
        "explicit_rows": explicit_rows[:20],
        "probe_rows": probe_rows[:20],
        "misroutes": misroutes[:20],
        "gate_recommendation": gate_recommendation,
    }


def _select_matrix_labels(route_cases: list[dict], skill_name: str) -> list[str]:
    counts: Counter[str] = Counter()
    for case in route_cases:
        expected = _canonical_route_label(
            _first_text(
                case.get("route_expected"),
                case.get("expected_route"),
                case.get("expected_skill"),
                case.get("target_skill"),
                case.get("main_skill"),
            )
            or ("none" if case.get("no_route_expected") else skill_name),
            skill_name,
        )
        explicit_pred, _, _ = _extract_explicit_route(case)
        probe_pred, _, _ = _predict_route_probe(case, [expected, skill_name, "none"], skill_name)
        counts[expected] += 1
        counts[_canonical_route_label(explicit_pred or probe_pred, skill_name)] += 1
    labels = [label for label, _ in counts.most_common(4)]
    for label in ("none", skill_name):
        if label and label not in labels:
            labels.append(label)
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        normalized = label.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(label)
    return deduped


def _build_matrix(matrix: dict[str, Counter[str]], labels: list[str]) -> dict:
    normalized_labels = list(dict.fromkeys(labels))
    rows = []
    for expected in normalized_labels:
        row = {"expected": expected, "counts": {}}
        for predicted in normalized_labels:
            row["counts"][predicted] = int(matrix.get(expected, Counter()).get(predicted, 0))
        other = sum(
            count
            for predicted, count in matrix.get(expected, Counter()).items()
            if predicted not in normalized_labels
        )
        if other:
            row["counts"]["other"] = int(other)
        rows.append(row)
    return {"labels": normalized_labels, "rows": rows}


def _route_gate_recommendation(
    *,
    explicit_accuracy: float | None,
    probe_accuracy: float | None,
    no_route_precision: float | None,
    route_field_coverage: float | None,
    low_confidence: int,
    route_case_total: int,
) -> str:
    accuracy = explicit_accuracy if explicit_accuracy is not None else probe_accuracy
    if route_case_total == 0:
        return "not_applicable"
    if route_field_coverage is not None and route_field_coverage < 0.7:
        return "needs_more_route_metadata"
    if accuracy is None:
        return "needs_predictions"
    if no_route_precision is not None and no_route_precision < 0.9:
        return "block_no_route_precision"
    if low_confidence > max(1, route_case_total // 5):
        return "warn_low_confidence"
    if accuracy >= 0.85:
        return "pass"
    if accuracy >= 0.75:
        return "conditional_pass"
    return "block"


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _grade_status(grading: dict) -> str:
    summary = grading.get("summary") if isinstance(grading, dict) else None
    if isinstance(summary, dict):
        status = _first_text(summary.get("status"), grading.get("status"))
        if status:
            return status.upper()
        rate = summary.get("authoritative_pass_rate")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            return "PASS" if rate >= 1.0 else "FAIL"
    status = _first_text(grading.get("status"))
    return status.upper() if status else "UNKNOWN"


def _assertion_passed(assertion: dict) -> bool:
    if "passed" in assertion:
        return bool(assertion.get("passed"))
    if "pass" in assertion:
        return bool(assertion.get("pass"))
    result = str(assertion.get("result") or "").strip().lower()
    return result in {"pass", "passed", "ok", "success", "true"}


def _failure_evidence(grading: dict) -> str:
    parts: list[str] = []
    for key in ("status", "error", "message", "reason", "note"):
        value = grading.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    summary = grading.get("summary")
    if isinstance(summary, dict):
        for key in ("status", "error", "reason", "note", "grader_error"):
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        if summary.get("precision_breakdown"):
            parts.append(json.dumps(summary.get("precision_breakdown"), ensure_ascii=False))
    if isinstance(grading.get("assertions"), list):
        for assertion in grading["assertions"]:
            if not isinstance(assertion, dict):
                continue
            for key in ("type", "name", "expected", "actual", "message", "evidence", "error"):
                value = assertion.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    return "\n".join(parts).lower()


def _extract_failed_assertions(grading: dict) -> list[dict]:
    failures: list[dict] = []
    assertions = grading.get("assertions")
    if not isinstance(assertions, list):
        return failures
    for assertion in assertions:
        if isinstance(assertion, dict) and not _assertion_passed(assertion):
            failures.append(assertion)
    return failures


def _explicit_failure_codes(case: dict, grading: dict, evidence: str) -> list[str]:
    codes: list[str] = []
    case_text = _combined_text(case).lower()
    security_meta = bool(
        str(case.get("security_family") or "").strip()
        or str(case.get("dimension") or case.get("category") or case.get("type") or "").strip().lower() == "security"
        or str(case.get("risk_level") or "").strip().upper() in {"P0", "P1"}
        or str(case.get("gate_level") or "").strip().lower() in {"block", "warn"}
    )
    security_evidence = _has_any_keyword(evidence, ("secret", "泄密", "prompt injection", "injection", "外联", "危险命令", "secrets exposed"))
    if security_meta and (_has_any_keyword(case_text + "\n" + evidence, ("secret", "泄密", "越权", "prompt injection", "injection", "外联", "危险命令")) or security_evidence):
        codes.append("F8")

    if _has_any_keyword(evidence, ("LLM grader call failed", "parse error", "grade", "judge")):
        codes.append("F12")

    if _has_any_keyword(evidence, ("preflight", "runner", "sdk", "mcp", "config", "environment", "not found", "missing grading")):
        codes.append("F11")

    if _has_any_keyword(evidence, ("timeout", "token", "cost", "duration", "slow", "latency")):
        codes.append("F9")

    if _has_any_keyword(case_text + "\n" + evidence, ("load", "path", "hash", "install", "frontmatter", "dependency")):
        codes.append("F4")

    if _has_any_keyword(case_text + "\n" + evidence, ("tool", "参数", "argument", "sequence", "order", "call", "plugin")):
        codes.append("F6")

    if _has_any_keyword(case_text + "\n" + evidence, ("schema", "format", "field", "output", "exact_match", "exact match", "response.md")):
        codes.append("F7")

    if _has_any_keyword(case_text + "\n" + evidence, ("rule", "checklist", "instruction", "step", "required", "漏掉", "遗漏")):
        codes.append("F5")

    if _has_any_keyword(case_text + "\n" + evidence, ("drift", "unstable", "variance", "inconsistent", "摇摆")):
        codes.append("F10")

    route_expected = _first_text(case.get("route_expected"), case.get("expected_route"), case.get("expected_skill"), case.get("target_skill"), case.get("main_skill"))
    predicted_route, _, _ = _extract_explicit_route(case)
    if case.get("no_route_expected"):
        if predicted_route:
            codes.append("F2")
    elif route_expected or predicted_route:
        if route_expected and predicted_route:
            if _canonical_route_label(route_expected, "") != _canonical_route_label(predicted_route, ""):
                codes.append("F3")
        elif not predicted_route:
            codes.append("F1")

    dimension = str(case.get("dimension") or case.get("category") or case.get("type") or "").strip().lower()
    if dimension in {"negative", "security"} and not predicted_route and not route_expected:
        codes.append("F1")
    if dimension in {"negative", "security"} and predicted_route and case.get("no_route_expected"):
        codes.append("F2")

    return codes


def classify_failure(case: dict, grading: dict, session_dir: Path) -> dict | None:
    failures = _extract_failed_assertions(grading)
    summary = grading.get("summary") if isinstance(grading.get("summary"), dict) else {}
    authoritative = None
    if isinstance(summary, dict):
        rate = summary.get("authoritative_pass_rate", summary.get("pass_rate"))
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            authoritative = float(rate)
    if not failures and authoritative is not None and authoritative >= 1.0:
        return None
    if _grade_status(grading) == "PASS" and not failures:
        return None

    evidence = _failure_evidence(grading)
    codes = _explicit_failure_codes(case, grading, evidence)
    if not codes:
        if failures:
            codes.append("F7")
        elif evidence:
            codes.append("F12")
        else:
            codes.append("F11")

    unique_codes: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        unique_codes.append(code)

    primary = unique_codes[0]
    stage, fix, owner = FAILURE_FIXES[primary]
    secondary = unique_codes[1:]
    confidence = "high" if len(unique_codes) == 1 else "medium"
    return {
        "case_id": _case_id(case, "unknown"),
        "primary_code": primary,
        "secondary_codes": secondary,
        "lifecycle_stage": stage,
        "confidence": confidence,
        "evidence": [
            text
            for text in [
                _combined_text(case)[:200],
                evidence[:500],
            ]
            if text
        ],
        "recommended_owner": owner,
        "recommended_fix": fix,
    }


def analyze_failure_taxonomy(session_dir: Path, cases: list[dict]) -> dict:
    case_by_id = {
        _case_id(case, f"eval-{index}"): case
        for index, case in enumerate(cases, 1)
        if isinstance(case, dict)
    }
    failures = []
    code_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    owner_counts: Counter[str] = Counter()

    grading_files = [
        path
        for path in session_dir.rglob("grading.json")
        if "without_skill" not in path.parts
    ]
    for path in sorted(grading_files):
        grading = load_json(path)
        if not isinstance(grading, dict):
            continue
        eval_id = path.relative_to(session_dir).parts[0] if path.is_relative_to(session_dir) else path.parent.name
        case = case_by_id.get(str(grading.get("eval_id") or eval_id)) or case_by_id.get(eval_id)
        if not isinstance(case, dict):
            continue
        record = classify_failure(case, grading, session_dir)
        if not record:
            continue
        failures.append(record)
        code_counts[record["primary_code"]] += 1
        stage_counts[record["lifecycle_stage"]] += 1
        owner_counts[record["recommended_owner"]] += 1

    sorted_failures = sorted(failures, key=lambda item: (item["primary_code"], item["case_id"]))
    top_codes = [
        {"code": code, "count": count, "stage": FAILURE_FIXES[code][0], "fix": FAILURE_FIXES[code][1]}
        for code, count in code_counts.most_common()
    ]
    return {
        "status": "SKIPPED" if not failures else "OK",
        "total_failures": len(failures),
        "code_counts": dict(code_counts),
        "stage_counts": dict(stage_counts),
        "owner_counts": dict(owner_counts),
        "top_codes": top_codes,
        "failures": sorted_failures[:20],
    }


def _recommended_isolation(case: dict) -> str:
    risk_level = str(case.get("risk_level") or "").strip().upper()
    gate_level = str(case.get("gate_level") or "").strip().lower()
    security_family = str(case.get("security_family") or "").strip().lower()
    dimension = str(case.get("dimension") or case.get("category") or case.get("type") or "").strip().lower()
    text = _combined_text(case).lower()
    has_tool = _has_any_keyword(text, ("tool", "shell", "mcp", "api", "调用", "命令"))
    has_file = _has_any_keyword(text, ("file", "文件", "文档", "路径", "path"))
    multi_turn = any(case.get(key) not in (None, "", [], {}) for key in ("state_goal", "user_simulation_profile", "turns", "messages"))

    if security_family or risk_level == "P0":
        return "L4" if gate_level == "block" else "L3"
    if has_tool or has_file or any(field in case for field in ("tool_call_assertions", "tool_chain_expected", "expected_tool_args")):
        return "L2"
    if multi_turn or dimension in {"route", "e2e", "robustness"}:
        return "L1"
    return "L0"


def analyze_sampling_and_pollution(cases: list[dict]) -> dict:
    isolation_counts: Counter[str] = Counter()
    recommended_runs: Counter[str] = Counter()
    contamination_flags = []
    multi_turn_count = 0

    leakage_fields = (
        "golden_answer",
        "expected_output",
        "expected_answer",
        "answer",
        "solution",
        "reference_output",
        "oracle",
    )

    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            continue
        case_id = _case_id(case, f"eval-{index}")
        isolation = _recommended_isolation(case)
        isolation_counts[isolation] += 1

        risk_level = str(case.get("risk_level") or "").strip().upper()
        if risk_level == "P0":
            recommended_runs["P0"] = max(recommended_runs["P0"], 5)
        elif risk_level == "P1":
            recommended_runs["P1"] = max(recommended_runs["P1"], 3)
        else:
            recommended_runs["default"] = max(recommended_runs["default"], 2 if isolation in {"L2", "L3", "L4"} else 1)

        if any(case.get(key) not in (None, "", [], {}) for key in ("state_goal", "user_simulation_profile", "turns", "messages")):
            multi_turn_count += 1

        for field in leakage_fields:
            value = case.get(field)
            if value in (None, "", [], {}):
                continue
            contamination_flags.append(
                {
                    "case_id": case_id,
                    "type": "potential_answer_leakage",
                    "field": field,
                    "message": f"{field} should stay out of executor input and only feed grading",
                }
            )

        prompt_text = _combined_text(case).lower()
        if _has_any_keyword(prompt_text, ("http://", "https://", "webhook", "外联", "联网", "internet")):
            contamination_flags.append(
                {
                    "case_id": case_id,
                    "type": "external_access_risk",
                    "field": "prompt",
                    "message": "Prompt contains external-access hints; keep network disabled or whitelisted.",
                }
            )

    if not recommended_runs:
        recommended_runs["default"] = 1

    return {
        "status": "OK",
        "isolation_counts": dict(isolation_counts),
        "recommended_runs_by_risk": dict(recommended_runs),
        "multi_turn_case_count": multi_turn_count,
        "contamination_flags": contamination_flags[:20],
        "contamination_flag_count": len(contamination_flags),
    }


def _recommended_runs_for_case(case: dict, isolation: str) -> int:
    risk_level = str(case.get("risk_level") or "").strip().upper()
    if risk_level == "P0":
        return 5
    if risk_level == "P1":
        return 3
    return 2 if isolation in {"L2", "L3", "L4"} else 1


def build_sampling_plan(cases: list[dict], protocol: dict) -> dict:
    contamination_by_case: dict[str, list[dict]] = defaultdict(list)
    for flag in protocol.get("contamination_flags", []) if isinstance(protocol, dict) else []:
        if isinstance(flag, dict):
            contamination_by_case[str(flag.get("case_id") or "unknown")].append(
                {
                    "type": flag.get("type"),
                    "field": flag.get("field"),
                    "message": flag.get("message"),
                }
            )

    planned_cases = []
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            continue
        case_id = _case_id(case, f"eval-{index}")
        isolation = _recommended_isolation(case)
        recommended_runs = _recommended_runs_for_case(case, isolation)
        risk_level = str(case.get("risk_level") or "default").strip().upper() or "default"
        reason = f"{risk_level} risk, isolation={isolation}"
        if contamination_by_case.get(case_id):
            reason += ", contamination-control required"
        planned_cases.append(
            {
                "case_id": case_id,
                "risk_level": risk_level,
                "isolation": isolation,
                "recommended_runs": recommended_runs,
                "requires_clean_executor_input": bool(contamination_by_case.get(case_id)),
                "contamination_controls": contamination_by_case.get(case_id, []),
                "reason": reason,
            }
        )

    return {
        "status": "OK" if planned_cases else "SKIPPED",
        "artifact": "sampling-plan.json",
        "case_count": len(planned_cases),
        "total_recommended_runs": sum(item["recommended_runs"] for item in planned_cases),
        "isolation_counts": protocol.get("isolation_counts", {}) if isinstance(protocol, dict) else {},
        "recommended_runs_by_risk": protocol.get("recommended_runs_by_risk", {}) if isinstance(protocol, dict) else {},
        "cases": planned_cases,
    }


def build_sampling_result(session_dir: Path) -> dict:
    for candidate in (
        session_dir / "sampling-result.raw.json",
        session_dir / "repeat-run-result.json",
        session_dir / "repetition-results.json",
        session_dir / "run-matrix-result.json",
    ):
        data = load_json(candidate)
        if isinstance(data, dict):
            result = dict(data)
            result.setdefault("status", "OK")
            result.setdefault("artifact", "sampling-result.json")
            result.setdefault("source", candidate.name)
            return result
    return {
        "status": "PENDING",
        "artifact": "sampling-result.json",
        "source": None,
        "reason": "no repeated-run result artifact found yet",
        "expected_sources": [
            "sampling-result.raw.json",
            "repeat-run-result.json",
            "repetition-results.json",
            "run-matrix-result.json",
        ],
    }


def _parse_arguments(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_tool_call(value: dict) -> dict | None:
    if not isinstance(value, dict):
        return None
    function = value.get("function") if isinstance(value.get("function"), dict) else {}
    name = _first_text(
        value.get("tool"),
        value.get("name"),
        value.get("tool_name"),
        value.get("function_name"),
        function.get("name"),
    )
    if not name:
        return None
    args = _parse_arguments(
        value.get(
            "arguments",
            value.get(
                "args",
                value.get("input", value.get("parameters", function.get("arguments"))),
            ),
        )
    )
    return {"tool": name, "args": args, "raw": value}


def _extract_tool_calls_from_json(value) -> list[dict]:
    calls: list[dict] = []
    if isinstance(value, list):
        for item in value:
            calls.extend(_extract_tool_calls_from_json(item))
        return calls
    if not isinstance(value, dict):
        return calls

    normalized = _normalize_tool_call(value)
    if normalized:
        calls.append(normalized)
    for key in ("tool_calls", "toolCalls", "calls", "items", "steps", "events"):
        if key in value:
            calls.extend(_extract_tool_calls_from_json(value.get(key)))
    return calls


def _parse_kv_args(text: str) -> dict:
    args = {}
    for part in text.split(","):
        if "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip().strip("'\"")
        if not key:
            continue
        parsed = raw_value
        if re.fullmatch(r"-?\d+", raw_value):
            parsed = int(raw_value)
        else:
            try:
                parsed = float(raw_value)
            except ValueError:
                pass
        args[key] = parsed
    return args


def _extract_tool_calls_from_text(text: str) -> list[dict]:
    calls = []
    for match in re.finditer(r"\b([A-Za-z_][\w.-]*)\s*\(([^()]*)\)", text or ""):
        calls.append({"tool": match.group(1), "args": _parse_kv_args(match.group(2)), "raw": match.group(0)})
    return calls


def _tool_call_candidates(session_dir: Path, case_id: str) -> list[Path]:
    names = (
        "tool-calls.json",
        "tool_calls.json",
        "actual-tool-calls.json",
        "actual_tool_calls.json",
        "transcript.json",
        "transcript.md",
    )
    direct_dirs = [
        session_dir / case_id,
        session_dir / case_id / "outputs",
        session_dir / case_id / "with_skill" / "outputs",
        session_dir / case_id / "old_skill" / "outputs",
    ]
    candidates: list[Path] = []
    for directory in direct_dirs:
        for name in names:
            candidates.append(directory / name)
    for name in names:
        for path in session_dir.rglob(name):
            if case_id in path.parts:
                candidates.append(path)
    return list(dict.fromkeys(candidates))


def _load_actual_tool_calls_for_case(session_dir: Path, case_id: str) -> tuple[list[dict], str | None]:
    for candidate in _tool_call_candidates(session_dir, case_id):
        if not candidate.exists():
            continue
        if candidate.suffix.lower() == ".json":
            calls = _extract_tool_calls_from_json(load_json(candidate))
        else:
            calls = _extract_tool_calls_from_text(candidate.read_text(encoding="utf-8", errors="replace"))
        if calls:
            return calls, str(candidate.relative_to(session_dir))
    return [], None


def _normalize_tool_assertions(case: dict) -> list[dict]:
    assertions = []
    for item in _as_list(case.get("tool_call_assertions")):
        if isinstance(item, dict):
            tool_name = _first_text(item.get("tool"), item.get("name"), item.get("tool_name"))
            assertions.append(
                {
                    "tool": tool_name or None,
                    "expected_args": item.get("expected_args", item.get("args", item.get("arguments", {}))),
                    "arg_match": str(item.get("arg_match") or item.get("match") or "subset").lower(),
                    "required": item.get("required", True) is not False,
                }
            )
        elif isinstance(item, str) and item.strip():
            assertions.append({"tool": item.strip(), "expected_args": {}, "arg_match": "subset", "required": True})

    expected_args = case.get("expected_tool_args")
    if isinstance(expected_args, dict):
        for key, value in expected_args.items():
            if isinstance(value, dict):
                assertions.append({"tool": str(key), "expected_args": value, "arg_match": "subset", "required": True})

    for item in _as_list(case.get("tool_chain_expected")) + _as_list(case.get("tool_sequence_expected")):
        if isinstance(item, str) and item.strip():
            assertions.append({"tool": item.strip(), "expected_args": {}, "arg_match": "sequence", "required": True})
    return assertions


def _args_match(actual_args: dict, expected_args: dict, match_mode: str) -> bool:
    if not expected_args:
        return True
    if match_mode == "exact":
        return actual_args == expected_args
    for key, expected_value in expected_args.items():
        if actual_args.get(key) != expected_value:
            return False
    return True


def analyze_tool_assertion_score(session_dir: Path, cases: list[dict]) -> dict:
    case_results = []
    total = 0
    passed = 0
    executable_cases = 0

    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            continue
        assertions = _normalize_tool_assertions(case)
        if not assertions:
            continue
        case_id = _case_id(case, f"eval-{index}")
        actual_calls, source = _load_actual_tool_calls_for_case(session_dir, case_id)
        expected_count = len(assertions)
        total += expected_count
        case_passed = 0
        details = []

        if actual_calls:
            executable_cases += 1
            tool_names = [call.get("tool") for call in actual_calls]
            sequence_cursor = 0
            for assertion in assertions:
                expected_tool = assertion.get("tool")
                expected_args = assertion.get("expected_args") if isinstance(assertion.get("expected_args"), dict) else {}
                match_mode = assertion.get("arg_match") or "subset"
                matched_call = None
                if match_mode == "sequence" and expected_tool:
                    for cursor in range(sequence_cursor, len(actual_calls)):
                        if actual_calls[cursor].get("tool") == expected_tool:
                            matched_call = actual_calls[cursor]
                            sequence_cursor = cursor + 1
                            break
                elif expected_tool:
                    for call in actual_calls:
                        if call.get("tool") == expected_tool and _args_match(call.get("args", {}), expected_args, match_mode):
                            matched_call = call
                            break
                elif actual_calls:
                    matched_call = actual_calls[0]

                ok = matched_call is not None
                if ok:
                    case_passed += 1
                    passed += 1
                details.append(
                    {
                        "tool": expected_tool,
                        "arg_match": match_mode,
                        "expected_args": expected_args,
                        "passed": ok,
                        "actual_tools": tool_names[:10],
                    }
                )
        else:
            details.append(
                {
                    "passed": None,
                    "message": "missing actual tool-call artifact",
                    "expected_tools": [item.get("tool") for item in assertions if item.get("tool")],
                }
            )

        case_results.append(
            {
                "case_id": case_id,
                "risk_level": str(case.get("risk_level") or "").strip().upper() or None,
                "status": "PASSED" if actual_calls and case_passed == expected_count else ("FAILED" if actual_calls else "NEEDS_EXECUTION_ARTIFACT"),
                "expected_assertions": expected_count,
                "passed_assertions": case_passed if actual_calls else None,
                "actual_call_count": len(actual_calls),
                "source": source,
                "details": details,
            }
        )

    if total == 0:
        status = "SKIPPED"
        pass_rate = None
    elif executable_cases == 0:
        status = "NEEDS_EXECUTION_ARTIFACT"
        pass_rate = None
    else:
        status = "OK"
        pass_rate = round(passed / total, 4) if total else None

    return {
        "status": status,
        "total": total,
        "passed": passed if executable_cases else None,
        "pass_rate": pass_rate,
        "cases_with_expectations": len(case_results),
        "cases_with_actual_calls": executable_cases,
        "cases": case_results[:50],
        "expected_artifacts": [
            "<case_id>/tool-calls.json",
            "<case_id>/outputs/tool-calls.json",
            "<case_id>/with_skill/outputs/tool-calls.json",
            "<case_id>/transcript.md",
        ],
    }


def write_sampling_artifacts(session_dir: Path, analysis: dict) -> None:
    sampling_plan = analysis.get("sampling_plan") if isinstance(analysis, dict) else None
    sampling_result = analysis.get("sampling_result") if isinstance(analysis, dict) else None
    if isinstance(sampling_plan, dict):
        save_json(session_dir / "sampling-plan.json", sampling_plan)
    if isinstance(sampling_result, dict):
        save_json(session_dir / "sampling-result.json", sampling_result)


def analyze_grader_calibration(session_dir: Path) -> dict:
    candidates = [
        session_dir / "grader-calibration.json",
        session_dir / "judge-calibration-result.json",
        session_dir / "grader-confidence.json",
        session_dir / "human-review-sample.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        data = load_json(candidate)
        if not isinstance(data, dict):
            continue
        items = data.get("items") if isinstance(data.get("items"), list) else data.get("samples")
        if isinstance(items, list):
            human_scores = []
            judge_scores = []
            severe_miss = 0
            evidence_coverage = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                human = item.get("expected_score", item.get("human_score", item.get("human")))
                judge = item.get("judge_score", item.get("score", item.get("predicted_score")))
                if isinstance(human, (int, float)) and isinstance(judge, (int, float)):
                    human_scores.append(float(human))
                    judge_scores.append(float(judge))
                    if abs(float(human) - float(judge)) >= 2:
                        severe_miss += 1
                if item.get("evidence"):
                    evidence_coverage += 1
            total = len(items)
            agreement = None
            if human_scores:
                close = sum(1 for human, judge in zip(human_scores, judge_scores) if abs(human - judge) <= 1)
                agreement = close / len(human_scores)
            severe_rate = severe_miss / total if total else None
            evidence_rate = evidence_coverage / total if total else None
            return {
                "status": "OK",
                "source": str(candidate.name),
                "sample_count": total,
                "agreement_rate": round(agreement, 4) if agreement is not None else None,
                "severe_miss_rate": round(severe_rate, 4) if severe_rate is not None else None,
                "evidence_coverage_rate": round(evidence_rate, 4) if evidence_rate is not None else None,
                "template": {
                    "calibration_id": "<id>",
                    "input": "<case input + response>",
                    "expected_score": 0,
                    "must_fail_reasons": [],
                    "must_pass_reasons": [],
                    "risk_level": "P0",
                    "last_reviewed_by": "<reviewer>",
                    "last_reviewed_at": "<iso8601>",
                },
            }
        direct_rate = _first_number(
            data.get("agreement_rate"),
            data.get("judge_agreement"),
            data.get("judge_accuracy"),
        )
        severe_rate = _first_number(data.get("severe_miss_rate"))
        evidence_rate = _first_number(data.get("evidence_coverage_rate"))
        if direct_rate is not None or severe_rate is not None or evidence_rate is not None:
            return {
                "status": "OK",
                "source": str(candidate.name),
                "sample_count": int(_first_number(data.get("sample_count"), data.get("total"), data.get("count")) or 0),
                "agreement_rate": round(direct_rate, 4) if direct_rate is not None else None,
                "severe_miss_rate": round(severe_rate, 4) if severe_rate is not None else None,
                "evidence_coverage_rate": round(evidence_rate, 4) if evidence_rate is not None else None,
                "template": {
                    "calibration_id": "<id>",
                    "input": "<case input + response>",
                    "expected_score": 0,
                    "must_fail_reasons": [],
                    "must_pass_reasons": [],
                    "risk_level": "P0",
                    "last_reviewed_by": "<reviewer>",
                    "last_reviewed_at": "<iso8601>",
                },
            }
    return {
        "status": "MISSING",
        "source": None,
        "sample_count": 0,
        "agreement_rate": None,
        "severe_miss_rate": None,
        "evidence_coverage_rate": None,
        "template": {
            "calibration_id": "<id>",
            "input": "<case input + response>",
            "expected_score": 0,
            "must_fail_reasons": [],
            "must_pass_reasons": [],
            "risk_level": "P0",
            "last_reviewed_by": "<reviewer>",
            "last_reviewed_at": "<iso8601>",
        },
    }


def analyze_benchmark_adapters(cases: list[dict]) -> dict:
    adapter_cases: dict[str, list[str]] = {name: [] for name in ADAPTER_NAMES}
    case_mappings = []

    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict):
            continue
        case_id = _case_id(case, f"eval-{index}")
        adapters = []
        text = _combined_text(case).lower()
        dimension = str(case.get("dimension") or case.get("category") or case.get("type") or "").strip().lower()

        if case.get("assertions") or case.get("expected_output") or case.get("expected_answer"):
            adapters.append("openai_evals_style")
        if any(case.get(key) not in (None, "", [], {}) for key in ("tool_call_assertions", "expected_tool_args", "tool_chain_expected")) or _has_any_keyword(text, ("tool", "调用", "参数", "sequence")):
            adapters.append("bfcl_style")
        if any(case.get(key) not in (None, "", [], {}) for key in ("tool_chain_expected", "tool_sequence_expected", "tool_sequence_score")):
            adapters.append("toolbench_style")
        if any(case.get(key) not in (None, "", [], {}) for key in ("environment", "task_completion_score")):
            adapters.append("agentbench_style")
        if case.get("real_world_task") or dimension in {"e2e", "real_world"}:
            adapters.append("gaia_style")
        if any(case.get(key) not in (None, "", [], {}) for key in ("user_simulation_profile", "state_goal", "turns", "messages")):
            adapters.append("tau_bench_style")
        if any(case.get(key) not in (None, "", [], {}) for key in ("time_horizon_bucket", "checkpoint_required")):
            adapters.append("metr_style")
        if case.get("security_family") or dimension == "security":
            adapters.extend(["agentdojo_style", "owasp_llm_top10"])

        adapters = list(dict.fromkeys(adapters))
        if adapters:
            case_mappings.append({"case_id": case_id, "adapters": adapters})
            for adapter in adapters:
                adapter_cases.setdefault(adapter, []).append(case_id)

    coverage = sum(1 for cases_for_adapter in adapter_cases.values() if cases_for_adapter)
    return {
        "status": "OK" if case_mappings else "SKIPPED",
        "adapter_coverage_rate": round(coverage / len(ADAPTER_NAMES), 4) if ADAPTER_NAMES else None,
        "adapter_counts": {name: len(ids) for name, ids in adapter_cases.items()},
        "mapped_cases": case_mappings[:20],
        "missing_adapters": [name for name, ids in adapter_cases.items() if not ids],
    }


def collect_methodology_v2(session_dir: Path, session: dict | None = None) -> dict:
    session_data = session if isinstance(session, dict) else load_json(session_dir / "session.json") or {}
    cases, source = _load_cases(session_dir, session_data)
    if not cases:
        return {
            "status": "SKIPPED",
            "session_dir": str(session_dir),
            "source": source,
            "reason": "no eval cases found",
        }

    skill_name = str(session_data.get("skill") or session_data.get("skill_name") or session_dir.name)
    route_eval = analyze_route_evaluation(cases, skill_name)
    failure_taxonomy = analyze_failure_taxonomy(session_dir, cases)
    contamination = analyze_sampling_and_pollution(cases)
    sampling_plan = build_sampling_plan(cases, contamination)
    sampling_result = build_sampling_result(session_dir)
    tool_assertion_score = analyze_tool_assertion_score(session_dir, cases)
    calibration = analyze_grader_calibration(session_dir)
    benchmark = analyze_benchmark_adapters(cases)

    route_accuracy = route_eval.get("top1_accuracy")
    route_gate = route_eval.get("gate_recommendation")
    failure_top = failure_taxonomy.get("top_codes", [])[:3]
    failure_primary = failure_top[0]["code"] if failure_top else None
    contamination_count = contamination.get("contamination_flag_count", 0)
    tool_assertion_pass_rate = tool_assertion_score.get("pass_rate")
    calibration_status = calibration.get("status")
    benchmark_coverage = benchmark.get("adapter_coverage_rate")

    overall = "pass"
    if route_gate in {"block", "block_no_route_precision"}:
        overall = "warn"
    if failure_primary == "F8" or contamination_count >= 5:
        overall = "block"
    if calibration_status == "MISSING":
        overall = "warn" if overall == "pass" else overall
    if benchmark_coverage is not None and benchmark_coverage < 0.5:
        overall = "warn" if overall == "pass" else overall
    if tool_assertion_score.get("status") == "OK" and tool_assertion_pass_rate is not None and tool_assertion_pass_rate < 1.0:
        overall = "warn" if overall == "pass" else overall

    return {
        "status": "OK",
        "session_dir": str(session_dir),
        "source": source,
        "skill": skill_name,
        "route_eval": route_eval,
        "failure_taxonomy": failure_taxonomy,
        "pollution_protocol": contamination,
        "sampling_plan": sampling_plan,
        "sampling_result": sampling_result,
        "tool_assertion_score": tool_assertion_score,
        "grader_calibration": calibration,
        "benchmark_adapters": benchmark,
        "summary": {
            "route_status": route_gate,
            "route_accuracy": route_accuracy,
            "failure_primary": failure_primary,
            "contamination_flag_count": contamination_count,
            "tool_assertion_pass_rate": tool_assertion_pass_rate,
            "calibration_status": calibration_status,
            "benchmark_coverage_rate": benchmark_coverage,
            "overall_recommendation": overall,
        },
    }


def _first_number(*values):
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            return float(value)
        if isinstance(value, str):
            try:
                parsed = float(value)
                if math.isfinite(parsed):
                    return parsed
            except ValueError:
                continue
    return None


def render_markdown(analysis: dict) -> str:
    route = analysis.get("route_eval", {}) if isinstance(analysis, dict) else {}
    failures = analysis.get("failure_taxonomy", {}) if isinstance(analysis, dict) else {}
    pollution = analysis.get("pollution_protocol", {}) if isinstance(analysis, dict) else {}
    sampling_plan = analysis.get("sampling_plan", {}) if isinstance(analysis, dict) else {}
    tool_score = analysis.get("tool_assertion_score", {}) if isinstance(analysis, dict) else {}
    calibration = analysis.get("grader_calibration", {}) if isinstance(analysis, dict) else {}
    benchmark = analysis.get("benchmark_adapters", {}) if isinstance(analysis, dict) else {}
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}

    lines = [
        "### Methodology V2",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Route status | {route.get('gate_recommendation', 'N/A')} ({route.get('prediction_mode', 'N/A')}) |",
        f"| Route accuracy | {route.get('top1_accuracy', 'N/A')} |",
        f"| Route cases | {route.get('route_case_total', 0)} |",
        f"| Failure primary | {summary.get('failure_primary', 'N/A')} |",
        f"| Failure count | {failures.get('total_failures', 0)} |",
        f"| Contamination flags | {pollution.get('contamination_flag_count', 0)} |",
        f"| Sampling plan | {sampling_plan.get('case_count', 0)} cases / {sampling_plan.get('total_recommended_runs', 0)} runs |",
        f"| Tool assertions | {tool_score.get('status', 'N/A')} / {tool_score.get('pass_rate', 'N/A')} |",
        f"| Calibration | {calibration.get('status', 'N/A')} |",
        f"| Benchmark coverage | {benchmark.get('adapter_coverage_rate', 'N/A')} |",
        f"| Overall recommendation | {summary.get('overall_recommendation', 'N/A')} |",
    ]

    route_matrix = route.get("probe_confusion_matrix") or {}
    if isinstance(route_matrix, dict) and route_matrix.get("rows"):
        lines.extend(
            [
                "",
                "Route probe confusion matrix:",
                "",
                "| Expected | " + " | ".join(route_matrix.get("labels", [])) + " |",
                "|---|" + "|".join("---" for _ in route_matrix.get("labels", [])) + "|",
            ]
        )
        for row in route_matrix.get("rows", []):
            if not isinstance(row, dict):
                continue
            counts = row.get("counts", {})
            lines.append(
                "| "
                + str(row.get("expected", "N/A"))
                + " | "
                + " | ".join(str(counts.get(label, 0)) for label in route_matrix.get("labels", []))
                + " |"
            )

    top_codes = failures.get("top_codes", [])
    if top_codes:
        lines.extend(["", "Failure taxonomy:", "", "| Code | Count | Stage | Fix |", "|---|---:|---|---|"])
        for item in top_codes[:8]:
            lines.append(
                f"| {item.get('code', 'N/A')} | {item.get('count', 0)} | {item.get('stage', 'N/A')} | {item.get('fix', 'N/A')} |"
            )

    if calibration.get("status") == "MISSING":
        lines.extend(["", "Calibration artifact is missing; add `grader-calibration.json` or `judge-calibration-result.json`."])
    elif calibration.get("status") == "OK":
        lines.extend(
            [
                "",
                f"Calibration: agreement={calibration.get('agreement_rate', 'N/A')}, severe_miss={calibration.get('severe_miss_rate', 'N/A')}, evidence={calibration.get('evidence_coverage_rate', 'N/A')}",
            ]
        )

    if pollution.get("contamination_flags"):
        lines.extend(["", "Sampling / Contamination:"])
        for flag in pollution.get("contamination_flags", [])[:6]:
            if isinstance(flag, dict):
                lines.append(f"- {flag.get('case_id', 'unknown')}: {flag.get('message', '')}")

    if tool_score.get("cases"):
        lines.extend(["", "Tool assertion score:"])
        for item in tool_score.get("cases", [])[:6]:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('case_id', 'unknown')}: {item.get('status', 'N/A')} "
                    f"({item.get('passed_assertions', 'N/A')}/{item.get('expected_assertions', 'N/A')})"
                )

    if benchmark.get("adapter_counts"):
        lines.extend(["", "Benchmark adapters:", ""])
        for name, count in benchmark.get("adapter_counts", {}).items():
            lines.append(f"- {name}: {count}")

    return "\n".join(lines)


def _table_row(title: str, value: str) -> str:
    return f"<tr><th>{title}</th><td>{value}</td></tr>"


def render_html(analysis: dict) -> str:
    route = analysis.get("route_eval", {}) if isinstance(analysis, dict) else {}
    failures = analysis.get("failure_taxonomy", {}) if isinstance(analysis, dict) else {}
    pollution = analysis.get("pollution_protocol", {}) if isinstance(analysis, dict) else {}
    sampling_plan = analysis.get("sampling_plan", {}) if isinstance(analysis, dict) else {}
    tool_score = analysis.get("tool_assertion_score", {}) if isinstance(analysis, dict) else {}
    calibration = analysis.get("grader_calibration", {}) if isinstance(analysis, dict) else {}
    benchmark = analysis.get("benchmark_adapters", {}) if isinstance(analysis, dict) else {}
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}

    route_rows = ""
    for title, value in [
        ("Route status", f"{route.get('gate_recommendation', 'N/A')} ({route.get('prediction_mode', 'N/A')})"),
        ("Route accuracy", route.get("top1_accuracy", "N/A")),
        ("Route cases", route.get("route_case_total", 0)),
        ("Failure primary", summary.get("failure_primary", "N/A")),
        ("Failure count", failures.get("total_failures", 0)),
        ("Contamination flags", pollution.get("contamination_flag_count", 0)),
        ("Sampling plan", f"{sampling_plan.get('case_count', 0)} cases / {sampling_plan.get('total_recommended_runs', 0)} runs"),
        ("Tool assertions", f"{tool_score.get('status', 'N/A')} / {tool_score.get('pass_rate', 'N/A')}"),
        ("Calibration", calibration.get("status", "N/A")),
        ("Benchmark coverage", benchmark.get("adapter_coverage_rate", "N/A")),
        ("Overall recommendation", summary.get("overall_recommendation", "N/A")),
    ]:
        route_rows += _table_row(title, str(value))

    route_matrix_html = ""
    route_matrix = route.get("probe_confusion_matrix") or {}
    if isinstance(route_matrix, dict) and route_matrix.get("rows"):
        headers = "".join(f"<th>{label}</th>" for label in route_matrix.get("labels", []))
        body = ""
        for row in route_matrix.get("rows", []):
            if not isinstance(row, dict):
                continue
            counts = row.get("counts", {})
            values = "".join(f"<td>{counts.get(label, 0)}</td>" for label in route_matrix.get("labels", []))
            body += f"<tr><th>{row.get('expected', 'N/A')}</th>{values}</tr>"
        route_matrix_html = f"""
  <h4>Route Probe Confusion Matrix</h4>
  <table>
    <tr><th>Expected \\ Predicted</th>{headers}</tr>
    {body}
  </table>
"""

    top_codes = failures.get("top_codes", [])
    failure_rows = ""
    for item in top_codes[:8]:
        failure_rows += f"<tr><td>{item.get('code', 'N/A')}</td><td>{item.get('count', 0)}</td><td>{item.get('stage', 'N/A')}</td><td>{item.get('fix', 'N/A')}</td></tr>"
    failure_html = f"""
  <h4>Failure Taxonomy</h4>
  <table>
    <tr><th>Code</th><th>Count</th><th>Stage</th><th>Fix</th></tr>
    {failure_rows or '<tr><td colspan=\"4\">none</td></tr>'}
  </table>
"""

    contamination_items = "".join(
        f"<li>{item.get('case_id', 'unknown')}: {item.get('message', '')}</li>"
        for item in pollution.get("contamination_flags", [])[:8]
        if isinstance(item, dict)
    ) or "<li>none</li>"

    tool_items = "".join(
        f"<li>{item.get('case_id', 'unknown')}: {item.get('status', 'N/A')} ({item.get('passed_assertions', 'N/A')}/{item.get('expected_assertions', 'N/A')})</li>"
        for item in tool_score.get("cases", [])[:8]
        if isinstance(item, dict)
    ) or "<li>none</li>"

    benchmark_rows = "".join(
        f"<tr><td>{name}</td><td>{count}</td></tr>"
        for name, count in benchmark.get("adapter_counts", {}).items()
    ) or "<tr><td colspan=\"2\">none</td></tr>"

    agreement_text = calibration.get("agreement_rate")
    severe_text = calibration.get("severe_miss_rate")
    evidence_text = calibration.get("evidence_coverage_rate")

    return f"""
  <h3>Methodology V2</h3>
  <table>
    {route_rows}
  </table>
  {route_matrix_html}
  {failure_html}
  <h4>Sampling / Contamination</h4>
  <p>Isolation counts: {json.dumps(pollution.get('isolation_counts', {}), ensure_ascii=False)}</p>
  <p>Recommended runs: {json.dumps(pollution.get('recommended_runs_by_risk', {}), ensure_ascii=False)}</p>
  <ul>{contamination_items}</ul>
  <h4>Tool Assertion Score</h4>
  <p>Status: {tool_score.get('status', 'N/A')}, pass_rate={tool_score.get('pass_rate', 'N/A')}</p>
  <ul>{tool_items}</ul>
  <h4>Grader Calibration</h4>
  <p>Status: {calibration.get('status', 'N/A')}, agreement={agreement_text if agreement_text is not None else 'N/A'}, severe_miss={severe_text if severe_text is not None else 'N/A'}, evidence={evidence_text if evidence_text is not None else 'N/A'}</p>
  <h4>Benchmark Adapters</h4>
  <p>Coverage: {benchmark.get('adapter_coverage_rate', 'N/A')}</p>
  <table>
    <tr><th>Adapter</th><th>Count</th></tr>
    {benchmark_rows}
  </table>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry methodology V2 analyzer")
    parser.add_argument("session_dir", help="Session directory containing evals.json and grading files")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_dir = Path(args.session_dir).expanduser().resolve()
    session = load_json(session_dir / "session.json") or {}
    payload = collect_methodology_v2(session_dir, session)
    write_sampling_artifacts(session_dir, payload)
    if args.output:
        save_json(Path(args.output), payload)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload.get("summary", {})
        print(
            "methodology v2: "
            f"route={summary.get('route_status', 'N/A')} "
            f"failure={summary.get('failure_primary', 'N/A')} "
            f"contamination={summary.get('contamination_flag_count', 'N/A')} "
            f"tool={summary.get('tool_assertion_pass_rate', 'N/A')} "
            f"calibration={summary.get('calibration_status', 'N/A')} "
            f"benchmark={summary.get('benchmark_coverage_rate', 'N/A')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
