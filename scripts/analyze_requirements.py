#!/usr/bin/env python3
"""
SkillSentry 需求分析脚本 - Step 0 自动化
从 SKILL.md 中提取规则，分类为显性/流程/隐性规则，输出 requirements.cache.json

用法：
  python3 analyze_requirements.py <skill_path>/SKILL.md [--output requirements.cache.json]
"""

import json, os, sys, argparse, hashlib, re
from datetime import datetime

def md5_file(path):
    return hashlib.md5(open(path, 'rb').read()).hexdigest()

def scan_explicit(content, lines):
    """语义扫描：找显性规则（必须/禁止/不得/严禁/如果...则）"""
    rules = []
    patterns = [
        (r'必须', 'high'),
        (r'禁止', 'high'),
        (r'不得', 'high'),
        (r'严禁', 'high'),
        (r'如果.*则', 'medium'),
        (r'务必', 'medium'),
        (r'固定为', 'low'),
    ]
    seen = set()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') and len(stripped) < 10:
            continue
        for pat, default_risk in patterns:
            if re.search(pat, stripped):
                key = stripped[:60]
                if key not in seen:
                    seen.add(key)
                    risk = 'high' if any(k in stripped for k in ['必须', '禁止', '不得', '严禁']) else default_risk
                    ref = f"R-{len(rules)+1:02d}"
                    desc = stripped[:120]
                    rules.append({"ref": ref, "description": desc, "risk": risk, "line": i})
                    break
    return rules

def scan_process(content, lines):
    """角色流扫描：找流程规则（流程/步骤）"""
    rules = []
    flow_pattern = re.compile(r'^#{2,3}\s*(流程\s*[A-C]|步骤\s*[A-C]?\d)')
    for i, line in enumerate(lines, 1):
        if flow_pattern.match(line.strip()):
            ref = f"F-{len(rules)+1:02d}"
            desc = line.strip().lstrip('#').strip()
            rules.append({"ref": ref, "description": desc, "line": i})
    
    # 也找关键的展示规则
    display_patterns = [
        (r'有效蓝票.*标注', '蓝票标注规则'),
        (r'红字发票.*标注', '红票标注规则'),
        (r'状态.*标注', '状态标注规则'),
        (r'优先展示', '排序优先规则'),
        (r'意图.*引导|不明确.*询问', '意图引导规则'),
        (r'额度.*提醒|可用额度.*低', '额度提醒规则'),
    ]
    for i, line in enumerate(lines, 1):
        for pat, name in display_patterns:
            if re.search(pat, line) and not any(r['description'] == name for r in rules):
                ref = f"F-{len(rules)+1:02d}"
                rules.append({"ref": ref, "description": name, "line": i})
                break
    return rules

def scan_implicit(content, lines):
    """负向空间推演：找隐性规则"""
    rules = []
    
    implicit_checks = [
        (r'编造|猜测|虚构', '不得编造数据去查询', 'high'),
        (r'重复.*查询|多次.*相同', '不得对同一输入重复查询', 'medium'),
        (r'额度.*低|额度.*10%', '低额度时应提醒用户', 'medium'),
        (r'403|权限不足|无权限', '权限不足时应提示申请', 'medium'),
        (r'链接.*过期|链接.*无效', '链接过期时应降级处理', 'medium'),
        (r'多个订单号|多个发票号', '多输入时应逐个处理', 'low'),
    ]
    for pat, desc, risk in implicit_checks:
        if re.search(pat, content):
            ref = f"I-{len(rules)+1:02d}"
            rules.append({"ref": ref, "description": desc, "risk": risk})
    return rules

def main():
    parser = argparse.ArgumentParser(description='SkillSentry 需求分析')
    parser.add_argument('skill_md', help='被测 SKILL.md 路径')
    parser.add_argument('--output', '-o', help='输出 requirements.cache.json 路径')
    parser.add_argument('--skill-name', '-n', help='Skill 名称（可选，自动推断）')
    args = parser.parse_args()

    skill_path = args.skill_md
    if not os.path.exists(skill_path):
        print(f"❌ 找不到文件：{skill_path}", file=sys.stderr)
        sys.exit(1)

    with open(skill_path, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = content.split('\n')
    skill_hash = md5_file(skill_path)

    # 推断 skill name
    skill_name = args.skill_name or os.path.basename(os.path.dirname(skill_path))

    # 三步扫描
    explicit = scan_explicit(content, lines)
    process = scan_process(content, lines)
    implicit = scan_implicit(content, lines)

    all_rules = explicit + process + implicit
    high_risk = [r for r in all_rules if r.get('risk') == 'high']

    # 构建 requirements.cache.json
    result = {
        "skill_hash": skill_hash,
        "analyzed_at": datetime.now().isoformat(),
        "skill_name": skill_name,
        "rules": {
            "explicit": explicit,
            "process": process,
            "implicit": implicit,
        },
        "extra_rules": [],
        "test_plan": {
            "mode": "quick",
            "coverage_target": "≥40%",
            "estimated_cases": max(8, len(all_rules) // 2),
            "focus_areas": [r['ref'] for r in high_risk],
        },
        "stats": {
            "total_rules": len(all_rules),
            "explicit_count": len(explicit),
            "process_count": len(process),
            "implicit_count": len(implicit),
            "high_risk_count": len(high_risk),
        }
    }

    # 输出
    output_path = args.output
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    # 打印可读报告
    print(f"📋 需求分析 · {skill_name}")
    print(f"   SKILL.md hash: {skill_hash[:12]}")
    print(f"   总行数: {len(lines)}")
    print()

    print(f"发现规则 {len(all_rules)} 条：")
    print()

    if explicit:
        print(f"显性规则（{len(explicit)}条）—— 规范里明确写出来的")
        for r in explicit:
            risk_mark = {'high': '🔴', 'medium': '🟡', 'low': '⚪'}[r['risk']]
            print(f"  {r['ref']}  {r['description'][:80]:<80} {risk_mark} {r['risk']}")
        print()

    if process:
        print(f"流程规则（{len(process)}条）—— 从执行路径推导出来的")
        for r in process:
            print(f"  {r['ref']}  {r['description'][:80]}")
        print()

    if implicit:
        print(f"隐性规则（{len(implicit)}条）—— 规范没写，但显然不该有的行为 ⚠️")
        for r in implicit:
            risk_mark = {'high': '🔴', 'medium': '🟡', 'low': '⚪'}[r.get('risk', 'low')]
            print(f"  {r['ref']}  {r['description'][:80]:<80} {risk_mark} {r.get('risk', 'low')}")
        print()

    print(f"测试计划：quick 模式，目标覆盖 ≥40%，预计 ~{result['test_plan']['estimated_cases']} 个用例")
    if high_risk:
        print(f"重点关注：{', '.join(r['ref'] for r in high_risk)}")

if __name__ == '__main__':
    main()
