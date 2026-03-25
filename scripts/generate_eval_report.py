#!/usr/bin/env python3
"""
generate_eval_report.py

聚合 skill-eval-master 的测评结果，生成 Markdown 格式的完整测评报告。

用法：
  python generate_eval_report.py <workspace_dir> --skill-name <name> [--risk-level S|A|B|C] [--output <path>]

示例：
  python generate_eval_report.py em-reimbursement-workspace/iteration-1 \
    --skill-name em-reimbursement-2.0 \
    --risk-level A \
    --output em-reimbursement-workspace/eval-report.md
"""

import json
import os
import sys
import argparse
import glob
from datetime import datetime
from pathlib import Path

# 准入指标阈值
ADMISSION_CRITERIA = {
    "S": {
        "pass_rate": 0.95, "trigger_rate": 0.95, "ifr": 1.00,
        "consistency": 0.95, "stddev": 0.05, "coverage": 0.95,
        "hallucination_max": 0, "p95_time": 15, "delta_min": 0.0,
        "disaster_required": True, "security_required": True,
    },
    "A": {
        "pass_rate": 0.90, "trigger_rate": 0.90, "ifr": 0.95,
        "consistency": 0.90, "stddev": 0.10, "coverage": 0.85,
        "hallucination_max": 1, "p95_time": 15, "delta_min": 0.0,
        "disaster_required": True, "security_required": True,
    },
    "B": {
        "pass_rate": 0.80, "trigger_rate": 0.85, "ifr": 0.90,
        "consistency": 0.80, "stddev": 0.20, "coverage": 0.70,
        "hallucination_max": 2, "p95_time": 30, "delta_min": -0.05,
        "disaster_required": False, "security_required": False,
    },
    "C": {
        "pass_rate": 0.70, "trigger_rate": 0.80, "ifr": 0.80,
        "consistency": None, "stddev": 0.30, "coverage": 0.50,
        "hallucination_max": None, "p95_time": 30, "delta_min": None,
        "disaster_required": False, "security_required": False,
    },
}

RISK_LABELS = {"S": "S级（关键）", "A": "A级（重要）", "B": "B级（一般）", "C": "C级（辅助）"}


