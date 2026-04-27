#!/usr/bin/env python3
"""
SkillSentry 历史趋势更新器
在每次测评完成后调用，将本次结果追加到 inputs/<Skill>/history.json

用法：
  python update_history.py \
    --skill em-reimbursement-v3 \
    --session-dir ~/.openclaw/skills/skill-eval-测评/sessions/em-reimbursement-v3/2026-04-10_001 \
    [--mode quick] \
    [--git-sha abc123]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Append test run to history.json")
    parser.add_argument("--skill", required=True, help="Skill 名称")
    parser.add_argument("--session-dir", required=True, help="本次测评的 session 目录")
    parser.add_argument("--mode", default=None, help="测评模式（smoke/quick/standard/full）")
    parser.add_argument("--git-sha", default=None, help="当前 SKILL.md 对应的 git commit SHA")
    parser.add_argument("--note", default="", help="附加备注（如 PR 标题）")
    parser.add_argument("--avg-delta", type=float, default=None, dest="avg_delta",
                        help="平均增益 Δ（with_skill 精确通过率 - without_skill 精确通过率），由 sentry-report 计算后传入")
    return parser.parse_args()


def collect_grading_results(session_dir: Path) -> list[dict]:
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
                pass
    return results


def compute_entry(grading_results: list[dict], mode: str, session_dir: Path, skill: str) -> dict:
    """计算本次测评的聚合数据，格式化为历史条目"""
    total_exact = exact_passed = 0
    total_sem = sem_passed = 0
    total_all = all_passed = 0
    p95_times = []

    for r in grading_results:
        data = r["data"]
        summary = data.get("summary", {})
        breakdown = summary.get("precision_breakdown", {})

        em = breakdown.get("exact_match", {})
        total_exact += em.get("total", 0)
        exact_passed += em.get("passed", 0)

        sem = breakdown.get("semantic", {})
        total_sem += sem.get("total", 0)
        sem_passed += sem.get("passed", 0)

        total_all += summary.get("total", 0)
        all_passed += summary.get("passed", 0)

        timing = data.get("timing", {})
        if "p95_ms" in timing:
            p95_times.append(timing["p95_ms"])

    # 读取 skill hash（从 inputs/<skill>/rules.cache.json）
    skill_hash = None
    sentry_base = Path.home() / ".claude" / "skills" / "SkillSentry"
    rules_cache = sentry_base / "inputs" / skill / "rules.cache.json"
    if rules_cache.exists():
        try:
            with open(rules_cache, encoding="utf-8") as fp:
                skill_hash = json.load(fp).get("skill_hash", "")[:8]
        except Exception:
            pass

    entry = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "session": session_dir.name,
        "mode": mode or "unknown",
        "skill_hash": skill_hash,
        "eval_count": len(grading_results),
        "exact_pass_rate": round(exact_passed / total_exact, 4) if total_exact > 0 else None,
        "semantic_pass_rate": round(sem_passed / total_sem, 4) if total_sem > 0 else None,
        "overall_pass_rate": round(all_passed / total_all, 4) if total_all > 0 else None,
        "avg_delta": None,  # 由调用方（sentry-report）通过 --avg-delta 传入
        "p95_ms": round(max(p95_times), 0) if p95_times else None,
    }

    # 判决
    exact_rate = entry["exact_pass_rate"]
    delta = entry["avg_delta"]
    if exact_rate is None:
        entry["verdict"] = "ERROR"
    elif exact_rate >= 0.95 and (delta is None or delta > 0):
        entry["verdict"] = "S"
    elif exact_rate >= 0.90 and (delta is None or delta > 0):
        entry["verdict"] = "A"
    elif exact_rate >= 0.80:
        entry["verdict"] = "B"
    elif exact_rate >= 0.70:
        entry["verdict"] = "C"
    else:
        entry["verdict"] = "FAIL"

    if delta is not None and delta < 0:
        entry["verdict"] = "FAIL"

    return entry


def load_history(history_file: Path) -> list[dict]:
    if not history_file.exists():
        return []
    try:
        with open(history_file, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_history(history_file: Path, history: list[dict]):
    history_file.parent.mkdir(parents=True, exist_ok=True)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def print_trend(history: list[dict], last_n: int = 10):
    """打印最近 N 次的趋势"""
    recent = history[-last_n:]
    print(f"\n{'='*60}")
    print(f"  {recent[0].get('mode','?') if recent else '?'} 历史趋势（最近 {len(recent)} 次）")
    print(f"{'='*60}")
    print(f"  {'日期':12} {'模式':8} {'精确通过率':10} {'Δ':8} {'判决':6}")
    print(f"  {'-'*50}")
    for entry in recent:
        run_at = entry.get("run_at", "")[:10]
        mode = entry.get("mode", "?")[:7]
        exact = f"{entry['exact_pass_rate']:.1%}" if entry.get("exact_pass_rate") is not None else "N/A"
        delta = f"{entry['avg_delta']:+.1%}" if entry.get("avg_delta") is not None else "N/A"
        verdict = entry.get("verdict", "?")
        verdict_icon = {"S": "🏆", "A": "✅", "B": "⚠️", "C": "⚠️", "FAIL": "❌", "ERROR": "💥"}.get(verdict, "?")
        print(f"  {run_at:12} {mode:8} {exact:10} {delta:8} {verdict_icon} {verdict}")

    # 趋势判断
    if len(recent) >= 3:
        rates = [e["exact_pass_rate"] for e in recent[-3:] if e.get("exact_pass_rate") is not None]
        if len(rates) >= 3:
            if rates[-1] > rates[0]:
                print(f"\n  📈 趋势：精确通过率上升（{rates[0]:.1%} → {rates[-1]:.1%}）")
            elif rates[-1] < rates[0]:
                print(f"\n  📉 趋势：精确通过率下降（{rates[0]:.1%} → {rates[-1]:.1%}）")
            else:
                print(f"\n  ➡️  趋势：精确通过率持平")
    print(f"{'='*60}\n")


def main():
    args = parse_args()
    session_dir = Path(args.session_dir).expanduser()

    if not session_dir.exists():
        print(f"❌ Session 目录不存在: {session_dir}", file=sys.stderr)
        sys.exit(1)

    # 找 inputs/<Skill>/ 下的 history.json
    sentry_base = Path.home() / ".claude" / "skills" / "SkillSentry"
    inputs_dir = sentry_base / "inputs" / args.skill
    history_file = inputs_dir / "history.json"

    # 收集本次结果
    grading_results = collect_grading_results(session_dir)
    if not grading_results:
        print("⚠️ 没有 grading.json，跳过历史更新", file=sys.stderr)
        sys.exit(0)

    # 计算本次条目
    entry = compute_entry(grading_results, args.mode, session_dir, args.skill)
    if args.git_sha:
        entry["git_sha"] = args.git_sha[:8]
    if args.note:
        entry["note"] = args.note
    if args.avg_delta is not None:
        entry["avg_delta"] = round(args.avg_delta, 4)
        # 有 delta 时重新判决：delta < 0 直接 FAIL
        if args.avg_delta < 0 and entry.get("verdict") not in ("ERROR", "FAIL"):
            entry["verdict"] = "FAIL"

    # 加载 + 幂等检查 + 追加 + 保存
    history = load_history(history_file)
    if any(e.get("session") == entry["session"] for e in history):
        print(f"ℹ️  Session {entry['session']} 已在历史记录中，跳过重复追加")
        print_trend(history)
        sys.exit(0)
    history.append(entry)
    save_history(history_file, history)

    print(f"✅ 历史记录已更新: {history_file}")
    print(f"   本次：精确通过率 {entry.get('exact_pass_rate', 'N/A')}，判决 {entry.get('verdict')}")
    print(f"   总计 {len(history)} 条历史记录")

    print_trend(history)


if __name__ == "__main__":
    main()
