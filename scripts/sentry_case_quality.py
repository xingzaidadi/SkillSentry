#!/usr/bin/env python3
"""SkillSentry case quality check.

Post-generation quality gate: reads evals.json and validates coverage
completeness before execution. Deterministic — no LLM required.

Outputs case-quality-result.json with verdict: pass / pass_with_warnings / blocked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ── Dimension definitions ────────────────────────────────────────────────────

DIMENSIONS = ("happy_path", "edge_case", "negative", "robustness", "security", "e2e")

HARD_GATE_DIMENSIONS = ("happy_path", "negative", "robustness")

# ── Mode-based thresholds ────────────────────────────────────────────────────
# hard_gate_min: minimum count per hard-gate dimension
# soft_warn_min: minimum count per soft-warn dimension

MODE_THRESHOLDS = {
    "smoke": {"hard_gate_min": 1, "soft_warn_min": 0},
    "quick": {"hard_gate_min": 1, "soft_warn_min": 1},
    "standard": {"hard_gate_min": 2, "soft_warn_min": 1},
    "full": {"hard_gate_min": 3, "soft_warn_min": 2},
}

# ── Orphan assertion thresholds ──────────────────────────────────────────────

ORPHAN_THRESHOLDS = {"pass": 0.30, "warn": 0.50}

# ── Rule coverage thresholds ────────────────────────────────────────────────

RULE_COVERAGE_THRESHOLDS = {"pass": 0.70, "warn": 0.50}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry case quality check")
    parser.add_argument("session_dir", help="Session/workspace directory containing evals.json")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--output", default=None, help="Optional output path for case-quality-result.json")
    parser.add_argument("--mode", choices=["smoke", "quick", "standard", "full"], default="quick",
                        help="Pipeline mode determines threshold strictness")
    return parser.parse_args()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Dimension counting ───────────────────────────────────────────────────────

def count_dimensions(evals: list[dict]) -> dict[str, int]:
    """Count cases per dimension from evals.json entries."""
    counts: dict[str, int] = {dim: 0 for dim in DIMENSIONS}
    for case in evals:
        if not isinstance(case, dict):
            continue
        dim = case.get("dimension") or case.get("category") or ""
        dim = dim.strip().lower()
        if dim in counts:
            counts[dim] += 1
    return counts


# ── Assertion quality ────────────────────────────────────────────────────────

def _extract_rule_ids(rules_cache: dict) -> set[str]:
    """Extract rule identifiers from rules.cache.json.

    Rules are stored as a plain string list. We generate IDs like R-01, R-02...
    and also accept the raw rule text as a valid ref (for LLMs that quote the rule directly).
    """
    rules = rules_cache.get("rules") or []
    if not isinstance(rules, list):
        return set()
    ids: set[str] = set()
    for i, rule in enumerate(rules, 1):
        ids.add(f"R-{i:02d}")
        ids.add(f"R{i}")
        ids.add(f"R-{i}")
        if isinstance(rule, str) and rule.strip():
            ids.add(rule.strip())
    return ids


def analyze_assertions(evals: list[dict], rules_cache: dict | None = None) -> dict:
    """Analyze assertion quality: rule_ref coverage, orphan rate, and structural validation."""
    total = 0
    with_rule_ref = 0
    ref_values: list[str] = []

    for case in evals:
        if not isinstance(case, dict):
            continue
        expectations = case.get("expectations") or case.get("assertions") or []
        if not isinstance(expectations, list):
            continue
        for exp in expectations:
            if not isinstance(exp, dict):
                continue
            total += 1
            ref = exp.get("rule_ref")
            if ref:
                with_rule_ref += 1
                ref_values.append(str(ref).strip())

    orphan = total - with_rule_ref
    orphan_rate = orphan / total if total > 0 else 0.0

    if orphan_rate <= ORPHAN_THRESHOLDS["pass"]:
        orphan_verdict = "pass"
    elif orphan_rate <= ORPHAN_THRESHOLDS["warn"]:
        orphan_verdict = "warn"
    else:
        orphan_verdict = "fail"

    result: dict = {
        "total": total,
        "with_rule_ref": with_rule_ref,
        "orphan": orphan,
        "orphan_rate": round(orphan_rate, 4),
        "orphan_verdict": orphan_verdict,
    }

    # Phase 5: structural validation against rules.cache.json
    if rules_cache and isinstance(rules_cache.get("rules"), list):
        valid_ids = _extract_rule_ids(rules_cache)
        rules_list = rules_cache.get("rules", [])
        total_rules = len(rules_list)

        # Find dangling refs (rule_ref values that don't match any known rule)
        dangling: list[str] = []
        referenced_indices: set[int] = set()
        for ref in ref_values:
            if ref in valid_ids:
                # Map back to rule index
                for i, rule in enumerate(rules_list):
                    if ref == f"R-{i+1:02d}" or ref == f"R{i+1}" or ref == f"R-{i+1}" or ref == rule.strip():
                        referenced_indices.add(i)
                        break
            else:
                if ref not in dangling:
                    dangling.append(ref)

        # Find uncovered rules (rules with no assertion referencing them)
        uncovered: list[str] = []
        for i, rule in enumerate(rules_list):
            if i not in referenced_indices:
                label = f"R-{i+1:02d}"
                uncovered.append(label)

        rule_coverage_rate = (total_rules - len(uncovered)) / total_rules if total_rules > 0 else 1.0

        if rule_coverage_rate >= RULE_COVERAGE_THRESHOLDS["pass"]:
            rule_coverage_verdict = "pass"
        elif rule_coverage_rate >= RULE_COVERAGE_THRESHOLDS["warn"]:
            rule_coverage_verdict = "warn"
        else:
            rule_coverage_verdict = "fail"

        result["dangling_refs"] = dangling[:20]
        result["uncovered_rules"] = uncovered[:20]
        result["rule_coverage_rate"] = round(rule_coverage_rate, 4)
        result["rule_coverage_verdict"] = rule_coverage_verdict

    return result


# ── Gate checks ──────────────────────────────────────────────────────────────

def check_hard_gates(dim_counts: dict[str, int], threshold: int) -> dict:
    """Check hard gate dimensions against threshold."""
    items = []
    passed = 0
    for dim in HARD_GATE_DIMENSIONS:
        actual = dim_counts.get(dim, 0)
        status = "pass" if actual >= threshold else "fail"
        if status == "pass":
            passed += 1
        items.append({"name": f"{dim} >= {threshold}", "status": status, "actual": actual})

    return {"total": len(HARD_GATE_DIMENSIONS), "passed": passed, "items": items}


def check_soft_warns(dim_counts: dict[str, int], threshold: int) -> dict:
    """Check soft-warn dimensions (non-hard-gate) against threshold."""
    soft_dims = [d for d in DIMENSIONS if d not in HARD_GATE_DIMENSIONS]
    items = []
    passed = 0

    if threshold <= 0:
        # smoke mode: soft warns not checked
        for dim in soft_dims:
            actual = dim_counts.get(dim, 0)
            items.append({"name": f"{dim} >= 1", "status": "skip", "actual": actual})
        return {"total": len(soft_dims), "passed": len(soft_dims), "items": items}

    for dim in soft_dims:
        actual = dim_counts.get(dim, 0)
        if actual >= threshold:
            status = "pass"
            passed += 1
        else:
            status = "warn"
        item: dict = {"name": f"{dim} >= {threshold}", "status": status, "actual": actual}
        if status == "warn":
            item["suggestion"] = f"补充 {threshold - actual} 条 {dim} 用例"
        items.append(item)

    return {"total": len(soft_dims), "passed": passed, "items": items}


# ── Suggestions ──────────────────────────────────────────────────────────────

def generate_suggestions(hard_gate: dict, soft_warn: dict, assertion_quality: dict) -> list[str]:
    """Generate actionable suggestions from check results."""
    suggestions = []

    for item in hard_gate["items"]:
        if item["status"] == "fail":
            suggestions.append(f"[阻断] 缺少 {item['name'].split(' >= ')[0]} 用例，当前 {item['actual']} 条")

    for item in soft_warn["items"]:
        if item["status"] == "warn":
            suggestions.append(f"建议补充 {item['name'].split(' >= ')[0]} 用例（当前 {item['actual']} 条）")

    if assertion_quality["orphan_verdict"] == "warn":
        suggestions.append(f"断言 orphan 率 {assertion_quality['orphan_rate']:.0%}，建议补充 rule_ref 映射")
    elif assertion_quality["orphan_verdict"] == "fail":
        suggestions.append(f"断言 orphan 率 {assertion_quality['orphan_rate']:.0%} 过高，断言设计质量不足")

    # Phase 5: structural validation suggestions
    dangling = assertion_quality.get("dangling_refs") or []
    if dangling:
        refs_text = ", ".join(dangling[:5])
        suggestions.append(f"断言引用了不存在的规则: {refs_text}")

    uncovered = assertion_quality.get("uncovered_rules") or []
    if uncovered:
        rules_text = ", ".join(uncovered[:5])
        suffix = f" 等 {len(uncovered)} 条" if len(uncovered) > 5 else ""
        suggestions.append(f"以下规则无断言覆盖: {rules_text}{suffix}")

    rule_cov_verdict = assertion_quality.get("rule_coverage_verdict")
    if rule_cov_verdict == "fail":
        rate = assertion_quality.get("rule_coverage_rate", 0)
        suggestions.append(f"规则覆盖率仅 {rate:.0%}，低于 50% 阈值，用例设计需大幅补充")

    return suggestions


# ── Main logic ───────────────────────────────────────────────────────────────

def build_quality_result(session_dir: Path, mode: str) -> dict:
    """Build the complete quality check result."""
    evals_path = session_dir / "evals.json"
    evals = load_json(evals_path)

    if evals is None:
        return {
            "verdict": "blocked",
            "block_reason": "evals.json 不存在或格式错误",
            "hard_gate": {"total": 3, "passed": 0, "items": []},
            "soft_warn": {"total": 3, "passed": 0, "items": []},
            "coverage": {"dimensions": {}, "total_cases": 0},
            "assertion_quality": {"total": 0, "with_rule_ref": 0, "orphan": 0, "orphan_rate": 0, "orphan_verdict": "pass"},
            "suggestions": ["evals.json 不存在或无法解析，请先运行 sentry-cases 生成用例"],
        }

    if not isinstance(evals, list):
        evals = []

    thresholds = MODE_THRESHOLDS.get(mode, MODE_THRESHOLDS["quick"])
    hard_min = thresholds["hard_gate_min"]
    soft_min = thresholds["soft_warn_min"]

    dim_counts = count_dimensions(evals)
    hard_gate = check_hard_gates(dim_counts, hard_min)
    soft_warn = check_soft_warns(dim_counts, soft_min)

    # Load rules.cache.json for structural validation (Phase 5)
    rules_cache = None
    for candidate in [
        session_dir / "rules.cache.json",
        session_dir.parent / "rules.cache.json",
    ]:
        rc = load_json(candidate)
        if rc and isinstance(rc, dict) and isinstance(rc.get("rules"), list):
            rules_cache = rc
            break

    assertion_quality = analyze_assertions(evals, rules_cache)
    suggestions = generate_suggestions(hard_gate, soft_warn, assertion_quality)

    # Determine verdict
    if hard_gate["passed"] < hard_gate["total"]:
        failed_items = [i["name"] for i in hard_gate["items"] if i["status"] == "fail"]
        verdict = "blocked"
        block_reason = f"硬门禁未通过: {', '.join(failed_items)}"
    elif (
        soft_warn["passed"] < soft_warn["total"]
        or assertion_quality["orphan_verdict"] != "pass"
        or assertion_quality.get("rule_coverage_verdict") == "fail"
        or assertion_quality.get("dangling_refs")
    ):
        verdict = "pass_with_warnings"
        block_reason = None
    else:
        verdict = "pass"
        block_reason = None

    return {
        "verdict": verdict,
        "block_reason": block_reason,
        "hard_gate": hard_gate,
        "soft_warn": soft_warn,
        "coverage": {
            "dimensions": dim_counts,
            "total_cases": len(evals),
        },
        "assertion_quality": assertion_quality,
        "suggestions": suggestions,
    }


def print_text(result: dict) -> None:
    """Print human-readable text output."""
    verdict_icon = {"pass": "✅", "pass_with_warnings": "⚠️", "blocked": "❌"}.get(result["verdict"], "?")
    print(f"verdict: {result['verdict']} {verdict_icon}")

    if result["block_reason"]:
        print(f"block_reason: {result['block_reason']}")

    print(f"\n硬门禁: {result['hard_gate']['passed']}/{result['hard_gate']['total']} 通过")
    for item in result["hard_gate"]["items"]:
        icon = "✓" if item["status"] == "pass" else "✗"
        print(f"  {icon} {item['name']} (实际: {item['actual']})")

    print(f"\n软告警: {result['soft_warn']['passed']}/{result['soft_warn']['total']} 通过")
    for item in result["soft_warn"]["items"]:
        icon = "✓" if item["status"] == "pass" else ("—" if item["status"] == "skip" else "⚠")
        print(f"  {icon} {item['name']} (实际: {item['actual']})")

    cov = result["coverage"]
    print(f"\n覆盖: 总用例 {cov['total_cases']}")
    for dim, count in cov["dimensions"].items():
        print(f"  {dim}: {count}")

    aq = result["assertion_quality"]
    print(f"\n断言质量: {aq['total']} 条, rule_ref {aq['with_rule_ref']}, orphan {aq['orphan']} ({aq['orphan_verdict']})")

    if result["suggestions"]:
        print("\n建议:")
        for s in result["suggestions"]:
            print(f"  - {s}")


def main() -> int:
    args = parse_args()
    session_dir = Path(args.session_dir).expanduser().resolve()
    result = build_quality_result(session_dir, args.mode)

    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)

    return 0 if result["verdict"] != "blocked" else 1


if __name__ == "__main__":
    sys.exit(main())
