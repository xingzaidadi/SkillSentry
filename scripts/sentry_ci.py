#!/usr/bin/env python3
"""
SkillSentry CI 编排入口
确定性 pipeline 执行，适用于 GitHub Actions 和本地 CI。

用法：
  python sentry_ci.py --skill <name|path> [--mode smoke|quick|regression] \
    [--threshold 0.8] [--output-dir ./results] [--model claude-sonnet-4-6] [--timeout 1800]

退出码：0=PASS, 1=FAIL, 2=ERROR

架构：
  static/cases/grader-report → Anthropic SDK 直调（纯文本推理）
  executor-with → claude CLI subprocess（需要 tool use）
  pipeline/state/gate → 复用 Tool-as-Code 确定性内核
"""

import argparse
import hashlib
import html
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

import sentry_state
import sentry_preflight
from sentry_diagnostics import collect_diagnostics, render_html_section, render_markdown
from sentry_gate import build_gate
from sentry_pipeline import PIPELINES, pipeline_for_mode, step_definition


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
        choices=sorted(PIPELINES),
        default="smoke",
        help="测评模式（默认 smoke）",
    )
    parser.add_argument("--threshold", type=float, default=0.8, help="通过率阈值（默认 0.80）")
    parser.add_argument("--output-dir", default="./ci-eval-results", help="结果输出目录")
    parser.add_argument("--cases", default=None, help="指定 evals.json 路径（regression 模式必需）")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="LLM model（SDK 调用用）")
    parser.add_argument("--executor-model", default=None, help="executor 使用的 claude CLI model（默认同 --model）")
    parser.add_argument("--timeout", type=int, default=1800, help="总超时秒数（默认 30 分钟）")
    parser.add_argument("--runtime", choices=["auto", "cli", "openclaw"], default="auto", help="运行环境预检模式")
    parser.add_argument("--config", default=str(sentry_preflight.DEFAULT_CONFIG), help="飞书/同步配置 JSON 路径")
    parser.add_argument(
        "--timeout-per-eval",
        type=int,
        default=int(os.environ.get("SKILLSENTRY_CI_TIMEOUT_PER_EVAL", "120")),
        help="executor 单个 eval 超时秒数（默认 120，可用 SKILLSENTRY_CI_TIMEOUT_PER_EVAL 覆盖）",
    )
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


def run_preflight(args) -> tuple[int, dict]:
    preflight_args = argparse.Namespace(
        skill=args.skill,
        mode=args.mode,
        runtime=args.runtime,
        config=args.config,
        format="json",
    )
    return sentry_preflight.build_result(preflight_args)


def init_session(skill_name: str, skill_hash: str, skill_type: str, mode: str, preflight: dict | None = None) -> Path:
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
        "preflight": preflight or {},
        "mcp_backend": "unavailable",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_step": "init",
        "pipeline": pipeline_for_mode(mode),
        "completed_steps": [],
        "milestones": {},
        "sync": {"pull": None, "push_cases": None, "push_results": None, "push_run": None},
        "ci": True,
    }

    sentry_state.save_session(session_dir, session_data)

    return session_dir


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


def inspect_case_feasibility(cases: list) -> list[dict]:
    """Return deterministic warnings for generated cases that cannot run as-is."""
    warnings = []
    path_pattern = re.compile(r"[A-Za-z]:\\[^\s，。；,;`\"']+")

    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id", "unknown")
        prompt = case.get("prompt", "") or ""
        for raw_path in path_pattern.findall(prompt):
            normalized = raw_path.rstrip(".,;，。；)")
            if not Path(normalized).exists():
                warnings.append({
                    "case_id": case_id,
                    "type": "missing_local_path",
                    "path": normalized,
                    "message": "Generated case references a local path that does not exist in this environment.",
                })
    return warnings


def record_case_feasibility(session_dir: Path, cases: list) -> None:
    warnings = inspect_case_feasibility(cases)
    if warnings:
        log(f"  ⚠️ case feasibility warnings: {len(warnings)}")
        for item in warnings:
            log(f"    - {item['case_id']}: missing path {item['path']}", verbose_only=True)
    merge_session(session_dir, {"case_warnings": warnings})


