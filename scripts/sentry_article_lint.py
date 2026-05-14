#!/usr/bin/env python3
"""SkillSentry article lint.

Scans article repositories for terminology that conflicts with the current
SkillSentry contract. The linter is intentionally conservative: historical
folders are skipped by default, and old terms are allowed when the local line
clearly frames them as history, compatibility, or method background.
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

DEFAULT_ARTICLE_ROOT = Path.home() / "Desktop" / "测评skill相关" / "AI_Skill测评体系"

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "archive",
    "references",
}

HISTORY_DIRS = {
    "90_历史与暂缓",
}

ALLOWED_HINTS = (
    "历史",
    "兼容",
    "归档",
    "旧",
    "不再",
    "仅作为",
    "只作为",
    "方法论",
    "补充",
    "当前口径",
    "更新说明",
    "替代",
    "路由",
    "保留",
    "不要再",
    "不要把",
    "不建议",
    "旧词",
    "扫描",
    "只能出现在",
    "历史来源",
    "兼容命令",
    "演进",
    "版本演进",
    "迁移",
    "从",
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
    "当前口径",
    "边界",
    "已有评分重新出报告",
    "路径",
    "为什么主流程没有",
)


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
    parser = argparse.ArgumentParser(description="Lint SkillSentry article terminology")
    parser.add_argument("--root", default=str(DEFAULT_ARTICLE_ROOT), help="Article repository root")
    parser.add_argument("--include-history", action="store_true", help="Scan archive/history folders too")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--output", default=None, help="Optional report path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when ERROR findings exist")
    return parser.parse_args()


def rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def has_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def should_skip(path: Path, root: Path, include_history: bool) -> bool:
    relative = path.relative_to(root)
    parts = set(relative.parts)
    if not include_history:
        if parts & SKIP_DIRS:
            return True
        if parts & HISTORY_DIRS:
            return True
    else:
        if ".git" in parts or "__pycache__" in parts:
            return True
    if path.suffix.lower() != ".md":
        return True
    if path.name in {
        "当前口径_术语扫描结果.md",
        "文章体系_当前口径整改计划.md",
        "SkillSentry与文章体系_当前口径总整改方案.md",
    }:
        return True
    return False


def iter_markdown(root: Path, include_history: bool):
    for path in sorted(root.rglob("*.md")):
        if not should_skip(path, root, include_history):
            yield path


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


def has_current_note(text: str) -> bool:
    head = "\n".join(text.splitlines()[:20])
    return "当前口径" in head or "当前口径更新说明" in head


def file_allows_history_terms(path: Path, text: str) -> bool:
    relative = str(path).replace("\\", "/")
    head = "\n".join(text.splitlines()[:30])
    if "历史" in relative or "演进" in relative or "升级说明" in relative:
        return True
    return "只作为历史来源和兼容命令理解" in head


def looks_like_main_report_misuse(text: str) -> bool:
    if "sentry-report" not in text:
        return False
    return bool(re.search(r"主流程|pipeline|最后一步|常规步骤|必要步骤|主\s*pipeline", text, re.IGNORECASE))


def lint_line(
    findings: list[Finding],
    path: Path,
    root: Path,
    line_no: int,
    line: str,
    context: str,
    allow_history_terms: bool,
) -> None:
    check_text = f"{context}\n{line}"

    if "Pass³" in line and not allow_history_terms and not has_any(check_text, ALLOWED_HINTS):
        add_finding(
            findings,
            "ERROR",
            "old_metric_pass3",
            path,
            root,
            line_no,
            "Pass³ should not be used as the current main metric in publishable articles.",
            line,
        )

    if re.search(r"\bL[0-5]\s*-\s*L[0-5]\b", line) and not allow_history_terms and not has_any(check_text, ALLOWED_HINTS):
        add_finding(
            findings,
            "ERROR",
            "old_level_l0_l5",
            path,
            root,
            line_no,
            "L0-L5 should only appear as historical framing in publishable articles.",
            line,
        )

    if re.search(r"\bsentry-(lint|trigger|check)\b", line) and not allow_history_terms and not has_any(check_text, ALLOWED_HINTS):
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

    if looks_like_main_report_misuse(line) and not has_any(check_text, REPORT_ALLOWED_HINTS):
        add_finding(
            findings,
            "WARN",
            "sentry_report_context",
            path,
            root,
            line_no,
            "sentry-report should be described as independent regeneration, while grader-report is the main flow.",
            line,
        )

    if "INCONCLUSIVE" in line and not allow_history_terms and not has_any(check_text, ALLOWED_HINTS):
        add_finding(
            findings,
            "WARN",
            "old_result_inconclusive",
            path,
            root,
            line_no,
            "Use CONDITIONAL PASS for release conclusions; reserve INCONCLUSIVE for historical or eval-level notes.",
            line,
        )


def lint_file(path: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    relative = rel(path, root)
    if relative.startswith("博客系列/publish_ready/") and not has_current_note(text):
        add_finding(
            findings,
            "WARN",
            "publish_ready_missing_current_note",
            path,
            root,
            1,
            "publish_ready articles should state the current SkillSentry口径 near the top.",
            text.splitlines()[0] if text.splitlines() else "",
        )

    allow_history_terms = file_allows_history_terms(path, text)
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        context = "\n".join(lines[max(0, line_no - 16) : line_no - 1])
        lint_line(findings, path, root, line_no, line, context, allow_history_terms)
    return findings


def build_result(root: Path, include_history: bool) -> dict:
    findings: list[Finding] = []
    scanned = 0
    for path in iter_markdown(root, include_history):
        scanned += 1
        findings.extend(lint_file(path, root))

    counts: dict[str, int] = {"ERROR": 0, "WARN": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    return {
        "status": "PASS" if counts.get("ERROR", 0) == 0 else "FAIL",
        "root": str(root),
        "scanned_files": scanned,
        "include_history": include_history,
        "summary": counts,
        "findings": [finding.to_dict() for finding in findings],
    }


def print_text(result: dict) -> None:
    summary = result["summary"]
    print(
        f"status: {result['status']} | scanned: {result['scanned_files']} | "
        f"errors: {summary.get('ERROR', 0)} | warnings: {summary.get('WARN', 0)}"
    )
    for item in result["findings"]:
        location = f"{item['path']}:{item['line']}" if item["line"] else item["path"]
        print(f"{item['severity']} {item['rule']} {location}")
        print(f"  {item['message']}")
        if item["text"]:
            print(f"  > {item['text']}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    result = build_result(root, args.include_history)
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
