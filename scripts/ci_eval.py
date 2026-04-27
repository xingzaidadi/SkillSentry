#!/usr/bin/env python3
"""
SkillSentry CI 运行器
用法：python ci_eval.py --skill <skill名> [--mode smoke|quick] [--threshold 0.8] [--output-dir ./ci-results]
返回码：0 = PASS，1 = FAIL，2 = 运行错误
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(description="SkillSentry CI Runner")
    parser.add_argument("--skill", required=True, help="被测 Skill 名称或 SKILL.md 路径")
    parser.add_argument(
        "--mode",
        choices=["smoke", "quick"],
        default="smoke",
        help="测评模式（CI 推荐 smoke，PR 合并前用 quick）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="精确通过率阈值，低于此值返回退出码 1（默认 0.80）",
    )
    parser.add_argument(
        "--output-dir",
        default="./ci-eval-results",
        help="结果输出目录（默认 ./ci-eval-results）",
    )
    parser.add_argument(
        "--session-dir",
        default=None,
        help="指定 SkillSentry session 目录（默认从 ~/.openclaw/skills/skill-eval-测评/sessions/ 查找最新）",
    )
    parser.add_argument(
        "--fail-on-negative-delta",
        action="store_true",
        default=True,
        help="Δ < 0 时强制 FAIL（默认开启，对应红线之一）",
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="输出 GitHub Actions 格式的 GITHUB_OUTPUT 变量",
    )
    return parser.parse_args()


def find_latest_session(skill_name: str) -> Path | None:
    """在 SkillSentry sessions 目录查找最新的 session"""
    base = Path.home() / ".claude" / "skills" / "SkillSentry" / "sessions" / skill_name
    if not base.exists():
        return None
    sessions = sorted(base.iterdir(), reverse=True)
    return sessions[0] if sessions else None


def collect_grading_results(session_dir: Path) -> list[dict]:
    """从 session 目录收集所有 grading.json"""
    results = []
    for eval_dir in sorted(session_dir.iterdir()):
        if not eval_dir.name.startswith("eval-"):
            continue
        grading_file = eval_dir / "grading.json"
        if grading_file.exists():
            try:
                with open(grading_file, encoding="utf-8") as f:
                    results.append({"eval": eval_dir.name, "data": json.load(f)})
            except json.JSONDecodeError:
                print(f"⚠️  {grading_file} 解析失败，跳过", file=sys.stderr)
    return results


def compute_summary(grading_results: list[dict]) -> dict:
    """聚合所有 eval 的结果，计算整体通过率"""
    total_exact = 0
    passed_exact = 0
    total_semantic = 0
    passed_semantic = 0
    total_all = 0
    passed_all = 0
    deltas = []
    failed_evals = []

    for r in grading_results:
        data = r["data"]
        summary = data.get("summary", {})
        breakdown = summary.get("precision_breakdown", {})

        # exact_match
        em = breakdown.get("exact_match", {})
        em_total = em.get("total", 0)
        em_passed = em.get("passed", 0)
        total_exact += em_total
        passed_exact += em_passed

        # semantic
        sem = breakdown.get("semantic", {})
        sem_total = sem.get("total", 0)
        sem_passed = sem.get("passed", 0)
        total_semantic += sem_total
        passed_semantic += sem_passed

        # all
        total_all += summary.get("total", 0)
        passed_all += summary.get("passed", 0)

        # delta
        if "delta" in data:
            deltas.append(data["delta"])

        # failed evals
        if summary.get("authoritative_pass_rate", 1.0) < 1.0:
            failed_evals.append(r["eval"])

    return {
        "exact_pass_rate": passed_exact / total_exact if total_exact > 0 else None,
        "semantic_pass_rate": passed_semantic / total_semantic if total_semantic > 0 else None,
        "overall_pass_rate": passed_all / total_all if total_all > 0 else None,
        "avg_delta": sum(deltas) / len(deltas) if deltas else None,
        "eval_count": len(grading_results),
        "failed_evals": failed_evals,
        "exact_total": total_exact,
        "exact_passed": passed_exact,
    }


def determine_verdict(summary: dict, threshold: float, fail_on_negative_delta: bool) -> tuple[str, list[str]]:
    """根据汇总结果给出 PASS / FAIL 判决"""
    reasons = []
    verdict = "PASS"

    exact_rate = summary.get("exact_pass_rate")
    if exact_rate is None:
        return "ERROR", ["找不到 exact_match 断言数据，无法判断"]

    if exact_rate < threshold:
        verdict = "FAIL"
        reasons.append(f"精确通过率 {exact_rate:.1%} < 阈值 {threshold:.1%}")

    delta = summary.get("avg_delta")
    if fail_on_negative_delta and delta is not None and delta < 0:
        verdict = "FAIL"
        reasons.append(f"Δ = {delta:.1%} < 0（加了 Skill 比没加更差）")

    if not reasons and verdict == "PASS":
        reasons.append(f"精确通过率 {exact_rate:.1%} ≥ 阈值 {threshold:.1%}")

    return verdict, reasons


def write_output(output_dir: Path, summary: dict, verdict: str, reasons: list[str], args):
    """写入 CI 结果文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "skill": args.skill,
        "mode": args.mode,
        "threshold": args.threshold,
        "verdict": verdict,
        "reasons": reasons,
        "summary": summary,
        "evaluated_at": datetime.utcnow().isoformat() + "Z",
    }

    result_file = output_dir / "eval_result.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    summary_file = output_dir / "summary.txt"
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(f"Skill: {args.skill}\n")
        f.write(f"Mode: {args.mode}\n")
        f.write(f"Verdict: {verdict}\n")
        f.write(f"Exact Pass Rate: {summary.get('exact_pass_rate', 'N/A')}\n")
        if summary.get('avg_delta') is not None:
            f.write(f"Avg Delta: {summary['avg_delta']:.1%}\n")
        f.write(f"Eval Count: {summary.get('eval_count', 0)}\n")
        f.write("\nReasons:\n")
        for r in reasons:
            f.write(f"  - {r}\n")

    print(f"📄 结果已写入 {output_dir}", file=sys.stderr)
    return result_file


