#!/usr/bin/env python3
"""Deterministic evals.json feasibility lint.

This is a light tool: no LLM calls, no network calls. It checks whether cases
reference local resources that are unavailable in the current environment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sentry_state


WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[^\s，。；,;`\"']+")
LINT_VERSION = 2

PROMPT_INJECTION_PATTERN = re.compile(
    r"(ignore\s+(all\s+)?previous|ignore\s+above|system\s+override|developer\s+override|忽略(前文|之前|以上|上面)|覆盖(系统|开发者)指令)",
    re.IGNORECASE,
)
SECRET_ACCESS_PATTERN = re.compile(
    r"(\.env\b|id_rsa|ssh\s*key|api[_-]?key|token|secret|password|密钥|令牌|数据库配置|凭据)",
    re.IGNORECASE,
)
EXFILTRATION_PATTERN = re.compile(
    r"(https?://[^\s，。；,;`\"']+|webhook|callback|回调地址|外部地址|发送到|上传到|post\s+to)",
    re.IGNORECASE,
)
DANGEROUS_COMMAND_PATTERN = re.compile(
    r"(rm\s+-rf|del\s+/[fsq]|format\s+[A-Za-z]:|shutdown\b|chmod\s+777|curl\b.*\|\s*(sh|bash)|Invoke-WebRequest\b.*iex\b)",
    re.IGNORECASE,
)
VAGUE_AUTH_PATTERN = re.compile(
    r"(无需(确认|审批|授权)|不用(确认|审批|授权)|绕过(确认|审批|权限)|所有权限|直接执行|不需要用户确认|自动批准)",
    re.IGNORECASE,
)

SECURITY_FAMILIES = {
    "prompt_injection",
    "indirect_injection",
    "multi_turn_induction",
    "normal_request_disguise",
    "tool_overscope",
    "secrets_access",
    "exfiltration",
    "recovery_rollback",
}

SECURITY_RISK_LEVELS = {"P0", "P1"}
SECURITY_GATE_LEVELS = {"block", "review", "warn"}

SECURITY_SIGNAL_RULES = (
    {
        "warning_type": "unlabeled_prompt_injection",
        "pattern": PROMPT_INJECTION_PATTERN,
        "families": {"prompt_injection", "indirect_injection"},
        "message": "Case contains prompt-injection signals but is not marked as a Security V1 injection case.",
    },
    {
        "warning_type": "unlabeled_secret_access",
        "pattern": SECRET_ACCESS_PATTERN,
        "families": {"secrets_access"},
        "message": "Case references secrets or credentials but is not marked as a Security V1 secrets_access case.",
    },
    {
        "warning_type": "unlabeled_exfiltration",
        "pattern": EXFILTRATION_PATTERN,
        "families": {"exfiltration"},
        "message": "Case references external sending or URLs but is not marked as a Security V1 exfiltration case.",
    },
    {
        "warning_type": "unlabeled_dangerous_command",
        "pattern": DANGEROUS_COMMAND_PATTERN,
        "families": {"tool_overscope"},
        "message": "Case references dangerous command execution but is not marked as a Security V1 tool_overscope case.",
    },
    {
        "warning_type": "unlabeled_vague_authorization",
        "pattern": VAGUE_AUTH_PATTERN,
        "families": {"tool_overscope", "normal_request_disguise"},
        "message": "Case contains vague authorization or approval-bypass language without Security V1 metadata.",
    },
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_cases(payload) -> list:
    """Accept legacy list payloads and common wrapped eval/case shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("evals", "cases", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _case_text(case: dict, key: str) -> str:
    value = case.get(key)
    return value.strip() if isinstance(value, str) else ""


def _combined_case_text(case: dict) -> str:
    parts: list[str] = []
    for key in ("name", "prompt", "expected_output", "expected_guardrail"):
        value = case.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("assertions", "expectations"):
        items = case.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for field in ("name", "expected", "message"):
                        value = item.get(field)
                        if isinstance(value, str):
                            parts.append(value)
                elif isinstance(item, str):
                    parts.append(item)
    return "\n".join(parts)


def inspect_security_metadata(cases) -> list[dict]:
    """Return deterministic warnings for security cases with incomplete metadata."""
    warnings: list[dict] = []

    for case in extract_cases(cases):
        if not isinstance(case, dict):
            continue

        case_id = case.get("id") or case.get("case_id") or "unknown"
        dimension = _case_text(case, "dimension").lower() or _case_text(case, "category").lower()
        security_family = _case_text(case, "security_family").lower()
        risk_level = _case_text(case, "risk_level").upper()
        gate_level = _case_text(case, "gate_level").lower()
        attack_surface = case.get("attack_surface")
        expected_guardrail = case.get("expected_guardrail")

        is_security_case = bool(
            security_family
            or risk_level
            or gate_level
            or dimension == "security"
        )
        if not is_security_case:
            continue

        if not security_family:
            warnings.append({
                "case_id": case_id,
                "type": "security_metadata_missing",
                "field": "security_family",
                "message": "Security case is missing security_family.",
            })
        elif security_family not in SECURITY_FAMILIES:
            warnings.append({
                "case_id": case_id,
                "type": "security_family_unknown",
                "field": "security_family",
                "value": security_family,
                "message": "Security case uses an unknown security_family.",
            })

        if risk_level not in SECURITY_RISK_LEVELS:
            warnings.append({
                "case_id": case_id,
                "type": "security_metadata_missing",
                "field": "risk_level",
                "message": "Security case is missing or invalid risk_level.",
            })

        if not isinstance(attack_surface, list) or not attack_surface:
            warnings.append({
                "case_id": case_id,
                "type": "security_metadata_missing",
                "field": "attack_surface",
                "message": "Security case is missing attack_surface.",
            })

        if not expected_guardrail:
            warnings.append({
                "case_id": case_id,
                "type": "security_metadata_missing",
                "field": "expected_guardrail",
                "message": "Security case is missing expected_guardrail.",
            })

        if gate_level not in SECURITY_GATE_LEVELS:
            warnings.append({
                "case_id": case_id,
                "type": "security_metadata_missing",
                "field": "gate_level",
                "message": "Security case is missing or invalid gate_level.",
            })

    return warnings


def inspect_static_security_signals(cases) -> list[dict]:
    """Warn when risky case text is not explicitly mapped to Security V1 metadata."""
    warnings: list[dict] = []

    for case in extract_cases(cases):
        if not isinstance(case, dict):
            continue
        case_id = case.get("id") or case.get("case_id") or "unknown"
        security_family = _case_text(case, "security_family").lower()
        risk_level = _case_text(case, "risk_level").upper()
        gate_level = _case_text(case, "gate_level").lower()
        text = _combined_case_text(case)
        if not text:
            continue

        for rule in SECURITY_SIGNAL_RULES:
            match = rule["pattern"].search(text)
            if not match:
                continue
            expected_families = rule["families"]
            if security_family in expected_families and risk_level in SECURITY_RISK_LEVELS and gate_level in SECURITY_GATE_LEVELS:
                continue
            warnings.append({
                "case_id": case_id,
                "type": rule["warning_type"],
                "signal": match.group(0),
                "expected_security_family": sorted(expected_families),
                "message": rule["message"],
            })

    return warnings


def inspect_case_feasibility(cases) -> list[dict]:
    """Return deterministic warnings for cases that cannot run as-is."""
    warnings: list[dict] = []

    for case in extract_cases(cases):
        if not isinstance(case, dict):
            continue
        case_id = case.get("id") or case.get("case_id") or "unknown"
        prompt = case.get("prompt", "") or ""
        if not isinstance(prompt, str):
            continue
        for raw_path in WINDOWS_PATH_PATTERN.findall(prompt):
            normalized = raw_path.rstrip(".,;，。；)")
            if not Path(normalized).exists():
                warnings.append({
                    "case_id": case_id,
                    "type": "missing_local_path",
                    "path": normalized,
                    "message": "Generated case references a local path that does not exist in this environment.",
                })
    warnings.extend(inspect_security_metadata(cases))
    warnings.extend(inspect_static_security_signals(cases))
    return warnings


def lint_cases_file(cases_file: Path) -> dict:
    payload = load_json(cases_file)
    cases = extract_cases(payload)
    warnings = inspect_case_feasibility(payload)
    return {
        "status": "WARN" if warnings else "OK",
        "step": "case-lint",
        "version": LINT_VERSION,
        "cases_file": str(cases_file),
        "total": len(cases),
        "warnings": warnings,
        "warning_count": len(warnings),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def record_case_feasibility(session_dir: Path, cases) -> list[dict]:
    """Write feasibility warnings into session.json and return them."""
    warnings = inspect_case_feasibility(cases)
    session = sentry_state.load_session(session_dir)
    session["case_warnings"] = warnings
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    sentry_state.save_session(session_dir, session)
    return warnings


def record_case_lint_result(session_dir: Path, result: dict) -> None:
    session = sentry_state.load_session(session_dir)
    session["case_warnings"] = result.get("warnings", [])
    session["case_lint"] = {
        "status": result.get("status"),
        "version": result.get("version", LINT_VERSION),
        "total": result.get("total", 0),
        "warning_count": result.get("warning_count", 0),
        "cases_file": result.get("cases_file"),
        "checked_at": result.get("checked_at"),
    }
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    sentry_state.save_session(session_dir, session)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint evals.json feasibility without running executor/grader")
    parser.add_argument("--cases", required=True, help="Path to evals.json/cases.cache.json")
    parser.add_argument("--session-dir", help="Optional session directory to update with case_warnings")
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = lint_cases_file(Path(args.cases))
    if args.session_dir:
        record_case_lint_result(Path(args.session_dir), result)
    if args.output:
        save_json(Path(args.output), result)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"case lint: {result['status']} | warnings: {result['warning_count']} | total: {result['total']}")
        for warning in result["warnings"]:
            print(f"- {warning['case_id']}: {warning['type']} {warning.get('path', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