def prepare_existing_cases(session_dir: Path, existing_cases: Path | None) -> bool:
    """Copy reusable evals.json into a session before modes without a cases step."""
    if not existing_cases:
        return True
    existing_cases = Path(existing_cases).expanduser()
    if not existing_cases.exists():
        log(f"  ❌ 指定用例不存在: {existing_cases}")
        return False

    import shutil

    shutil.copy2(existing_cases, session_dir / "evals.json")
    log(f"  ⚡ 预置已有用例: {existing_cases}")
    try:
        cases = json.loads((session_dir / "evals.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log(f"  ❌ 用例 JSON 解析失败: {exc}")
        return False

    total = len(cases) if isinstance(cases, list) else 0
    record_case_feasibility(session_dir, cases)
    merge_session(session_dir, {"cases": {"total": total, "types": {}, "reused": True}})
    return True


def merge_session(session_dir: Path, data: dict):
    """Merge step data into session.json without advancing last_step."""
    session = sentry_state.load_session(session_dir)
    session.update(data)
    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    sentry_state.save_session(session_dir, session)


def transition_session(session_dir: Path, step: str):
    """Advance session through sentry_state transition rules."""
    args = argparse.Namespace(session_dir=str(session_dir), step=step, allow_skip=False)
    result = sentry_state.transition(args)
    if result.get("status") != "OK":
        raise RuntimeError(f"illegal pipeline transition: {result}")


def run_step(step: str, session_dir: Path, skill_path: Path, args, **kwargs) -> bool:
    """执行单个 pipeline 步骤，返回 True=成功"""
    definition = step_definition(step)
    log(f"🔧 执行: {step} ({definition.tool})")
    start = time.time()

    try:
        if step == "static":
            success = run_static(session_dir, skill_path, args)
        elif step == "cases":
            success = run_cases(session_dir, skill_path, args, **kwargs)
        elif step == "sync-pull":
            success = run_sync_step(session_dir, "pull", config=getattr(args, "config", None))
        elif step == "sync-push-cases":
            success = run_sync_step(session_dir, "push_cases", config=getattr(args, "config", None))
        elif step == "sync-push-results":
            success = run_sync_step(session_dir, "push_results", config=getattr(args, "config", None))
        elif step == "executor-with":
            success = run_executor_with(session_dir, skill_path, args)
        elif step == "executor-without":
            success = run_executor_without(session_dir, skill_path, args)
        elif step == "comparator":
            success = run_comparator(session_dir)
        elif step == "analyzer":
            success = run_analyzer(session_dir)
        elif step == "grader-report":
            success = run_grader_report(session_dir, skill_path, args)
        elif step == "gate":
            success = run_gate(session_dir)
        elif step == "publish":
            success = run_publish(session_dir)
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


def run_static(session_dir: Path, skill_path: Path, args) -> bool:
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
            merge_session(session_dir, {
                "lint": check_data.get("lint", {}),
                "trigger": check_data.get("trigger", {}),
            })

            # 检查 P0
            p0_count = check_data.get("lint", {}).get("P0", 0)
            if p0_count > 0:
                log(f"  ⚠️ 发现 {p0_count} 个 P0 问题")
            return True
    except json.JSONDecodeError:
        log("  ⚠️ static 结果 JSON 解析失败，继续")

    return True  # check 不阻断 pipeline


def run_cases(session_dir: Path, skill_path: Path, args, existing_cases: Path = None) -> bool:
    """生成测试用例 — 用 SDK"""
    from ci_grader import call_llm

    # 如果有现成 cases，直接复用
    if existing_cases and existing_cases.exists():
        import shutil
        shutil.copy2(existing_cases, session_dir / "evals.json")
        log(f"  ⚡ 复用已有用例: {existing_cases}")
        try:
            cases = json.loads((session_dir / "evals.json").read_text(encoding="utf-8"))
            total = len(cases) if isinstance(cases, list) else 0
            record_case_feasibility(session_dir, cases)
        except json.JSONDecodeError:
            total = 0
        merge_session(session_dir, {"cases": {"total": total, "types": {}, "reused": True}})
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

Additional hard constraints for generated cases:
- Cases must be executable in a fresh CI session directory.
- Do not invent absolute local file paths such as C:\\Users\\... unless the case is explicitly testing missing-file handling and the assertions expect a graceful missing-file response.
- Smoke mode cases should be bounded enough to finish under the executor timeout. Avoid requiring a full real project compile unless the prompt provides an accessible target project.
- Assertions must match the material actually provided in the prompt. Do not expect Word extraction, screenshot OCR, project reads, or Maven compile when no accessible file/project exists.
- Prefer one small happy path, one routing/negative case, and one incomplete-input case over multiple heavy end-to-end code-generation cases.

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
            record_case_feasibility(session_dir, cases)
            merge_session(session_dir, {
                "cases": {"total": len(cases), "types": {}}
            })
            return True
    except json.JSONDecodeError as e:
        log(f"  ❌ 用例 JSON 解析失败: {e}")

    return False


def run_sync_step(session_dir: Path, sync_key: str, config: str | None = None) -> bool:
    """Run the stable sync wrapper; skipped_no_config is a valid CI outcome."""
    from sentry_sync import execute_sync_step

    step_by_key = {
        "pull": "sync-pull",
        "push_cases": "sync-push-cases",
        "push_results": "sync-push-results",
    }
    payload = execute_sync_step(step_by_key[sync_key], session_dir=session_dir, config=config)
    log(f"  ⏭️ sync.{sync_key}: {payload['status']}")
    return payload["status"] != "ERROR"


def run_executor_with(session_dir: Path, skill_path: Path, args) -> bool:
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
        timeout_per_eval=args.timeout_per_eval,
        verbose=args.verbose,
        variant="with_skill",
    )

    summary_file = session_dir / "executor_results.json"
    summary = {}
    if summary_file.exists():
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    merge_session(session_dir, {
        "executor": {
            "with_skill": summary,
            "success": summary.get("success", 0),
            "total": summary.get("total", 0),
        }
    })
    return success


def run_executor_without(session_dir: Path, skill_path: Path, args) -> bool:
    """Run no-skill baseline when safe; otherwise record explicit partial."""
    session = sentry_state.load_session(session_dir)
    if session.get("skill_type") == "mcp_based":
        merge_session(session_dir, {
            "without_skill": {
                "status": "partial",
                "reason": "mcp_based baseline is not executed in CI until MCP sandbox parity is available",
            }
        })
        log("  ⏭️ executor-without: partial (mcp_based baseline not executed in CI)")
        return True

    from ci_executor import execute_all_evals

    evals_file = session_dir / "evals.json"
    if not evals_file.exists():
        log("  ❌ evals.json 不存在，无法执行 without_skill")
        return False

    model = args.executor_model or args.model
    success = execute_all_evals(
        evals_file=evals_file,
        skill_path=skill_path,
        session_dir=session_dir,
        model=model,
        timeout_per_eval=args.timeout_per_eval,
        verbose=args.verbose,
        variant="without_skill",
    )

    summary_file = session_dir / "executor_without_skill_results.json"
    summary = {}
    if summary_file.exists():
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
    merge_session(session_dir, {
        "without_skill": {
            "status": "completed" if success else "failed",
            "summary": summary,
        }
    })
    return success


def run_comparator(session_dir: Path) -> bool:
    eval_items = []
    missing_without = []
    missing_with = []

    for eval_dir in sorted(p for p in session_dir.glob("eval-*") if p.is_dir()):
        with_response = eval_dir / "with_skill" / "outputs" / "response.md"
        without_response = eval_dir / "without_skill" / "outputs" / "response.md"
        if not with_response.exists():
            missing_with.append(eval_dir.name)
            continue
        if not without_response.exists():
            missing_without.append(eval_dir.name)
            continue
        with_text = with_response.read_text(encoding="utf-8", errors="replace")
        without_text = without_response.read_text(encoding="utf-8", errors="replace")
        eval_items.append({
            "eval_id": eval_dir.name,
            "status": "available",
            "with_skill_response_chars": len(with_text),
            "without_skill_response_chars": len(without_text),
            "note": "CI comparator only verifies paired outputs. Quality comparison remains an LLM comparator responsibility.",
        })

    if eval_items:
        status = "partial" if missing_with or missing_without else "computed_structural"
        payload = {
            "status": status,
            "comparable_evals": len(eval_items),
            "missing_with_skill": missing_with,
            "missing_without_skill": missing_without,
            "items": eval_items,
        }
    else:
        payload = {
            "status": "N/A",
            "reason": "without_skill baseline unavailable in CI",
            "missing_with_skill": missing_with,
            "missing_without_skill": missing_without,
        }
    (session_dir / "comparator-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    merge_session(session_dir, {"comparator": payload})
    log(f"  📊 comparator: {payload['status']}")
    return True


def run_analyzer(session_dir: Path) -> bool:
    payload = {
        "status": "N/A",
        "reason": "comparator result unavailable in CI",
    }
    (session_dir / "analyzer-recommendations.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    merge_session(session_dir, {"analyzer": payload})
    log("  ⏭️ analyzer: N/A")
    return True


def run_grader_report(session_dir: Path, skill_path: Path, args) -> bool:
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

    merge_session(session_dir, {"grader_report": {"status": "completed" if success else "failed"}})
    if success:
        gate_preview = build_gate(session_dir)
        summary_payload = {
            "status": "generated_by_ci",
            "note": "CI compatibility summary. Per-eval grading.json files remain the source for deterministic gate counts.",
            "authoritative_pass_rate": gate_preview.get("authoritative_pass_rate"),
            "grade": gate_preview.get("grade"),
            "verdict": gate_preview.get("verdict"),
            "sources": gate_preview.get("sources", []),
        }
        (session_dir / "grading-summary.json").write_text(
            json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_minimal_report(session_dir, gate_preview)
    return success


def write_minimal_report(session_dir: Path, gate_result: dict) -> None:
    rate = gate_result.get("authoritative_pass_rate")
    rate_text = "N/A" if rate is None else f"{rate:.1%}"
    diagnostics = collect_diagnostics(session_dir, gate_result)
    diagnostics_html = render_html_section(diagnostics)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>SkillSentry CI Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; line-height: 1.5; }}
    code {{ background: #f4f4f4; padding: 2px 4px; }}
    table {{ border-collapse: collapse; margin: 12px 0 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
    th {{ background: #f7f7f7; }}
  </style>
</head>
<body>
  <h1>SkillSentry CI Report</h1>
  <p><strong>Verdict:</strong> {gate_result.get("verdict", "UNKNOWN")}</p>
  <p><strong>Grade:</strong> {gate_result.get("grade", "N/A")}</p>
  <p><strong>Authoritative pass rate:</strong> {rate_text}</p>
  <p><strong>Delta:</strong> {gate_result.get("delta", {}).get("status", "N/A")}</p>
{diagnostics_html}
  <p>Generated by <code>sentry_ci.py</code>. Full interactive reports are produced by <code>sentry-grader</code>.</p>
</body>
</html>
"""
    (session_dir / "report.html").write_text(html, encoding="utf-8")


def write_ci_html_report(report_path: Path, results: dict, args, *, generated_by: str = "sentry_ci.py") -> None:
    """Write a deterministic HTML report for every CI outcome, including ERROR paths."""
    summary = results.get("summary", {})
    diagnostics = results.get("diagnostics", {})
    rate = summary.get("authoritative_pass_rate")
    rate_text = "N/A" if rate is None else f"{rate:.1%}"
    reasons = "".join(f"<li>{html.escape(str(reason))}</li>" for reason in results.get("reasons", []))
    if not reasons:
        reasons = "<li>none</li>"
    diagnostics_html = render_html_section(diagnostics)
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>SkillSentry CI Result</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; line-height: 1.5; }}
    code {{ background: #f4f4f4; padding: 2px 4px; }}
    table {{ border-collapse: collapse; margin: 12px 0 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
    th {{ background: #f7f7f7; }}
  </style>
</head>
<body>
  <h1>SkillSentry CI Result</h1>
  <p><strong>Skill:</strong> {html.escape(str(args.skill))}</p>
  <p><strong>Mode:</strong> {html.escape(str(args.mode))}</p>
  <p><strong>Verdict:</strong> {html.escape(str(results.get("verdict", "UNKNOWN")))}</p>
  <p><strong>Grade:</strong> {html.escape(str(summary.get("grade", "N/A")))}</p>
  <p><strong>Authoritative pass rate:</strong> {rate_text}</p>
  <h2>Reasons</h2>
  <ul>{reasons}</ul>
{diagnostics_html}
  <p>Generated by <code>{html.escape(generated_by)}</code>.</p>
</body>
</html>
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html_text, encoding="utf-8")


def ensure_ci_report_artifacts(output_dir: Path, results: dict, args, session_dir: Path | None = None) -> dict:
    """Ensure CI always exposes an HTML report artifact."""
    output_report = output_dir / "report.html"
    write_ci_html_report(output_report, results, args)
    artifacts = {"output_report_html": str(output_report)}

    if session_dir is not None:
        session_report = session_dir / "report.html"
        if not session_report.exists() or results.get("verdict") == "ERROR":
            write_ci_html_report(session_report, results, args)
        artifacts["session_report_html"] = str(session_report)

    return artifacts


def release_status_for_verdict(verdict: str | None) -> str:
    """Map gate verdicts to stable downstream CI status labels."""
    normalized = str(verdict or "").strip().upper()
    if normalized == "PASS":
        return "pass"
    if normalized == "CONDITIONAL PASS":
        return "conditional"
    if normalized == "FAIL":
        return "fail"
    return "error"


def exit_code_for_verdict(verdict: str | None) -> int:
    """Return the stable sentry_ci.py process exit code for a verdict."""
    status = release_status_for_verdict(verdict)
    if status == "pass":
        return 0
    if status in {"conditional", "fail"}:
        return 1
    return 2


def single_line(value) -> str:
    return str(value).replace("\r", " ").replace("\n", " ")


def github_output_fields(results: dict, artifacts: dict) -> dict[str, str]:
    summary = results.get("summary", {})
    diagnostics = results.get("diagnostics", {})
    categories = diagnostics.get("categories", []) if isinstance(diagnostics, dict) else []
    rate = summary.get("authoritative_pass_rate") if isinstance(summary, dict) else None
    verdict = results.get("verdict", "ERROR")
    exit_code = exit_code_for_verdict(verdict)
    release_status = release_status_for_verdict(verdict)
    return {
        "verdict": single_line(verdict),
        "status": release_status,
        "release_status": release_status,
        "exit_code": str(exit_code),
        "report_html": single_line(artifacts.get("output_report_html", "")),
        "session_report_html": single_line(artifacts.get("session_report_html", "")),
        "diagnostic_categories": single_line(",".join(str(item) for item in categories)),
        "authoritative_pass_rate": f"{rate:.4f}" if rate is not None else "N/A",
        "grade": single_line(summary.get("grade", "N/A") if isinstance(summary, dict) else "N/A"),
    }


def run_gate(session_dir: Path) -> bool:
    result = build_gate(session_dir)
    (session_dir / "gate-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    merge_session(session_dir, {
        "verdict": {
            "status": result.get("verdict"),
            "grade": result.get("grade"),
            "authoritative_pass_rate": result.get("authoritative_pass_rate"),
            "delta": result.get("delta"),
            "ifr": result.get("ifr"),
            "vetoes": result.get("vetoes", []),
            "reasons": result.get("decision_reasons", []),
        }
    })
    return True


def run_publish(session_dir: Path) -> bool:
    from sentry_publish import execute_publish

    payload = execute_publish(session_dir)
    log(f"  📣 publish: {payload['status']}")
    return payload["status"] != "ERROR"


def collect_results(session_dir: Path, args) -> dict:
    """Collect deterministic gate output."""
    gate_file = session_dir / "gate-result.json"
    if gate_file.exists():
        gate = json.loads(gate_file.read_text(encoding="utf-8"))
    else:
        gate = build_gate(session_dir)
        gate_file.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "authoritative_pass_rate": gate.get("authoritative_pass_rate"),
        "grade": gate.get("grade"),
        "delta": gate.get("delta"),
        "ifr": gate.get("ifr"),
        "vetoes": gate.get("vetoes", []),
    }
    diagnostics = collect_diagnostics(session_dir, gate)
    return {
        "verdict": gate.get("verdict", "ERROR"),
        "reasons": gate.get("decision_reasons", []),
        "summary": summary,
        "gate": gate,
        "diagnostics": diagnostics,
    }


def write_ci_output(output_dir: Path, results: dict, args, session_dir: Path | None = None):
    """写入 CI 输出文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = ensure_ci_report_artifacts(output_dir, results, args, session_dir=session_dir)
    exit_code = exit_code_for_verdict(results.get("verdict"))
    release_status = release_status_for_verdict(results.get("verdict"))

    output = {
        "skill": args.skill,
        "mode": args.mode,
        "threshold": args.threshold,
        "verdict": results["verdict"],
        "status": release_status,
        "exit_code": exit_code,
        "reasons": results["reasons"],
        "summary": results["summary"],
        "diagnostics": results.get("diagnostics", {}),
        "artifacts": artifacts,
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
| Status | `{release_status}` |
| Exit Code | `{exit_code}` |
| Report | `{artifacts['output_report_html']}` |
"""
    s = results.get("summary", {})
    if s.get("authoritative_pass_rate") is not None:
        summary_md += f"| Authoritative Pass Rate | {s['authoritative_pass_rate']:.1%} |\n"
    if s.get("grade"):
        summary_md += f"| Grade | {s['grade']} |\n"

    if results["reasons"]:
        summary_md += "\n### Reasons\n"
        for r in results["reasons"]:
            summary_md += f"- {r}\n"

    summary_md += "\n" + render_markdown(results.get("diagnostics", {}))

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
                for key, value in github_output_fields(results, artifacts).items():
                    f.write(f"{key}={value}\n")


def main():
    args = parse_args()
    log._verbose = args.verbose

    log(f"SkillSentry CI current-contract — mode={args.mode}, threshold={args.threshold:.0%}")

    # 1. 预检并定位 Skill
    preflight_code, preflight = run_preflight(args)
    if preflight_code != 0:
        log(f"❌ preflight 失败: {preflight.get('error', 'unknown')}")
        results = {
            "verdict": "ERROR",
            "reasons": [f"Preflight failed: {preflight.get('error', 'unknown')}"],
            "summary": {},
            "diagnostics": {
                "preflight": preflight,
                "categories": ["preflight_error"],
                "notes": [f"Preflight failed before session creation: {preflight.get('error', 'unknown')}."],
            },
        }
        write_ci_output(Path(args.output_dir), results, args)
        sys.exit(2)
    skill_path = Path(preflight["skill_path"])
    log(f"📂 Skill: {skill_path}")

    skill_name = preflight.get("skill_dir_name") or skill_path.parent.name
    skill_content = skill_path.read_text(encoding="utf-8")

    # 2. 使用 preflight 的确定性识别结果
    skill_type = preflight["skill_type"]
    skill_hash = preflight["skill_hash"]
    log(f"📋 Type: {skill_type} | Hash: {skill_hash[:8]}")
    tools = preflight.get("runtime_tools", {})
    claude_cli = tools.get("claude_cli", {}) if isinstance(tools, dict) else {}
    if claude_cli.get("available") is False:
        log("  ⚠️ preflight: claude CLI not found; real executor steps will fail unless the environment is fixed")

    # 3. 初始化 session
    session_dir = init_session(skill_name, skill_hash, skill_type, args.mode, preflight)
    log(f"📁 Session: {session_dir}")

    # 4. 确定 pipeline
    pipeline = pipeline_for_mode(args.mode)
    log(f"🔗 Pipeline: {' → '.join(pipeline)}")

    # 5. 查找已有 cases（regression 模式或缓存命中）
    existing_cases = None
    if args.cases:
        existing_cases = Path(args.cases)
    elif args.mode == "regression":
        existing_cases = find_existing_cases(skill_name)
        if not existing_cases:
            log("❌ regression 模式需要已有 cases，但未找到缓存")
            sys.exit(2)

    if existing_cases and "cases" not in pipeline:
        if not prepare_existing_cases(session_dir, existing_cases):
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
                if step in ("cases", "executor-with", "grader-report"):
                    log(f"  ⛔ {step} 失败，后续步骤无法执行，终止 pipeline")
                    break
        else:
            try:
                transition_session(session_dir, step)
            except RuntimeError as exc:
                log(f"  ❌ 状态流转失败: {exc}")
                failed_steps.append(f"{step}(transition)")
                break

    total_time = time.time() - start_time
    log(f"⏱️ Pipeline 完成 ({total_time:.1f}s)")

    # 7. 收集结果
    if not failed_steps:
        results = collect_results(session_dir, args)
    else:
        results = {
            "verdict": "ERROR",
            "reasons": [f"Pipeline 步骤失败: {', '.join(failed_steps)}"],
            "summary": {},
            "diagnostics": collect_diagnostics(session_dir),
        }

    # 8. 输出
    output_dir = Path(args.output_dir)
    write_ci_output(output_dir, results, args, session_dir=session_dir)

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
    sys.exit(exit_code_for_verdict(verdict))


if __name__ == "__main__":
    main()
