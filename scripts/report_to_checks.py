#!/usr/bin/env python3
"""
SkillSentry → GitHub Checks API 桥接器
把 ci_eval.py 输出的 eval_result.json 推送到 GitHub Checks

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


def parse_args():
    parser = argparse.ArgumentParser(description="Push SkillSentry results to GitHub Checks")
    parser.add_argument("--result", required=True, help="eval_result.json 路径")
    parser.add_argument("--repo", default=None, help="GitHub repo（owner/repo），默认读 GITHUB_REPOSITORY")
    parser.add_argument("--sha", default=None, help="Commit SHA，默认读 GITHUB_SHA")
    parser.add_argument("--token", default=None, help="GitHub token，默认读 GITHUB_TOKEN")
    parser.add_argument("--check-name", default="SkillSentry Eval", help="Check 名称")
    return parser.parse_args()


def load_result(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_check_payload(result: dict, check_name: str, sha: str) -> dict:
    verdict = result["verdict"]
    summary = result["summary"]
    reasons = result.get("reasons", [])
    skill = result["skill"]
    mode = result["mode"]

    exact_rate = summary.get("exact_pass_rate")
    delta = summary.get("avg_delta")

    # GitHub Checks conclusion
    conclusion = "success" if verdict == "PASS" else "failure"

    # 标题行
    rate_str = f"{exact_rate:.1%}" if exact_rate is not None else "N/A"
    delta_str = f"{delta:+.1%}" if delta is not None else "N/A"
    title = f"SkillSentry [{mode}] — {verdict} (精确通过率 {rate_str}, Δ {delta_str})"

    # 正文（Markdown）
    lines = [
        f"## SkillSentry 测评结果",
        f"",
        f"| 项目 | 值 |",
        f"|------|-----|",
        f"| Skill | `{skill}` |",
        f"| Mode | `{mode}` |",
        f"| Eval 数 | {summary.get('eval_count', 0)} |",
        f"| 精确通过率 | **{rate_str}** |",
        f"| 增益 Δ | {delta_str} |",
        f"| 阈值 | {result.get('threshold', 0.8):.1%} |",
        f"| 判决 | **{verdict}** |",
        f"",
    ]

    if reasons:
        lines.append("### 判决原因")
        for r in reasons:
            lines.append(f"- {r}")
        lines.append("")

    failed_evals = summary.get("failed_evals", [])
    if failed_evals:
        lines.append("### 未通过用例")
        for e in failed_evals:
            lines.append(f"- `{e}`")
        lines.append("")

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
