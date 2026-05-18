#!/usr/bin/env python3
"""SkillSentry deterministic gate.

Reads a session directory and emits a stable grade/verdict JSON. The gate is
conservative and compatible with historical grading formats.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

GRADE_THRESHOLDS = [("S", 0.95), ("A", 0.90), ("B", 0.80), ("C", 0.70)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry deterministic gate")
    parser.add_argument("session_dir", help="Session/workspace directory")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--output", default=None, help="Optional gate-result.json path")
    parser.add_argument("--expect", default=None, help="Optional expected JSON fixture to compare against")
    parser.add_argument("--tolerance", type=float, default=0.0001, help="Numeric comparison tolerance for --expect")
    return parser.parse_args()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def first_number(*values):
    for value in values:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if math.isfinite(float(value)):
                return float(value)
        if isinstance(value, str):
            try:
                parsed = float(value)
                if math.isfinite(parsed):
                    return parsed
            except ValueError:
                pass
    return None


def bool_value(item: dict) -> bool:
    if "passed" in item or "pass" in item:
        return bool(item.get("passed", item.get("pass", False)))
    result = str(item.get("result", "")).strip().lower()
    if result in {"pass", "passed", "true", "ok", "success"}:
        return True
    if result in {"fail", "failed", "false", "error"}:
        return False
    return False


def precision_value(item: dict) -> str:
    precision = str(item.get("precision") or "").strip()
    if precision in {"exact_match", "semantic", "existence"}:
        return precision
    item_type = str(item.get("type") or "").strip()
    if item_type in {"exact_match", "semantic", "existence"}:
        return item_type
    return precision or item_type


def empty_counts() -> dict:
    return {
        "exact_pass": 0,
        "exact_total": 0,
        "semantic_pass": 0,
        "semantic_total": 0,
        "existence_pass": 0,
        "existence_total": 0,
        "total_pass": 0,
        "total_total": 0,
        "per_eval_rates": [],
    }


def add_counts(target: dict, source: dict) -> None:
    for key in (
        "exact_pass",
        "exact_total",
        "semantic_pass",
        "semantic_total",
        "existence_pass",
        "existence_total",
        "total_pass",
        "total_total",
    ):
        target[key] += int(source.get(key, 0))
    target["per_eval_rates"].extend(source.get("per_eval_rates", []))


def counts_from_expectations(expectations: list[dict]) -> dict:
    counts = empty_counts()
    for item in expectations:
        precision = precision_value(item)
        passed = bool_value(item)
        counts["total_total"] += 1
        counts["total_pass"] += 1 if passed else 0
        if precision == "exact_match":
            counts["exact_total"] += 1
            counts["exact_pass"] += 1 if passed else 0
        elif precision == "semantic":
            counts["semantic_total"] += 1
            counts["semantic_pass"] += 1 if passed else 0
        elif precision == "existence":
            counts["existence_total"] += 1
            counts["existence_pass"] += 1 if passed else 0
    if counts["total_total"]:
        counts["per_eval_rates"].append(counts["total_pass"] / counts["total_total"])
    return counts


def counts_from_precision_breakdown(summary: dict) -> dict:
    counts = empty_counts()
    breakdown = summary.get("precision_breakdown", {})
    for precision, prefix in (
        ("exact_match", "exact"),
        ("semantic", "semantic"),
        ("existence", "existence"),
    ):
        item = breakdown.get(precision, {})
        total = int(first_number(item.get("total")) or 0)
        passed = int(first_number(item.get("passed"), item.get("pass")) or 0)
        counts[f"{prefix}_total"] = total
        counts[f"{prefix}_pass"] = passed
    total = int(first_number(summary.get("total")) or 0)
    passed = int(first_number(summary.get("passed"), summary.get("pass")) or 0)
    if total == 0:
        total = counts["exact_total"] + counts["semantic_total"] + counts["existence_total"]
        passed = counts["exact_pass"] + counts["semantic_pass"] + counts["existence_pass"]
    counts["total_total"] = total
    counts["total_pass"] = passed
    if total:
        counts["per_eval_rates"].append(passed / total)
    return counts


def counts_from_grading(data: dict) -> dict:
    if not isinstance(data, dict):
        return empty_counts()

    if isinstance(data.get("aggregate"), dict):
        aggregate = data["aggregate"]
        counts = empty_counts()
        counts["exact_pass"] = int(first_number(aggregate.get("exact_match_passed")) or 0)
        counts["exact_total"] = int(first_number(aggregate.get("exact_match_assertions")) or 0)
        counts["semantic_total"] = int(first_number(aggregate.get("semantic_assertions")) or 0)
        semantic_rate = first_number(aggregate.get("semantic_pass_rate"))
        if semantic_rate is not None:
            counts["semantic_pass"] = round(semantic_rate * counts["semantic_total"])
        counts["existence_total"] = int(first_number(aggregate.get("existence_assertions")) or 0)
        existence_rate = first_number(aggregate.get("existence_pass_rate"))
        if existence_rate is not None:
            counts["existence_pass"] = round(existence_rate * counts["existence_total"])
        counts["total_total"] = int(first_number(aggregate.get("total_assertions")) or 0)
        if counts["total_total"] == 0:
            counts["total_total"] = counts["exact_total"] + counts["semantic_total"] + counts["existence_total"]
        counts["total_pass"] = counts["exact_pass"] + counts["semantic_pass"] + counts["existence_pass"]
        rate = first_number(aggregate.get("exact_match_pass_rate"))
        if rate is not None:
            counts["per_eval_rates"].append(rate)
        return counts

    if isinstance(data.get("summary"), dict) and isinstance(data["summary"].get("precision_breakdown"), dict):
        return counts_from_precision_breakdown(data["summary"])

    if isinstance(data.get("expectations"), list):
        return counts_from_expectations(data["expectations"])

    if isinstance(data.get("assertions"), list):
        return counts_from_expectations(data["assertions"])

    if isinstance(data.get("runs"), dict):
        counts = empty_counts()
        for run in data["runs"].values():
            if isinstance(run.get("assertions"), list):
                add_counts(counts, counts_from_expectations(run["assertions"]))
        return counts

    if isinstance(data.get("cases"), dict):
        counts = empty_counts()
        for case in data["cases"].values():
            if isinstance(case, dict) and isinstance(case.get("expectations"), list):
                add_counts(counts, counts_from_expectations(case["expectations"]))
        return counts

    return empty_counts()


def rate_from_grading(data: dict) -> float | None:
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    rate = first_number(summary.get("authoritative_pass_rate"), summary.get("pass_rate"))
    if rate is not None:
        return rate
    counts = counts_from_grading(data)
    if counts["exact_total"]:
        return counts["exact_pass"] / counts["exact_total"]
    if counts["total_total"]:
        return counts["total_pass"] / counts["total_total"]
    return None


def find_grading_files(session_dir: Path) -> list[Path]:
    files = []
    for path in session_dir.rglob("grading.json"):
        parts = set(path.parts)
        if "without_skill" in parts:
            continue
        files.append(path)
    for name in ("grading-summary.json", "grading-all.json"):
        candidate = session_dir / name
        if candidate.exists():
            files.append(candidate)
    return sorted(set(files))


def collect_with_skill_counts(session_dir: Path) -> tuple[dict, list[str]]:
    total = empty_counts()
    sources = []
    for path in find_grading_files(session_dir):
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        counts = counts_from_grading(data)
        if counts["total_total"] or counts["exact_total"]:
            add_counts(total, counts)
            sources.append(str(path.relative_to(session_dir)))
    return total, sources


def collect_delta(session_dir: Path) -> dict:
    evals = load_json(session_dir / "evals.json")
    skipped_declared = 0
    if isinstance(evals, list):
        skipped_declared = sum(1 for item in evals if isinstance(item, dict) and item.get("skip_without_skill"))

    deltas = []
    missing_without = 0
    for eval_dir in sorted(p for p in session_dir.glob("eval-*") if p.is_dir()):
        with_candidates = [
            eval_dir / "with_skill" / "outputs" / "grading.json",
            eval_dir / "with_skill" / "grading.json",
            eval_dir / "grading.json",
        ]
        without_candidates = [
            eval_dir / "without_skill" / "outputs" / "grading.json",
            eval_dir / "without_skill" / "grading.json",
        ]
        with_data = next((load_json(p) for p in with_candidates if p.exists()), None)
        without_data = next((load_json(p) for p in without_candidates if p.exists()), None)
        if not isinstance(with_data, dict):
            continue
        if not isinstance(without_data, dict):
            missing_without += 1
            continue
        with_rate = rate_from_grading(with_data)
        without_rate = rate_from_grading(without_data)
        if with_rate is not None and without_rate is not None:
            deltas.append(with_rate - without_rate)

    if deltas:
        value = sum(deltas) / len(deltas)
        if missing_without or skipped_declared:
            status = "partial"
        elif value > 0:
            status = "computed_positive"
        elif value < 0:
            status = "computed_negative"
        else:
            status = "computed_zero"
        return {
            "status": status,
            "value": round(value, 4),
            "computed_evals": len(deltas),
            "skipped_evals": skipped_declared + missing_without,
        }

    return {
        "status": "N/A",
        "value": None,
        "computed_evals": 0,
        "skipped_evals": skipped_declared + missing_without,
        "reason": "no comparable without_skill grading found",
    }


def collect_vetoes(session: dict, grading_files: list[Path]) -> list[dict]:
    vetoes = []
    for item in session.get("grader_report", {}).get("vetoes", []) or []:
        vetoes.append({"source": "session.grader_report", "detail": item})
    for item in session.get("verdict", {}).get("vetoes", []) or []:
        vetoes.append({"source": "session.verdict", "detail": item})
    for path in grading_files:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        aggregate = data.get("aggregate", {})
        if isinstance(aggregate, dict):
            for warning in aggregate.get("hil_warnings", []) or []:
                vetoes.append({"source": str(path), "detail": warning, "type": "hil_warning"})
        for key in ("vetoes", "critical_violations"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    vetoes.append({"source": str(path), "detail": item, "type": key})
            elif isinstance(value, int) and value > 0:
                vetoes.append({"source": str(path), "detail": f"{key}={value}", "type": key})
    return vetoes


def collect_ifr(session: dict, grading_files: list[Path]) -> dict:
    candidates = [
        session.get("verdict", {}).get("ifr") if isinstance(session.get("verdict"), dict) else None,
        session.get("grader_report", {}).get("ifr") if isinstance(session.get("grader_report"), dict) else None,
    ]
    for path in grading_files:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        aggregate = data.get("aggregate", {})
        if isinstance(aggregate, dict):
            candidates.append(aggregate.get("ifr"))
        candidates.append(data.get("ifr"))
    value = first_number(*candidates)
    return {"value": value, "status": "unknown" if value is None else ("pass" if value >= 0.95 else "warn")}


def grade_from_rate(rate: float | None, vetoes: list[dict]) -> str:
    if vetoes:
        return "F"
    if rate is None:
        return "D"
    for grade, threshold in GRADE_THRESHOLDS:
        if rate >= threshold:
            return grade
    return "D"


def verdict_from(grade: str, rate: float | None, delta: dict, ifr: dict, vetoes: list[dict]) -> tuple[str, list[str]]:
    reasons = []
    if vetoes:
        return "FAIL", [f"{len(vetoes)} veto/warning item(s) detected"]
    if rate is None:
        return "FAIL", ["no grading data found"]

    reasons.append(f"authoritative_pass_rate={rate:.2%} -> grade {grade}")
    delta_status = delta.get("status")
    delta_value = delta.get("value")
    if delta_value is not None:
        reasons.append(f"Delta {delta_status}: {delta_value:+.2%}")
    else:
        reasons.append(f"Delta {delta_status}")

    if grade in ("S", "A"):
        if delta_status == "computed_negative":
            return "FAIL", reasons + ["S/A grade cannot publish with negative Delta"]
        if ifr.get("value") is not None and ifr["value"] < (1.0 if grade == "S" else 0.95):
            return "CONDITIONAL PASS", reasons + ["IFR below target for grade"]
        return "PASS", reasons

    if grade == "B":
        if delta_value is not None and delta_value < -0.05:
            return "FAIL", reasons + ["B grade allows only Delta >= -5%"]
        return "PASS", reasons

    if grade == "C":
        return "CONDITIONAL PASS", reasons + ["C grade requires explicit stakeholder alignment"]

    return "FAIL", reasons + ["D grade is below release threshold"]


def build_gate(session_dir: Path) -> dict:
    session = load_json(session_dir / "session.json") or {}
    counts, sources = collect_with_skill_counts(session_dir)
    grading_files = find_grading_files(session_dir)
    exact_rate = counts["exact_pass"] / counts["exact_total"] if counts["exact_total"] else None
    total_rate = counts["total_pass"] / counts["total_total"] if counts["total_total"] else None
    authoritative = exact_rate if exact_rate is not None else total_rate
    stddev = statistics.pstdev(counts["per_eval_rates"]) if len(counts["per_eval_rates"]) > 1 else 0.0
    delta = collect_delta(session_dir)
    vetoes = collect_vetoes(session, grading_files)
    ifr = collect_ifr(session, grading_files)
    grade = grade_from_rate(authoritative, vetoes)
    verdict, reasons = verdict_from(grade, authoritative, delta, ifr, vetoes)

    return {
        "status": "OK",
        "session_dir": str(session_dir),
        "skill": session.get("skill"),
        "mode": session.get("mode"),
        "authoritative_pass_rate": authoritative,
        "exact_pass_rate": exact_rate,
        "overall_pass_rate": total_rate,
        "stddev": round(stddev, 4),
        "counts": counts,
        "grade": grade,
        "verdict": verdict,
        "delta": delta,
        "ifr": ifr,
        "vetoes": vetoes,
        "blocked": session.get("blocked", []),
        "skipped": session.get("skipped", []),
        "decision_reasons": reasons,
        "sources": sources,
    }


def print_text(result: dict) -> None:
    print(f"verdict: {result['verdict']}")
    print(f"grade: {result['grade']}")
    rate = result.get("authoritative_pass_rate")
    print(f"authoritative_pass_rate: {'N/A' if rate is None else f'{rate:.2%}'}")
    print(f"delta: {result['delta']['status']} ({result['delta'].get('value')})")
    for reason in result.get("decision_reasons", []):
        print(f"- {reason}")


def value_at(data: dict, dotted: str):
    value = data
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def compare_expected(result: dict, expect_path: Path, tolerance: float) -> tuple[bool, list[str]]:
    expected = load_json(expect_path)
    if not isinstance(expected, dict):
        return False, [f"expected fixture is not a JSON object: {expect_path}"]

    checks = {
        "verdict": result.get("verdict"),
        "grade": result.get("grade"),
        "authoritative_pass_rate": result.get("authoritative_pass_rate"),
        "delta.status": value_at(result, "delta.status"),
    }
    if "exact_pass_rate" in expected:
        checks["exact_pass_rate"] = result.get("exact_pass_rate")
    if "overall_pass_rate" in expected:
        checks["overall_pass_rate"] = result.get("overall_pass_rate")

    errors = []
    for key, actual in checks.items():
        if key not in expected:
            continue
        wanted = expected[key]
        if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
            if actual is None or abs(float(actual) - float(wanted)) > tolerance:
                errors.append(f"{key}: expected {wanted}, got {actual}")
        elif actual != wanted:
            errors.append(f"{key}: expected {wanted!r}, got {actual!r}")

    return not errors, errors


def main() -> int:
    args = parse_args()
    session_dir = Path(args.session_dir).expanduser().resolve()
    result = build_gate(session_dir)
    expect_ok = True
    expect_errors: list[str] = []
    if args.expect:
        expect_ok, expect_errors = compare_expected(result, Path(args.expect).expanduser(), args.tolerance)
        result["expectation"] = {
            "status": "PASS" if expect_ok else "FAIL",
            "fixture": args.expect,
            "errors": expect_errors,
        }
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)
        if args.expect:
            print(f"expectation: {'PASS' if expect_ok else 'FAIL'}")
            for error in expect_errors:
                print(f"- {error}")
    if args.expect:
        return 0 if expect_ok else 1
    return 0 if result.get("verdict") in ("PASS", "CONDITIONAL PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
