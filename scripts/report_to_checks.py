#!/usr/bin/env python3
"""
SkillSentry → GitHub Checks API bridge.
Push sentry_ci.py eval_result.json output to GitHub Checks.

用法：
  python report_to_checks.py \
    --result ./ci-eval-results/eval_result.json \
    --repo owner/repo \
    --sha <commit-sha> \
    --token <github-token>

环境变量（优先级低于命令行参数）：
  GITHUB_TOKEN     GitHub Personal Access Token 或 Actions token
  GITHUB_REPOSITORY  owner/repo
  GITHUB_SHA       当前 commit SHA
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Push SkillSentry results to GitHub Checks")
    parser.add_argument("--result", required=True, help="eval_result.json 路径")
    parser.add_argument("--repo", default=None, help="GitHub repo（owner/repo），默认读 GITHUB_REPOSITORY")
    parser.add_argument("--sha", default=None, help="Commit SHA，默认读 GITHUB_SHA")
    parser.add_argument("--token", default=None, help="GitHub token，默认读 GITHUB_TOKEN")
    parser.add_argument("--check-name", default="SkillSentry Eval", help="Check 名称")
    return parser.parse_args()


def load_result(path: str) -> dict:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def format_rate(value) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.1%}"
    return "N/A"


def format_delta(delta) -> str:
    if isinstance(delta, dict):
        value = delta.get("value")
        status = delta.get("status", "N/A")
        if isinstance(value, (int, float)):
            return f"{status} ({value:+.1%})"
        return str(status)
    if isinstance(delta, (int, float)):
        return f"{delta:+.1%}"
    return "N/A"


def check_conclusion(status: str, verdict: str) -> str:
    normalized_status = (status or "").lower()
    normalized_verdict = (verdict or "").upper()
    if normalized_status == "pass" or normalized_verdict == "PASS":
        return "success"
    if normalized_status == "conditional" or normalized_verdict == "CONDITIONAL PASS":
        return "action_required"
    return "failure"


def build_check_payload(result: dict, check_name: str, sha: str) -> dict:
    verdict = result.get("verdict", "ERROR")
    status = result.get("status") or result.get("release_status") or "error"
    exit_code = result.get("exit_code")
    summary = result.get("summary", {})
    diagnostics = result.get("diagnostics", {})
    artifacts = result.get("artifacts", {})
    reasons = result.get("reasons", [])
    skill = result.get("skill", "unknown")
    mode = result.get("mode", "unknown")

    rate = first_present(summary.get("authoritative_pass_rate"), summary.get("exact_pass_rate"))
    delta = first_present(summary.get("delta"), summary.get("avg_delta"))
    grade = summary.get("grade", "N/A")
    categories = as_list(diagnostics.get("categories")) if isinstance(diagnostics, dict) else []
    notes = as_list(diagnostics.get("notes")) if isinstance(diagnostics, dict) else []
    timing_hints = as_list(diagnostics.get("timing_hints")) if isinstance(diagnostics, dict) else []
    report_html = artifacts.get("output_report_html") or artifacts.get("session_report_html") or "N/A"

    conclusion = check_conclusion(status, verdict)

    rate_str = format_rate(rate)
    delta_str = format_delta(delta)
    category_str = ", ".join(str(item) for item in categories) if categories else "none"
    title = f"SkillSentry [{mode}] — {verdict} ({status}, {rate_str})"

    lines = [
        f"## SkillSentry 测评结果",
        f"",
        f"| 项目 | 值 |",
        f"|------|-----|",
        f"| Skill | `{skill}` |",
        f"| Mode | `{mode}` |",
        f"| Status | `{status}` |",
        f"| Exit code | `{exit_code}` |",
        f"| Grade | `{grade}` |",
        f"| Authoritative pass rate | **{rate_str}** |",
        f"| 增益 Δ | {delta_str} |",
        f"| 阈值 | {result.get('threshold', 0.8):.1%} |",
        f"| 判决 | **{verdict}** |",
        f"| Diagnostics | `{category_str}` |",
        f"| Report | `{report_html}` |",
        f"",
    ]

    if reasons:
        lines.append("### 判决原因")
        for r in reasons:
            lines.append(f"- {r}")
        lines.append("")

    if notes:
        lines.append("### 诊断说明")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    if timing_hints:
        lines.append("### Timing hints")
        for hint in timing_hints:
            lines.append(f"- {hint}")
        lines.append("")

    if isinstance(diagnostics, dict):
        executor = diagnostics.get("executor", {})
        if isinstance(executor, dict) and executor:
            lines.extend(
                [
                    "### Executor",
                    "",
                    f"- total: {executor.get('total', 0)}",
                    f"- success: {executor.get('success', 0)}",
                    f"- failed: {executor.get('failed', 0)}",
                    f"- timeouts: {executor.get('timeouts', 0)}",
                    "",
                ]
            )

    lines.append(f"*由 [SkillSentry](https://github.com/xingzaidadi/SkillSentry) 自动生成 · {result.get('evaluated_at', '')}*")

    body_text = "\n".join(lines)

    return {
        "name": check_name,
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "completed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output": {
            "title": title,
            "summary": body_text,
        },
    }


def post_check(repo: str, payload: dict, token: str) -> dict:
    url = f"https://api.github.com/repos/{repo}/check-runs"
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    args = parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY")
    sha = args.sha or os.environ.get("GITHUB_SHA")

    if not token:
        print("❌ 缺少 GitHub token（--token 或 GITHUB_TOKEN）", file=sys.stderr)
        sys.exit(1)
    if not repo:
        print("❌ 缺少 repo（--repo 或 GITHUB_REPOSITORY）", file=sys.stderr)
        sys.exit(1)
    if not sha:
        print("❌ 缺少 SHA（--sha 或 GITHUB_SHA）", file=sys.stderr)
        sys.exit(1)

    result = load_result(args.result)
    payload = build_check_payload(result, args.check_name, sha)

    try:
        resp = post_check(repo, payload, token)
        check_url = resp.get("html_url", "")
        print(f"✅ Check 创建成功: {check_url}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"❌ GitHub API 错误 {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
