#!/usr/bin/env python3
"""
SkillSentry CI 编排入口
确定性 pipeline 执行，适用于 GitHub Actions 和本地 CI。

用法：
  python sentry_ci.py --skill <name|path> [--mode smoke|quick|regression] \
    [--threshold 0.8] [--output-dir ./results] [--model claude-sonnet-4-6] [--timeout 1800]

退出码：0=PASS, 1=FAIL, 2=ERROR

架构：
  cases/grader → Anthropic SDK 直调（纯文本推理）
  executor → claude CLI subprocess（需要 tool use）
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 本地模块
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))


def parse_args():
    parser = argparse.ArgumentParser(
        description="SkillSentry CI Runner — 确定性 pipeline 编排",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # Smoke 测评（最快，CI 默认）
  python sentry_ci.py --skill em-reimbursement-v3 --mode smoke

  # Quick 测评（PR 合并前）
  python sentry_ci.py --skill my-skill --mode quick --threshold 0.85

  # Regression（复用已有 cases）
  python sentry_ci.py --skill my-skill --mode regression --cases ./evals.json
        """,
    )
    parser.add_argument("--skill", required=True, help="被测 Skill 名称或 SKILL.md 路径")
    parser.add_argument(
        "--mode",
        choices=["smoke", "quick", "regression"],
        default="smoke",
        help="测评模式（默认 smoke）",
    )
    parser.add_argument("--threshold", type=float, default=0.8, help="通过率阈值（默认 0.80）")
    parser.add_argument("--output-dir", default="./ci-eval-results", help="结果输出目录")
    parser.add_argument("--cases", default=None, help="指定 evals.json 路径（regression 模式必需）")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="LLM model（SDK 调用用）")
    parser.add_argument("--executor-model", default=None, help="executor 使用的 claude CLI model（默认同 --model）")
    parser.add_argument("--timeout", type=int, default=1800, help="总超时秒数（默认 30 分钟）")
    parser.add_argument("--max-retries", type=int, default=1, help="每步失败后重试次数")
    parser.add_argument("--github-output", action="store_true", help="输出 GitHub Actions 变量")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    return parser.parse_args()


def log(msg: str, verbose_only: bool = False):
    """统一日志输出"""
    if verbose_only and not getattr(log, "_verbose", False):
        return
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", file=sys.stderr)


def find_skill(skill_arg: str) -> Path | None:
    """定位 SKILL.md 文件"""
    # 直接路径
    p = Path(skill_arg)
    if p.is_file() and p.name == "SKILL.md":
        return p
    if p.is_dir() and (p / "SKILL.md").exists():
        return p / "SKILL.md"

    # 按名称搜索
    search_paths = [
        Path.home() / ".claude" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".config" / "opencode" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".openclaw" / "skills" / skill_arg / "SKILL.md",
        Path.home() / ".openclaw" / "workspace" / "skills" / skill_arg / "SKILL.md",
    ]
    for sp in search_paths:
        if sp.exists():
            return sp
    return None


def detect_skill_type(skill_md_content: str) -> str:
    """检测 skill_type: mcp_based / code_execution / text_generation"""
    # MCP: 含 camelCase 工具名（如 feishu_app_bitable_*、budget_*）
    if re.search(r"[a-z]+_[a-z]+_[a-z]+\(", skill_md_content) or \
       re.search(r"mcporter|MCP\s*(Server|Tool)", skill_md_content, re.IGNORECASE):
        return "mcp_based"
    # Code execution: 含 bash/python/exec
    if re.search(r"\b(bash|python|exec|subprocess|shell)\b", skill_md_content, re.IGNORECASE):
        return "code_execution"
    return "text_generation"


def compute_skill_hash(skill_md_path: Path) -> str:
    """计算 SKILL.md 的 MD5"""
    content = skill_md_path.read_bytes()
    return hashlib.md5(content).hexdigest()


