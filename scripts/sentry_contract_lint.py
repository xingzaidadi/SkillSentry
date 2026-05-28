#!/usr/bin/env python3
"""SkillSentry contract lint.

Scans the SkillSentry skill package for current-contract drift. This is a
deterministic guardrail: it does not judge quality, it only finds old terms in
current entry files where they can confuse the active execution contract.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "sessions",
    "inputs",
}

SKIP_SUFFIXES = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".html",
    ".sqlite",
    ".db",
}

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".ps1",
    ".sh",
    ".py",
}

CURRENT_ALLOWED_HINTS = (
    "历史",
    "兼容",
    "归档",
    "旧",
    "不再",
    "仅作为",
    "只作为",
    "方法论",
    "补充",
    "替代",
    "路由",
    "保留",
    "废弃",
    "不要",
    "不在主 pipeline",
    "扫描",
    "清理",
    "兼容/归档",
    "去哪了",
    "本来就是",
    "自动路由",
    "原 ",
    "原`",
    "原'",
)

REPORT_ALLOWED_HINTS = (
    "独立",
    "已有 grading",
    "重新生成",
    "重出",
    "保留",
    "不作为",
    "仅用于",
    "只用于",
    "用户说",
    "特殊命令",
    "工具组成",
    "$Tools",
    "工具链",
    "路径",
    "不在主 pipeline",
)

EXPECTED_ACTIVE_TOOLS = {
    "sentry-static",
    "sentry-cases",
    "sentry-executor",
    "sentry-grader",
    "sentry-report",
    "sentry-comparator",
    "sentry-analyzer",
    "sentry-sync",
    "sentry-openclaw",
}

EXPECTED_CORE_SCRIPTS = {
    "sentry_pipeline.py",
    "sentry_preflight.py",
    "sentry_state.py",
    "sentry_gate.py",
    "sentry_sync.py",
    "sentry_publish.py",
    "sentry_contract_lint.py",
}

CURRENT_PIPELINES = {
    "smoke": ["cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
    "quick": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
    "regression": ["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"],
    "standard": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"],
    "full": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"],
}


@dataclass
class Finding:
    severity: str
    rule: str
    path: str
    line: int
    message: str
    text: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "text": self.text,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lint SkillSentry current-contract terminology")
    parser.add_argument("--root", default=str(SKILL_ROOT), help="SkillSentry root directory")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--output", default=None, help="Optional report path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when ERROR findings exist")
    return parser.parse_args()


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def should_skip(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in SKIP_DIRS for part in relative.parts):
        return True
    if "archive" in relative.parts:
        return True
    if len(relative.parts) >= 2 and relative.parts[0] == "tools" and relative.parts[1] in {
        "sentry-check",
        "sentry-lint",
        "sentry-trigger",
    }:
        return True
    if relative.parts[0:1] == ("scripts",) and path.name in {
        "sentry_contract_lint.py",
        "sentry_article_lint.py",
    }:
        return True
    if path.name == "CHANGELOG.md":
        return True
    if path.name == "cleanup-old-memory.sh":
        return True
    if path.name.endswith(".bak") or ".bak." in path.name:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"VERSION"}:
        return True
    return False


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not should_skip(path, root):
            yield path


def has_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def add_finding(findings: list[Finding], severity: str, rule: str, path: Path, root: Path, line: int, message: str, text: str):
    findings.append(
        Finding(
            severity=severity,
            rule=rule,
            path=rel(path, root),
            line=line,
            message=message,
            text=text.strip(),
        )
    )


def looks_like_main_report_misuse(text: str) -> bool:
    if "sentry-report" not in text:
        return False
    return bool(re.search(r"主流程|pipeline|最后一步|常规步骤|必要步骤|主\s*pipeline", text, re.IGNORECASE))


def lint_line(findings: list[Finding], path: Path, root: Path, line_no: int, line: str, context: str) -> None:
    relative = rel(path, root)
    stripped = line.strip()
    if not stripped:
        return

    check_text = f"{context}\n{line}"

    if "Pass³" in line and not has_any(check_text, CURRENT_ALLOWED_HINTS):
        add_finding(
            findings,
            "ERROR",
            "old_metric_pass3",
            path,
            root,
            line_no,
            "Pass³ must only appear as history or method supplement in current entry files.",
            line,
        )

    if re.search(r"\bL[0-5]\s*-\s*L[0-5]\b", line) and not has_any(check_text, CURRENT_ALLOWED_HINTS):
        add_finding(
            findings,
            "ERROR",
            "old_level_l0_l5",
            path,
            root,
            line_no,
            "L0-L5 level terminology must not be used as the current release contract.",
            line,
        )

    if re.search(r"\bsentry-(lint|trigger|check)\b", line) and not has_any(check_text, CURRENT_ALLOWED_HINTS):
        add_finding(
            findings,
            "ERROR",
            "old_tool_name",
            path,
            root,
            line_no,
            "Old tool names must be framed as compatibility/history, not current recommended tools.",
            line,
        )

    if looks_like_main_report_misuse(line) and "tools/sentry-report" not in relative:
        if not has_any(check_text, REPORT_ALLOWED_HINTS):
            add_finding(
                findings,
                "WARN",
                "sentry_report_context",
                path,
                root,
                line_no,
                "sentry-report should be described as independent report regeneration, not a main pipeline step.",
                line,
            )

    if re.search(r"\b[vV]10\b|早期平台适配版本", line):
        if not has_any(check_text, CURRENT_ALLOWED_HINTS):
            add_finding(
                findings,
                "WARN",
                "old_version_context",
                path,
                root,
                line_no,
                "Old version names should be explicitly historical when they appear in current files.",
                line,
            )


def lint_text_files(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = text.splitlines()
        for line_no, line in enumerate(lines, start=1):
            context = "\n".join(lines[max(0, line_no - 9) : line_no - 1])
            lint_line(findings, path, root, line_no, line, context)
    return findings


def structural_findings(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    tools_dir = root / "tools"
    scripts_dir = root / "scripts"

    if tools_dir.exists():
        actual_tools = {p.name for p in tools_dir.iterdir() if p.is_dir()}
        missing = sorted(EXPECTED_ACTIVE_TOOLS - actual_tools)
        for name in missing:
            add_finding(
                findings,
                "ERROR",
                "missing_active_tool",
                tools_dir,
                root,
                0,
                f"Expected active tool directory is missing: {name}",
                name,
            )

    if scripts_dir.exists():
        actual_scripts = {p.name for p in scripts_dir.iterdir() if p.is_file()}
        missing = sorted(EXPECTED_CORE_SCRIPTS - actual_scripts)
        for name in missing:
            add_finding(
                findings,
                "ERROR",
                "missing_core_script",
                scripts_dir,
                root,
                0,
                f"Expected deterministic core script is missing: {name}",
                name,
            )

    current_contract = root / "references" / "current-contract.md"
    if current_contract.exists():
        text = current_contract.read_text(encoding="utf-8")
        pipeline_block = re.search(r"合法 pipeline:\s*```json\s*(.*?)```", text, re.DOTALL)
        if pipeline_block and re.search(r'"report"', pipeline_block.group(1)):
            add_finding(
                findings,
                "ERROR",
                "report_in_main_pipeline",
                current_contract,
                root,
                0,
                "Main pipeline must use grader-report and must not include a standalone report step.",
                '"report"',
            )

    pipeline_script = root / "scripts" / "sentry_pipeline.py"
    if pipeline_script.exists():
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("sentry_pipeline_lint_target", pipeline_script)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            actual = getattr(module, "PIPELINES", {})
            if actual != CURRENT_PIPELINES:
                add_finding(
                    findings,
                    "ERROR",
                    "pipeline_core_mismatch",
                    pipeline_script,
                    root,
                    0,
                    "sentry_pipeline.py PIPELINES must match current-contract pipeline.",
                    json.dumps(actual, ensure_ascii=False),
                )
        except Exception as exc:
            add_finding(
                findings,
                "ERROR",
                "pipeline_core_unreadable",
                pipeline_script,
                root,
                0,
                f"Could not import sentry_pipeline.py: {exc}",
                "",
            )

    ci_script = root / "scripts" / "sentry_ci.py"
    if ci_script.exists():
        text = ci_script.read_text(encoding="utf-8")
        old_patterns = [
            (r"return\s+\[\s*[\"']check[\"']", "old_check_pipeline"),
            (r"return\s+\[[^\]]*[\"']executor[\"'][^\]]*[\"']grader[\"']", "old_executor_grader_pipeline"),
            (r"def\s+get_pipeline\s*\(", "local_pipeline_function"),
        ]
        for pattern, rule in old_patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                add_finding(
                    findings,
                    "ERROR",
                    rule,
                    ci_script,
                    root,
                    0,
                    "sentry_ci.py must use sentry_pipeline.py current step names, not local legacy pipeline definitions.",
                    match.group(0),
                )

    validator = root / "scripts" / "validate_step.py"
    if validator.exists():
        text = validator.read_text(encoding="utf-8")
        for legacy in ("'grader'", '"grader"', "'report'", '"report"', "step-7", "step-7.5"):
            if legacy in text:
                add_finding(
                    findings,
                    "ERROR",
                    "legacy_validate_step",
                    validator,
                    root,
                    0,
                    "validate_step.py must validate current pipeline steps through sentry_pipeline.py.",
                    legacy,
                )
    return findings


def build_result(root: Path) -> dict:
    findings = structural_findings(root) + lint_text_files(root)
    counts: dict[str, int] = {"ERROR": 0, "WARN": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    return {
        "status": "PASS" if counts.get("ERROR", 0) == 0 else "FAIL",
        "root": str(root),
        "summary": counts,
        "findings": [finding.to_dict() for finding in findings],
    }


def print_text(result: dict) -> None:
    summary = result["summary"]
    print(f"status: {result['status']} | errors: {summary.get('ERROR', 0)} | warnings: {summary.get('WARN', 0)}")
    for item in result["findings"]:
        location = f"{item['path']}:{item['line']}" if item["line"] else item["path"]
        print(f"{item['severity']} {item['rule']} {location}")
        print(f"  {item['message']}")
        if item["text"]:
            print(f"  > {item['text']}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    result = build_result(root)
    payload = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")

    if args.format == "json":
        print(payload)
    else:
        print_text(result)

    if args.strict and result["summary"].get("ERROR", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