def load_json(path):
    """Load a JSON file, return None if not found."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def collect_gradings(workspace_dir):
    """Collect all grading.json files from the workspace.
    When duplicate eval IDs exist (e.g. eval-1 and eval-1-daily-taxi),
    prefer the directory with the longer (more descriptive) name."""
    results = {"with_skill": [], "without_skill": [], "disaster": []}

    # Deduplicate by eval ID, preferring longer directory names
    by_id = {}
    for eval_dir in glob.glob(os.path.join(workspace_dir, "eval-*")):
        name = os.path.basename(eval_dir)
        parts = name.split("-")
        try:
            eid = int(parts[1])
        except (IndexError, ValueError):
            continue
        # Prefer dir WITH metadata over dir without; then prefer longer name
        has_meta = os.path.exists(os.path.join(eval_dir, "eval_metadata.json"))
        if eid not in by_id:
            by_id[eid] = (eval_dir, has_meta)
        else:
            prev_dir, prev_meta = by_id[eid]
            if has_meta and not prev_meta:
                by_id[eid] = (eval_dir, has_meta)
            elif has_meta == prev_meta and len(name) > len(os.path.basename(prev_dir)):
                by_id[eid] = (eval_dir, has_meta)

    for eid, (eval_dir, _) in sorted(by_id.items()):
        eval_name = os.path.basename(eval_dir)
        metadata = load_json(os.path.join(eval_dir, "eval_metadata.json"))

        for config in ["with_skill", "without_skill"]:
            grading_path = os.path.join(eval_dir, config, "grading.json")
            grading = load_json(grading_path)
            if grading:
                # Prefer display_name (Chinese) > eval_name > dir name
                display = (metadata.get("display_name") or
                           metadata.get("eval_name") or
                           eval_name) if metadata else eval_name
                grading["_eval_name"] = display
                grading["_eval_id"] = metadata.get("eval_id", eval_name) if metadata else eval_name
                results[config].append(grading)
    
    # Collect disaster scenario results
    disaster_dir = os.path.join(workspace_dir, "disaster-scenarios")
    if os.path.exists(disaster_dir):
        for scenario_dir in sorted(glob.glob(os.path.join(disaster_dir, "*"))):
            if os.path.isdir(scenario_dir):
                grading = load_json(os.path.join(scenario_dir, "grading.json"))
                if grading:
                    grading["_scenario_name"] = os.path.basename(scenario_dir)
                    results["disaster"].append(grading)
    
    return results


def calculate_metrics(gradings):
    """Calculate aggregate metrics from a list of grading results."""
    if not gradings:
        return {"pass_rate": 0, "total_passed": 0, "total_failed": 0, "total": 0}
    
    total_passed = sum(g.get("summary", {}).get("passed", 0) for g in gradings)
    total_failed = sum(g.get("summary", {}).get("failed", 0) for g in gradings)
    total = total_passed + total_failed
    pass_rate = total_passed / total if total > 0 else 0
    
    # Calculate per-eval pass rates for stddev
    per_eval_rates = []
    for g in gradings:
        s = g.get("summary", {})
        t = s.get("total", 0)
        if t > 0:
            per_eval_rates.append(s.get("passed", 0) / t)
    
    stddev = 0
    if len(per_eval_rates) > 1:
        mean = sum(per_eval_rates) / len(per_eval_rates)
        variance = sum((r - mean) ** 2 for r in per_eval_rates) / len(per_eval_rates)
        stddev = variance ** 0.5
    
    return {
        "pass_rate": pass_rate,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total": total,
        "stddev": round(stddev, 4),
        "per_eval_rates": per_eval_rates,
    }


def check_admission(metrics, risk_level, disaster_results):
    """Check metrics against admission criteria."""
    criteria = ADMISSION_CRITERIA.get(risk_level, ADMISSION_CRITERIA["B"])
    checks = []
    all_pass = True
    
    # Pass rate
    target = criteria["pass_rate"]
    actual = metrics["with_skill"]["pass_rate"]
    met = actual >= target
    if not met:
        all_pass = False
    checks.append(("通过率", f">= {target*100:.0f}%", f"{actual*100:.1f}%", met))
    
    # Stddev
    target_std = criteria["stddev"]
    actual_std = metrics["with_skill"]["stddev"]
    met = actual_std <= target_std
    if not met:
        all_pass = False
    checks.append(("稳定性 (Stddev)", f"< {target_std}", f"{actual_std:.4f}", met))
    
    # Delta
    delta = metrics["with_skill"]["pass_rate"] - metrics["without_skill"]["pass_rate"]
    delta_min = criteria["delta_min"]
    if delta_min is not None:
        met = delta >= delta_min
        if not met:
            all_pass = False
        checks.append(("增益 (Δ)", f">= {delta_min*100:.0f}%", f"{delta*100:+.1f}%", met))
    else:
        checks.append(("增益 (Δ)", "不硬性要求", f"{delta*100:+.1f}%", True))
    
    # Disaster scenarios
    if criteria["disaster_required"]:
        disaster_pass = all(
            g.get("summary", {}).get("pass_rate", 0) == 1.0
            for g in disaster_results
        ) if disaster_results else False
        if not disaster_pass and disaster_results:
            all_pass = False
        checks.append(("灾难场景", "全部通过", 
                       f"{sum(1 for g in disaster_results if g.get('summary',{}).get('pass_rate',0)==1.0)}/{len(disaster_results)} 通过" if disaster_results else "未执行",
                       disaster_pass))
    
    # Decision
    if all_pass:
        decision = "PASS"
    elif metrics["with_skill"]["pass_rate"] >= criteria["pass_rate"] - 0.05:
        decision = "CONDITIONAL PASS"
    else:
        decision = "FAIL"
    
    return decision, checks


def find_negative_deltas(with_gradings, without_gradings):
    """Find test cases where with_skill performed worse than without_skill."""
    negatives = []
    for ws, wos in zip(with_gradings, without_gradings):
        ws_rate = ws.get("summary", {}).get("pass_rate", 0)
        wos_rate = wos.get("summary", {}).get("pass_rate", 0)
        delta = ws_rate - wos_rate
        if delta < 0:
            negatives.append({
                "eval_name": ws.get("_eval_name", "unknown"),
                "with_skill_rate": ws_rate,
                "without_skill_rate": wos_rate,
                "delta": delta,
            })
    return negatives


def generate_report(workspace_dir, skill_name, risk_level, output_path=None):
    """Generate the full evaluation report."""
    # Load data
    gradings = collect_gradings(workspace_dir)
    benchmark = load_json(os.path.join(workspace_dir, "benchmark.json"))
    env_config = load_json(os.path.join(workspace_dir, "eval_environment.json"))
    
    # Calculate metrics
    metrics = {
        "with_skill": calculate_metrics(gradings["with_skill"]),
        "without_skill": calculate_metrics(gradings["without_skill"]),
    }
    
    # Admission check
    decision, checks = check_admission(metrics, risk_level, gradings["disaster"])
    
    # Negative deltas
    neg_deltas = find_negative_deltas(gradings["with_skill"], gradings["without_skill"])
    
    # Build report
    report_lines = []
    r = report_lines.append
    
    r(f"# {skill_name} 测评报告\n")
    
    # Section 1: Basic Info
    r("## 一、基本信息\n")
    r("| 项目 | 内容 |")
    r("|------|------|")
    r(f"| 被测 Skill | {skill_name} |")
    r(f"| 测评日期 | {datetime.now().strftime('%Y-%m-%d')} |")
    r(f"| 风险等级 | {RISK_LABELS.get(risk_level, risk_level)} |")
    r(f"| 目标通过率 | >= {ADMISSION_CRITERIA[risk_level]['pass_rate']*100:.0f}% |")
    if env_config:
        env = env_config.get("eval_environment", env_config)
        r(f"| 模型版本 | {env.get('model', 'N/A')} |")
        r(f"| Temperature | {env.get('temperature', 'N/A')} |")
        r(f"| Skill 版本 | {env.get('skill_version', 'N/A')} |")
    r("")
    
    # Section 2: Executive Summary
    r("## 二、执行摘要\n")
    ws_rate = metrics["with_skill"]["pass_rate"]
    wos_rate = metrics["without_skill"]["pass_rate"]
    delta = ws_rate - wos_rate
    target = ADMISSION_CRITERIA[risk_level]["pass_rate"]
    
    if decision == "PASS":
        r(f"> **{skill_name}** 测评结果为 **PASS**，可以发布。")
        r(f"> with_skill 通过率 {ws_rate*100:.1f}%，达到 {RISK_LABELS[risk_level]} 准入标准（>= {target*100:.0f}%）。")
        r(f"> 相比无 Skill 基线提升 {delta*100:+.1f}%，Skill 增益有效。")
    elif decision == "CONDITIONAL PASS":
        r(f"> **{skill_name}** 测评结果为 **CONDITIONAL PASS**，有条件发布。")
        r(f"> with_skill 通过率 {ws_rate*100:.1f}%，接近但未完全达到 {target*100:.0f}% 的准入标准。")
        r(f"> 建议在发布后持续关注，并在约定时间内迭代修复已知问题。")
    else:
        r(f"> **{skill_name}** 测评结果为 **FAIL**，不建议发布。")
        r(f"> with_skill 通过率 {ws_rate*100:.1f}%，未达到 {target*100:.0f}% 的准入标准。")
        if neg_deltas:
            r(f"> 存在 {len(neg_deltas)} 个负向增益用例，需要优先修复。")
    r("")
    
    # Section 3: Decision
    r("## 三、发布决策\n")
    r(f"### 决策结果：{decision}\n")
    r("### 指标达成一览\n")
    r("| 指标 | 准入标准 | 实际结果 | 达标 |")
    r("|------|---------|---------|------|")
    for name, target_str, actual_str, met in checks:
        status = "是" if met else "**否**"
        r(f"| {name} | {target_str} | {actual_str} | {status} |")
    r("")
    
    # Section 4: Benchmark Data
    r("## 四、Benchmark 数据\n")
    r("```")
    r(f"{'Configuration':<30} {'Pass Rate':<15} {'Evals':<10}")
    r("-" * 55)
    r(f"{'with_skill':<30} {ws_rate*100:.1f}%{'':<10} {metrics['with_skill']['total']}")
    r(f"{'without_skill':<30} {wos_rate*100:.1f}%{'':<10} {metrics['without_skill']['total']}")
    r("-" * 55)
    r(f"{'Delta':<30} {delta*100:+.1f}%")
    r("```\n")
    
    # Section 5: Negative Deltas
    r("## 五、负向增益分析\n")
    if neg_deltas:
        r(f"发现 **{len(neg_deltas)}** 个负向增益用例：\n")
        r("| 用例名称 | with_skill | without_skill | Δ |")
        r("|---------|-----------|--------------|------|")
        for nd in neg_deltas:
            r(f"| {nd['eval_name']} | {nd['with_skill_rate']*100:.1f}% | {nd['without_skill_rate']*100:.1f}% | {nd['delta']*100:+.1f}% |")
        r("")
        r("> **注意**：负向增益用例是发布红线（S/A级），根因未明确前不允许上线。")
    else:
        r("未发现负向增益用例。所有测试用例的 with_skill 表现均优于或等于 without_skill。")
    r("")
    
    # Section 6: Disaster Scenarios
    if ADMISSION_CRITERIA[risk_level]["disaster_required"]:
        r("## 六、灾难场景测试结论\n")
        if gradings["disaster"]:
            r("| 场景 | 结果 |")
            r("|------|------|")
            for dg in gradings["disaster"]:
                name = dg.get("_scenario_name", "unknown")
                rate = dg.get("summary", {}).get("pass_rate", 0)
                status = "通过" if rate == 1.0 else "**失败**"
                r(f"| {name} | {status} |")
            
            all_pass = all(g.get("summary", {}).get("pass_rate", 0) == 1.0 for g in gradings["disaster"])
            r("")
            if all_pass:
                r("**红线结论**：全部通过。")
            else:
                failed = sum(1 for g in gradings["disaster"] if g.get("summary", {}).get("pass_rate", 0) < 1.0)
                r(f"**红线结论**：{failed} 项失败，**阻止上线**。")
        else:
            r("未执行灾难场景测试。S/A级 Skill 必须执行灾难场景测试。")
        r("")
    
    # Section 7: Per-eval Breakdown
    r("## 七、逐用例详情\n")
    if gradings["with_skill"]:
        r("| 用例 | with_skill 通过率 | 通过/总计 |")
        r("|------|-----------------|----------|")
        for g in gradings["with_skill"]:
            s = g.get("summary", {})
            name = g.get("_eval_name", "unknown")
            rate = s.get("pass_rate", 0)
            passed = s.get("passed", 0)
            total = s.get("total", 0)
            r(f"| {name} | {rate*100:.1f}% | {passed}/{total} |")
    r("")
    
    # Section 8: Environment
    r("## 八、测评环境\n")
    if env_config:
        r("```json")
        r(json.dumps(env_config, indent=2, ensure_ascii=False))
        r("```")
    else:
        r("未找到 eval_environment.json，请确保测评环境已归档。")
    r("")
    
    # Section 9: Improvement Suggestions
    r("## 九、改进建议\n")
    r("_基于测评结果自动生成的改进方向，详细分析请结合人工评审反馈：_\n")

    suggestions = []
    if neg_deltas:
        suggestions.append(("P0", "修复负向增益", f"共 {len(neg_deltas)} 个用例出现 Δ < 0，建议用二分法定位问题模块"))
    if ws_rate < target:
        gap = (target - ws_rate) * 100
        suggestions.append(("P0", "提升通过率", f"当前通过率距准入标准差 {gap:.1f}%"))
    if metrics["with_skill"]["stddev"] > ADMISSION_CRITERIA[risk_level]["stddev"]:
        suggestions.append(("P1", "降低方差", "测试结果不稳定，检查 prompt 歧义或 Skill 规则冲突"))

    if suggestions:
        r("| 优先级 | 改进方向 | 具体建议 |")
        r("|--------|---------|---------|")
        for pri, direction, detail in suggestions:
            r(f"| {pri} | {direction} | {detail} |")
    else:
        r("当前测评结果良好，无紧急改进建议。")
    r("")

    # Section 10: Limitations
    r("## 十、测评局限性\n")

    # Generic file-processing simulation detection
    file_processing_simulated = False
    if env_config:
        env = env_config.get("eval_environment", env_config)
        note = env.get("note", "")
        if "模拟" in note or "simulate" in note.lower():
            file_processing_simulated = True
    
    # If it's a skill that likely uses files but we are in a simulation
    if file_processing_simulated:
        r("> ⚠️ **物理素材处理链路风险提示**")
        r(">")
        r("> 本次测评采用「纯文本模拟」方式进行，未直接输入原始二进制素材（如 PDF、")
        r("> 图像、二进制文档）。这导致 Skill 涉及的物理文件处理链路**未被真实验证**：")
        r(">")
        r("> 1. **上传链路可行性**：脚本调用及存储服务的连通性")
        r("> 2. **文件解析健壮性**：复杂文件（多页、大尺寸）的解析耗时与稳定性")
        r("> 3. **视觉/结构提取**：针对图片 OCR 或复杂表格识别的实际准确率")
        r("> 4. **并发处理能力**：多文件并行解析时的资源竞争与逻辑保护")
        r(">")
        r("> **建议补充集成测试**（在真实执行环境中）：")
        r("> - 使用 1-2 个代表性的真实素材执行完整链路，验证端到端成功率")
        r("> - 验证特殊文件格式（如加密 PDF、极低分辨率图像）的降级行为")
        r(">")
        r("> 当前结论仅代表**业务逻辑编排**层面的质量，不能等同于生产环境的端到端可靠性。")
    else:
        r("本次测评未发现明显局限性。建议在发布前补充 1-2 个端到端集成测试，以验证底层工具（如上传、解析）的连通性。")
    r("")

    r("---\n")
    r(f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    # Write report
    report_content = "\n".join(report_lines)
    
    if output_path is None:
        output_path = os.path.join(workspace_dir, "eval-report.md")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    print(f"Report generated: {output_path}")
    print(f"Decision: {decision}")
    print(f"Pass Rate: {ws_rate*100:.1f}% (target: >= {target*100:.0f}%)")
    print(f"Delta: {delta*100:+.1f}%")
    if neg_deltas:
        print(f"WARNING: {len(neg_deltas)} negative delta eval(s) found!")
    
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate AI Skill evaluation report")
    parser.add_argument("workspace_dir", help="Path to the workspace/iteration directory")
    parser.add_argument("--skill-name", required=True, help="Name of the skill being evaluated")
    parser.add_argument("--risk-level", choices=["S", "A", "B", "C"], default="B",
                        help="Risk level of the skill (default: B)")
    parser.add_argument("--output", help="Output path for the report (default: <workspace>/eval-report.md)")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.workspace_dir):
        print(f"Error: workspace directory not found: {args.workspace_dir}")
        sys.exit(1)
    
    generate_report(args.workspace_dir, args.skill_name, args.risk_level, args.output)


if __name__ == "__main__":
    main()