def init_session(skill_name: str, skill_hash: str, skill_type: str, mode: str) -> Path:
    """创建 session 目录和初始 session.json"""
    base = Path.home() / ".claude" / "skills" / "SkillSentry" / "sessions" / skill_name
    base.mkdir(parents=True, exist_ok=True)

    # 找下一个序号
    today = datetime.now().strftime("%Y-%m-%d")
    existing = sorted([d.name for d in base.iterdir() if d.name.startswith(today)])
    if existing:
        last_num = int(existing[-1].split("_")[-1])
        session_name = f"{today}_{last_num + 1:03d}"
    else:
        session_name = f"{today}_001"

    session_dir = base / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    session_data = {
        "skill": skill_name,
        "mode": mode,
        "skill_type": skill_type,
        "skill_hash": skill_hash,
        "runtime": "ci",
        "mcp_backend": "unavailable",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_step": "init",
        "ci": True,
    }

    with open(session_dir / "session.json", "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    return session_dir


def get_pipeline(mode: str, skill_type: str) -> list[str]:
    """根据 mode 和 skill_type 返回 pipeline 步骤"""
    if skill_type == "mcp_based":
        # MCP Skill: 跳过 executor，只做静态分析 + 用例设计
        if mode == "regression":
            return []  # regression 无意义（无法执行）
        return ["cases"]  # smoke/quick: 只生成用例验证覆盖度

    if mode == "smoke":
        return ["cases", "executor", "grader"]
    elif mode == "quick":
        return ["check", "cases", "executor", "grader"]
    elif mode == "regression":
        return ["executor", "grader"]
    return ["cases", "executor", "grader"]


def find_existing_cases(skill_name: str) -> Path | None:
    """查找已有的 cases 缓存"""
    inputs_dir = Path.home() / ".claude" / "skills" / "SkillSentry" / "inputs" / skill_name
    candidates = [
        inputs_dir / "cases.cache.json",
        inputs_dir / "evals.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def update_session(session_dir: Path, step: str, data: dict):
    """更新 session.json"""
    session_file = session_dir / "session.json"
    with open(session_file, encoding="utf-8") as f:
        session = json.load(f)
    session["last_step"] = step
    session.update(data)
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def run_step(step: str, session_dir: Path, skill_path: Path, args, **kwargs) -> bool:
    """执行单个 pipeline 步骤，返回 True=成功"""
    log(f"🔧 执行: {step}")
    start = time.time()

    try:
        if step == "check":
            success = run_check(session_dir, skill_path, args)
        elif step == "cases":
            success = run_cases(session_dir, skill_path, args, **kwargs)
        elif step == "executor":
            success = run_executor(session_dir, skill_path, args)
        elif step == "grader":
            success = run_grader(session_dir, skill_path, args)
        else:
            log(f"  ❌ 未知步骤: {step}")
            return False

        elapsed = time.time() - start
        status = "✅" if success else "❌"
        log(f"  {status} {step} 完成 ({elapsed:.1f}s)")
        return success

    except Exception as e:
        elapsed = time.time() - start
        log(f"  ❌ {step} 异常 ({elapsed:.1f}s): {e}")
        return False


def run_check(session_dir: Path, skill_path: Path, args) -> bool:
    """静态检查（lint + trigger）— 用 SDK"""
    from ci_grader import call_llm

    skill_content = skill_path.read_text(encoding="utf-8")

    prompt = f"""你是 SkillSentry 的静态检查模块。请对以下 SKILL.md 做结构检查和触发率评估。

检查项：
- L1: frontmatter 完整性（name, description 必须存在）
- L2: 触发/不触发场景是否明确
- L3: 流程步骤是否有明确输入输出
- P0 问题：致命缺陷（如缺少 name/description、无触发条件）
- P1 问题：重要缺陷
- P2 问题：建议改进

触发率评估：
- 给出 5 个应该触发的用户消息（TP）
- 给出 5 个不应该触发的用户消息（TN）
- 估算触发准确率

请以 JSON 格式返回结果：
{{"lint": {{"L1": "pass/fail", "L2": "pass/fail", "L3": 0, "P0": 0, "P1": 0, "P2": 0, "issues": []}}, "trigger": {{"tp": 0, "tn": 0, "confidence": "high/medium/low", "issues": []}}}}

SKILL.md 内容：
```
{skill_content}
```"""

    result = call_llm(prompt, model=args.model, max_tokens=2000)
    if not result:
        return False

    # 尝试解析 JSON
    try:
        # 提取 JSON（可能被 markdown 包裹）
        json_match = re.search(r"\{[\s\S]*\}", result)
        if json_match:
            check_data = json.loads(json_match.group())
            update_session(session_dir, "check", {
                "lint": check_data.get("lint", {}),
                "trigger": check_data.get("trigger", {}),
            })

            # 检查 P0
            p0_count = check_data.get("lint", {}).get("P0", 0)
            if p0_count > 0:
                log(f"  ⚠️ 发现 {p0_count} 个 P0 问题")
            return True
    except json.JSONDecodeError:
        log("  ⚠️ check 结果 JSON 解析失败，继续")

    return True  # check 不阻断 pipeline


def run_cases(session_dir: Path, skill_path: Path, args, existing_cases: Path = None) -> bool:
    """生成测试用例 — 用 SDK"""
    from ci_grader import call_llm

    # 如果有现成 cases，直接复用
    if existing_cases and existing_cases.exists():
        import shutil
        shutil.copy2(existing_cases, session_dir / "evals.json")
        log(f"  ⚡ 复用已有用例: {existing_cases}")
        return True

    skill_content = skill_path.read_text(encoding="utf-8")
    case_count = 5 if args.mode == "smoke" else 8

    prompt = f"""你是 SkillSentry 的用例设计模块。请为以下 SKILL.md 设计 {case_count} 个测试用例。

用例类型分布要求：
- happy_path: 正常流程（至少 2 个）
- edge_case: 边界情况（至少 1 个）
- negative: 应拒绝/降级的输入（至少 1 个）
- robustness: 模糊/不完整输入（至少 1 个）

每个用例必须包含：
- id: 唯一标识（如 "eval-1"）
- type: 用例类型
- name: 用例名称（中文简述）
- prompt: 模拟用户输入
- assertions: 断言列表，每个断言包含 {{name, type(exact_match/semantic/existence), expected, rule_ref}}

请以 JSON 数组格式返回（直接返回 JSON，不要 markdown 包裹）：
[{{"id": "eval-1", "type": "happy_path", "name": "...", "prompt": "...", "assertions": [...]}}]

SKILL.md 内容：
```
{skill_content}
```"""

    result = call_llm(prompt, model=args.model, max_tokens=4000)
    if not result:
        log("  ❌ 用例生成 LLM 调用失败")
        return False

    try:
        # 提取 JSON 数组
        json_match = re.search(r"\[[\s\S]*\]", result)
        if json_match:
            cases = json.loads(json_match.group())
            with open(session_dir / "evals.json", "w", encoding="utf-8") as f:
                json.dump(cases, f, ensure_ascii=False, indent=2)
            log(f"  📋 生成 {len(cases)} 个用例")
            update_session(session_dir, "cases", {
                "cases": {"total": len(cases), "types": {}}
            })
            return True
    except json.JSONDecodeError as e:
        log(f"  ❌ 用例 JSON 解析失败: {e}")

    return False


def run_executor(session_dir: Path, skill_path: Path, args) -> bool:
    """执行测试用例 — 用 claude CLI"""
    from ci_executor import execute_all_evals

    evals_file = session_dir / "evals.json"
    if not evals_file.exists():
        log("  ❌ evals.json 不存在，无法执行")
        return False

    model = args.executor_model or args.model
    success = execute_all_evals(
        evals_file=evals_file,
        skill_path=skill_path,
        session_dir=session_dir,
        model=model,
        timeout_per_eval=120,
        verbose=args.verbose,
    )

    return success


def run_grader(session_dir: Path, skill_path: Path, args) -> bool:
    """评审断言 — 用 SDK"""
    from ci_grader import grade_all_evals

    evals_file = session_dir / "evals.json"
    if not evals_file.exists():
        log("  ❌ evals.json 不存在，无法评审")
        return False

    success = grade_all_evals(
        evals_file=evals_file,
        session_dir=session_dir,
        model=args.model,
        verbose=args.verbose,
    )

    return success


def collect_results(session_dir: Path, args) -> dict:
    """收集所有 grading 结果，计算汇总"""
    from ci_eval import collect_grading_results, compute_summary, determine_verdict

    grading_results = collect_grading_results(session_dir)
    if not grading_results:
        return {"verdict": "ERROR", "reasons": ["无 grading 结果"], "summary": {}}

    summary = compute_summary(grading_results)
    verdict, reasons = determine_verdict(summary, args.threshold, True)

    return {"verdict": verdict, "reasons": reasons, "summary": summary}


def write_ci_output(output_dir: Path, results: dict, args):
    """写入 CI 输出文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    output = {
        "skill": args.skill,
        "mode": args.mode,
        "threshold": args.threshold,
        "verdict": results["verdict"],
        "reasons": results["reasons"],
        "summary": results["summary"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_dir / "eval_result.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # GitHub Step Summary
    summary_md = f"""## SkillSentry CI — {results['verdict']}

| 项目 | 值 |
|------|-----|
| Skill | `{args.skill}` |
| Mode | `{args.mode}` |
| Threshold | {args.threshold:.0%} |
| Verdict | **{results['verdict']}** |
"""
    s = results.get("summary", {})
    if s.get("exact_pass_rate") is not None:
        summary_md += f"| Exact Pass Rate | {s['exact_pass_rate']:.1%} |\n"
    if s.get("eval_count"):
        summary_md += f"| Eval Count | {s['eval_count']} |\n"

    if results["reasons"]:
        summary_md += "\n### Reasons\n"
        for r in results["reasons"]:
            summary_md += f"- {r}\n"

    with open(output_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(summary_md)

    # GITHUB_STEP_SUMMARY
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as f:
            f.write(summary_md)

    # GITHUB_OUTPUT
    if args.github_output:
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"verdict={results['verdict']}\n")
                rate = s.get("exact_pass_rate")
                f.write(f"exact_pass_rate={rate:.4f}\n" if rate else "exact_pass_rate=N/A\n")


def main():
    args = parse_args()
    log._verbose = args.verbose

    log(f"🦞 SkillSentry CI v7.8.2 — mode={args.mode}, threshold={args.threshold:.0%}")

    # 1. 定位 Skill
    skill_path = find_skill(args.skill)
    if not skill_path:
        log(f"❌ 找不到 Skill: {args.skill}")
        sys.exit(2)
    log(f"📂 Skill: {skill_path}")

    skill_name = skill_path.parent.name
    skill_content = skill_path.read_text(encoding="utf-8")

    # 2. 检测 skill_type
    skill_type = detect_skill_type(skill_content)
    skill_hash = compute_skill_hash(skill_path)
    log(f"📋 Type: {skill_type} | Hash: {skill_hash[:8]}")

    # 3. 初始化 session
    session_dir = init_session(skill_name, skill_hash, skill_type, args.mode)
    log(f"📁 Session: {session_dir}")

    # 4. 确定 pipeline
    pipeline = get_pipeline(args.mode, skill_type)
    if not pipeline:
        log("⚠️ 无可执行步骤（mcp_based + regression 组合无意义）")
        sys.exit(2)
    log(f"🔗 Pipeline: {' → '.join(pipeline)}")

    if skill_type == "mcp_based":
        log("⚠️ MCP Skill: 跳过 executor，只做静态分析 + 用例设计")

    # 5. 查找已有 cases（regression 模式或缓存命中）
    existing_cases = None
    if args.cases:
        existing_cases = Path(args.cases)
    elif args.mode == "regression":
        existing_cases = find_existing_cases(skill_name)
        if not existing_cases:
            log("❌ regression 模式需要已有 cases，但未找到缓存")
            sys.exit(2)

    # 6. 执行 pipeline
    start_time = time.time()
    failed_steps = []

    for step in pipeline:
        elapsed = time.time() - start_time
        if elapsed > args.timeout:
            log(f"⏰ 总超时 ({args.timeout}s)，终止")
            failed_steps.append(f"{step}(timeout)")
            break

        kwargs = {}
        if step == "cases" and existing_cases:
            kwargs["existing_cases"] = existing_cases

        success = run_step(step, session_dir, skill_path, args, **kwargs)
        if not success:
            # 重试
            for retry in range(args.max_retries):
                log(f"  🔄 重试 {step} ({retry + 1}/{args.max_retries})")
                success = run_step(step, session_dir, skill_path, args, **kwargs)
                if success:
                    break
            if not success:
                failed_steps.append(step)
                if step in ("cases", "executor"):
                    log(f"  ⛔ {step} 失败，后续步骤无法执行，终止 pipeline")
                    break

    total_time = time.time() - start_time
    log(f"⏱️ Pipeline 完成 ({total_time:.1f}s)")

    # 7. 收集结果
    if "grader" not in failed_steps and "grader" in pipeline:
        results = collect_results(session_dir, args)
    elif skill_type == "mcp_based":
        # MCP Skill: 只有 cases 步骤，给 DEGRADED 判决
        results = {
            "verdict": "DEGRADED",
            "reasons": ["mcp_based Skill: CI 模式下跳过 executor，仅验证用例覆盖度"],
            "summary": {"eval_count": 0, "note": "skipped_no_mcp"},
        }
    else:
        results = {
            "verdict": "ERROR",
            "reasons": [f"Pipeline 步骤失败: {', '.join(failed_steps)}"],
            "summary": {},
        }

    # 8. 输出
    output_dir = Path(args.output_dir)
    write_ci_output(output_dir, results, args)

    # 9. 打印结果
    verdict = results["verdict"]
    print(f"\n{'=' * 50}")
    print(f"  🦞 SkillSentry CI Result")
    print(f"  Skill:     {args.skill}")
    print(f"  Mode:      {args.mode}")
    print(f"  Type:      {skill_type}")
    print(f"  Verdict:   {verdict}")
    for r in results.get("reasons", []):
        print(f"             → {r}")
    print(f"  Time:      {total_time:.1f}s")
    print(f"  Output:    {output_dir}")
    print(f"{'=' * 50}\n")

    # 10. 退出码
    if verdict == "PASS":
        sys.exit(0)
    elif verdict == "DEGRADED":
        sys.exit(0)  # DEGRADED 不 block CI
    elif verdict == "ERROR":
        sys.exit(2)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