def set_github_outputs(summary: dict, verdict: str):
    """写入 GitHub Actions GITHUB_OUTPUT"""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return

    exact_rate = summary.get("exact_pass_rate")
    delta = summary.get("avg_delta")

    with open(github_output, "a", encoding="utf-8") as f:
        f.write(f"verdict={verdict}\n")
        f.write(f"exact_pass_rate={exact_rate:.4f}\n" if exact_rate is not None else "exact_pass_rate=N/A\n")
        f.write(f"delta={delta:.4f}\n" if delta is not None else "delta=N/A\n")
        f.write(f"eval_count={summary.get('eval_count', 0)}\n")


def main():
    args = parse_args()

    # 找 session 目录
    if args.session_dir:
        session_dir = Path(args.session_dir)
    else:
        skill_name = Path(args.skill).stem if "/" in args.skill or "\\" in args.skill else args.skill
        session_dir = find_latest_session(skill_name)

    if not session_dir or not session_dir.exists():
        print(f"❌ 找不到 session 目录（Skill: {args.skill}）", file=sys.stderr)
        print("请先运行 SkillSentry 测评，再执行 CI 汇总", file=sys.stderr)
        sys.exit(2)

    print(f"📂 Session 目录: {session_dir}", file=sys.stderr)

    # 收集 grading 结果
    grading_results = collect_grading_results(session_dir)
    if not grading_results:
        print("❌ session 目录下没有 grading.json，测评尚未完成", file=sys.stderr)
        sys.exit(2)

    print(f"✅ 找到 {len(grading_results)} 个 eval 结果", file=sys.stderr)

    # 计算汇总
    summary = compute_summary(grading_results)

    # 给出判决
    verdict, reasons = determine_verdict(summary, args.threshold, args.fail_on_negative_delta)

    # 输出到文件
    output_dir = Path(args.output_dir)
    write_output(output_dir, summary, verdict, reasons, args)

    # GitHub Actions 输出
    if args.github_output:
        set_github_outputs(summary, verdict)

    # 打印结果
    exact_rate = summary.get("exact_pass_rate")
    delta = summary.get("avg_delta")

    print(f"\n{'='*50}")
    print(f"  Skill:       {args.skill}")
    print(f"  Mode:        {args.mode}")
    print(f"  Eval count:  {summary['eval_count']}")
    print(f"  Exact rate:  {exact_rate:.1%}" if exact_rate is not None else "  Exact rate:  N/A")
    print(f"  Avg delta:   {delta:+.1%}" if delta is not None else "  Avg delta:   N/A")
    print(f"  Verdict:     {verdict}")
    for r in reasons:
        print(f"               → {r}")
    print(f"{'='*50}\n")

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
