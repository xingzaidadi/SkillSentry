#!/usr/bin/env python3
"""sentry_quick_check.py — 单用例快速验证

不走完整 pipeline，直接：
  1. 执行一个用例（executor）
  2. 评审断言（确定性 grader，semantic 也走 LLM）
  3. 打印结果

目标：30s 内出结果，适合日常迭代微调。

用法示例
--------
# 方式一：直接传入 prompt 和断言
python scripts/sentry_quick_check.py \\
    --skill C:/path/to/SKILL.md \\
    --prompt "用户说报销这张发票" \\
    --assert "exact_match:单据状态=10"

# 方式二：引用 evals.json 中某个用例
python scripts/sentry_quick_check.py \\
    --skill C:/path/to/SKILL.md \\
    --evals path/to/evals.json \\
    --case-id eval-1

# 断言格式：<type>:<expected>
#   exact_match:期望文本
#   existence:期望关键词
#   semantic:期望语义描述
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ci_executor import execute_single_eval
from ci_grader import grade_exact_match, grade_existence, call_llm, build_grading_prompt

# ─── ANSI 颜色 ─────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _color(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


# ─── 断言解析 ───────────────────────────────────────────────────────────────
def parse_assertion_str(s: str, idx: int) -> dict:
    """解析 'type:expected' 格式的断言字符串。"""
    known_types = ("exact_match", "existence", "semantic")
    for t in known_types:
        prefix = f"{t}:"
        if s.startswith(prefix):
            return {"name": f"A{idx+1}", "type": t, "expected": s[len(prefix):]}
    # 没有前缀，默认 semantic
    return {"name": f"A{idx+1}", "type": "semantic", "expected": s}


# ─── 单条断言评审 ───────────────────────────────────────────────────────────
def grade_one_assertion(a: dict, response_text: str, model: str) -> dict:
    a_type = a.get("type", "semantic")
    a_expected = a.get("expected", "")
    a_name = a.get("name", "A1")

    if a_type == "exact_match":
        passed, evidence = grade_exact_match(a_expected, response_text)
        return {**a, "pass": passed, "evidence": evidence, "graded_by": "deterministic"}
    elif a_type == "existence":
        passed, evidence = grade_existence(a_expected, response_text)
        return {**a, "pass": passed, "evidence": evidence, "graded_by": "deterministic"}
    else:
        # semantic → LLM
        fake_eval = {"name": a_name, "assertions": [a]}
        prompt = build_grading_prompt(fake_eval, response_text, response_text, [a])
        result = call_llm(prompt, model=model, max_tokens=800)
        if not result:
            return {**a, "pass": False, "evidence": "LLM grader call failed", "graded_by": "llm"}
        import re
        m = re.search(r"\{[\s\S]*\}", result)
        if not m:
            return {**a, "pass": False, "evidence": "LLM returned no JSON", "graded_by": "llm"}
        try:
            data = json.loads(m.group())
            graded = data.get("assertions", [])
            if graded:
                g = graded[0]
                return {**a, "pass": g.get("pass", False), "evidence": g.get("evidence", ""), "graded_by": "llm"}
        except json.JSONDecodeError:
            pass
        return {**a, "pass": False, "evidence": "LLM JSON parse error", "graded_by": "llm"}


# ─── 主逻辑 ─────────────────────────────────────────────────────────────────
def quick_check(
    *,
    skill_path: Path,
    prompt_text: str,
    assertions: list[dict],
    case_name: str = "quick-check",
    model_exec: str = "sonnet",
    model_grade: str = "claude-sonnet-4-6",
    timeout: int = 120,
    verbose: bool = False,
) -> dict:
    """运行单个用例并立即评审，返回结果 dict。"""
    t0 = time.time()

    eval_config = {
        "id": "eval-quick",
        "name": case_name,
        "prompt": prompt_text,
        "assertions": assertions,
    }

    with tempfile.TemporaryDirectory(prefix="sentry_quick_") as tmpdir:
        session_dir = Path(tmpdir)

        # Step 1: execute
        print(_color(f"\n▶ 执行用例「{case_name}」...", CYAN))
        exec_result = execute_single_eval(
            eval_config=eval_config,
            skill_path=skill_path,
            session_dir=session_dir,
            eval_idx=1,
            model=model_exec,
            timeout=timeout,
            verbose=verbose,
            variant="with_skill",
        )

        exec_status = exec_result.get("status", "unknown")
        exec_dur = exec_result.get("duration", 0)
        print(f"  executor: {exec_status} ({exec_dur:.1f}s)")

        # 读取 response
        response_file = session_dir / "eval-quick" / "with_skill" / "outputs" / "response.md"
        if not response_file.exists() or exec_status != "success":
            error_msg = exec_result.get("error", "executor failed")
            print(_color(f"\n✗ 执行失败: {error_msg}", RED))
            return {"status": "EXEC_FAILED", "error": error_msg, "elapsed": time.time() - t0}

        response_text = response_file.read_text(encoding="utf-8")
        resp_len = len(response_text)
        print(f"  response: {resp_len} chars")

        if verbose:
            # 打印 response 前 300 字
            preview = response_text[:300].replace("\n", " ")
            print(f"\n  {_color('Response preview:', YELLOW)}\n  {preview}{'...' if resp_len > 300 else ''}\n")

        # Step 2: grade
        print(_color(f"\n▶ 评审 {len(assertions)} 条断言...", CYAN))
        graded: list[dict] = []
        for a in assertions:
            r = grade_one_assertion(a, response_text, model=model_grade)
            graded.append(r)
            status_icon = _color("✓", GREEN) if r["pass"] else _color("✗", RED)
            method_tag = f"[{r.get('graded_by', '?')}]"
            print(f"  {status_icon} [{r.get('type','?')}] {r.get('name','')} {method_tag}")
            print(f"     expect: {r.get('expected','')[:80]}")
            print(f"     evidence: {r.get('evidence','')[:80]}")

        total = len(graded)
        passed = sum(1 for r in graded if r["pass"])
        elapsed = time.time() - t0

        result_color = GREEN if passed == total else RED
        print(_color(f"\n{'='*50}", result_color))
        label = "PASS ✅" if passed == total else "FAIL ❌"
        print(_color(f"  {label}  {passed}/{total} 断言通过  ({elapsed:.1f}s)", result_color) + _color("", BOLD))
        print(_color(f"{'='*50}\n", result_color))

        return {
            "status": "PASS" if passed == total else "FAIL",
            "pass": passed,
            "total": total,
            "elapsed": elapsed,
            "assertions": graded,
            "response_preview": response_text[:200],
        }


# ─── CLI ────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SkillSentry 单用例快速验证（30s 内出结果）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python sentry_quick_check.py --skill SKILL.md --prompt "报销这张发票" --assert "existence:单据状态" --assert "semantic:询问金额"
  python sentry_quick_check.py --skill SKILL.md --evals evals.json --case-id eval-1
  python sentry_quick_check.py --skill SKILL.md --prompt "你好" --assert "semantic:礼貌回应" --model haiku
""",
    )
    parser.add_argument("--skill", required=True, help="被测 SKILL.md 路径")

    # 方式一：直接传 prompt + 断言
    parser.add_argument("--prompt", help="用户输入文本")
    parser.add_argument(
        "--assert", dest="assertions", action="append", default=[],
        metavar="TYPE:EXPECTED",
        help="断言（可多次指定），格式：exact_match:文本 / existence:关键词 / semantic:描述",
    )
    parser.add_argument("--case-name", default="quick-check", help="用例名称（显示用）")

    # 方式二：从 evals.json 取某个用例
    parser.add_argument("--evals", help="evals.json 路径")
    parser.add_argument("--case-id", help="evals.json 中的 eval id，例如 eval-1")

    # 模型
    parser.add_argument("--model", "--model-exec", dest="model_exec", default="sonnet",
                        help="executor 模型（默认 sonnet；可改 haiku 更快）")
    parser.add_argument("--model-grade", default="claude-sonnet-4-6",
                        help="grader 模型（默认 claude-sonnet-4-6）")
    parser.add_argument("--timeout", type=int, default=120, help="executor 超时（秒）")
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_path = Path(args.skill)
    if not skill_path.exists():
        print(f"❌ SKILL.md 不存在: {skill_path}", file=sys.stderr)
        return 1

    # 确定用例来源
    if args.evals and args.case_id:
        # 从 evals.json 读取
        evals_path = Path(args.evals)
        if not evals_path.exists():
            print(f"❌ evals.json 不存在: {evals_path}", file=sys.stderr)
            return 1
        evals = json.loads(evals_path.read_text(encoding="utf-8-sig"))
        case = next((e for e in evals if e.get("id") == args.case_id), None)
        if case is None:
            ids = [e.get("id") for e in evals]
            print(f"❌ 找不到 case-id={args.case_id}，可用: {ids}", file=sys.stderr)
            return 1
        prompt_text = case.get("prompt", "")
        assertions = case.get("assertions", [])
        # 补 name 字段
        for i, a in enumerate(assertions):
            a.setdefault("name", f"A{i+1}")
        case_name = case.get("name", args.case_id)
    elif args.prompt:
        prompt_text = args.prompt
        assertions = [parse_assertion_str(s, i) for i, s in enumerate(args.assertions)]
        case_name = args.case_name
    else:
        print("❌ 必须指定 --prompt 或 (--evals + --case-id)", file=sys.stderr)
        return 1

    if not assertions:
        print(_color("⚠️  未指定断言，只执行用例并打印响应（不评审）", "\033[93m"))

    result = quick_check(
        skill_path=skill_path,
        prompt_text=prompt_text,
        assertions=assertions,
        case_name=case_name,
        model_exec=args.model_exec,
        model_grade=args.model_grade,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    return 0 if result.get("status") in ("PASS", "EXEC_FAILED") or not assertions else (
        0 if result.get("status") == "PASS" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
