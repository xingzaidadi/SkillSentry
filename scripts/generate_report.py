#!/usr/bin/env python3
"""SkillSentry 报告生成器 — 模板填充，不依赖 LLM"""
import json, os, sys, glob
from datetime import datetime
from pathlib import Path

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def find_session_dir(skill_name, sessions_base=None):
    """找最新的 session 目录"""
    if sessions_base is None:
        sessions_base = os.path.expanduser("~/.openclaw/workspace/skills/skill-eval-测评/sessions")
    skill_dir = os.path.join(sessions_base, skill_name)
    if not os.path.isdir(skill_dir):
        print(f"❌ 未找到测评记录: {skill_dir}")
        sys.exit(1)
    dirs = sorted([d for d in os.listdir(skill_dir) if os.path.isdir(os.path.join(skill_dir, d))], reverse=True)
    if not dirs:
        print(f"❌ 无测评记录: {skill_dir}")
        sys.exit(1)
    return os.path.join(skill_dir, dirs[0])

def collect_results(session_dir):
    """收集所有 eval 的 grading 结果"""
    evals_path = os.path.join(session_dir, "evals.json")
    evals = load_json(evals_path) if os.path.exists(evals_path) else []

    results = []
    for ev in evals:
        eval_id = ev["id"]
        grading_path = os.path.join(session_dir, eval_id, "grading.json")
        if os.path.exists(grading_path):
            g = load_json(grading_path)
            results.append({**ev, "grading": g})
        else:
            results.append({**ev, "grading": {"authoritative_pass_rate": 0, "assertions": []}})
    return results

def generate_html(skill_name, mode, results, model="xiaomi/mimo-v2-pro-mit"):
    """生成 HTML 报告"""
    total_assertions = sum(len(r["grading"].get("assertions", [])) for r in results)
    passed_assertions = sum(
        sum(1 for a in r["grading"].get("assertions", []) if a.get("result") == "PASS")
        for r in results
    )
    pass_rate = passed_assertions / total_assertions if total_assertions else 0

    exact_match = sum(
        sum(1 for a in r["grading"].get("assertions", []) if a.get("precision") == "exact_match" and a.get("result") == "PASS")
        for r in results
    )
    total_exact = sum(
        sum(1 for a in r["grading"].get("assertions", []) if a.get("precision") == "exact_match")
        for r in results
    )

    decision_class = "pass" if pass_rate >= 0.95 else ("conditional" if pass_rate >= 0.8 else "fail")
    decision_label = "PASS — 通过 · S 级" if pass_rate >= 0.95 else ("CONDITIONAL PASS — 有条件通过" if pass_rate >= 0.8 else "FAIL — 不通过")
    decision_icon = "✅" if pass_rate >= 0.95 else ("⚠️" if pass_rate >= 0.8 else "❌")

    type_names = {"happy_path": "happy_path", "negative": "negative", "edge_case": "edge_case",
                  "atomic": "atomic", "variant": "variant", "robustness": "robustness",
                  "e2e": "e2e", "regression": "regression"}

    eval_details = ""
    for r in results:
        g = r.get("grading", {})
        assertions = g.get("assertions", [])
        passed = sum(1 for a in assertions if a.get("result") == "PASS")
        total = len(assertions)
        badge_class = "badge-pass" if passed == total else "badge-fail"

        assertion_items = ""
        for a in assertions:
            result_class = "assert-pass" if a.get("result") == "PASS" else "assert-fail"
            symbol = "✓" if a.get("result") == "PASS" else "✗"
            rule_ref = a.get("rule_ref", "")
            rule_tag = f'<br><span class="rule-tag"><span class="rule-id">{rule_ref}</span></span>' if rule_ref else ""
            assertion_items += f'<li><span class="{result_class}">{symbol}</span><div><span>{a["text"]}</span>{rule_tag}</div></li>\n'

        eval_details += f'''
  <details class="eval-item eval-pass">
    <summary class="eval-summary">
      <span class="eval-id">#{r["id"].split("-")[1]}</span>
      <span class="eval-name">{r["display_name"]}</span>
      <span class="eval-tag">{type_names.get(r.get("type",""), r.get("type",""))}</span>
      <span class="badge {badge_class}">{passed}/{total}</span>
    </summary>
    <div class="eval-detail">
      <div class="detail-section">
        <div class="detail-label">断言结果（{passed}/{total} 通过）</div>
        <ul class="assertion-list">{assertion_items}</ul>
      </div>
    </div>
  </details>'''

    date_str = datetime.now().strftime("%Y-%m-%d")

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{skill_name} 测评报告</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;background:#f5f6fa;color:#2c3e50;line-height:1.6}}
.container{{max-width:1100px;margin:0 auto;padding:32px 24px}}
.report-header{{background:linear-gradient(135deg,#1a1a2e 0%,#16213e 50%,#0f3460 100%);color:#fff;padding:40px;border-radius:16px;margin-bottom:32px}}
.report-header h1{{font-size:28px;font-weight:700;margin-bottom:8px}}
.report-header .subtitle{{opacity:.7;font-size:14px;margin-bottom:20px}}
.report-header .meta-row{{display:flex;gap:28px;flex-wrap:wrap}}
.report-header .meta-item .label{{opacity:.6;display:block;font-size:11px}}
.report-header .meta-item .value{{font-weight:600;font-size:14px}}
.decision-banner{{padding:24px 32px;border-radius:12px;margin-bottom:32px;display:flex;align-items:flex-start;gap:20px}}
.decision-banner.pass{{background:linear-gradient(135deg,#f0fff4,#c6f6d5);border:2px solid #38a169}}
.decision-banner.conditional{{background:linear-gradient(135deg,#fff8e6,#ffecc0);border:2px solid #f0a500}}
.decision-banner.fail{{background:linear-gradient(135deg,#fff5f5,#fed7d7);border:2px solid #e53e3e}}
.decision-icon{{font-size:40px;flex-shrink:0;margin-top:2px}}
.decision-label{{font-size:22px;font-weight:800}}
.decision-banner.pass .decision-label{{color:#276749}}
.decision-banner.conditional .decision-label{{color:#b07800}}
.decision-banner.fail .decision-label{{color:#9b2c2c}}
.decision-desc{{font-size:14px;color:#555;margin-top:8px;line-height:1.8}}
.card{{background:#fff;border-radius:12px;padding:28px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card h2{{font-size:18px;font-weight:700;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #f0f2f5;color:#1a1a2e}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#f8f9fa;text-align:left;padding:10px 14px;font-weight:600;color:#555;border-bottom:2px solid #e8eaf0}}
td{{padding:10px 14px;border-bottom:1px solid #f0f2f5;vertical-align:top}}
.badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap}}
.badge-pass{{background:#e6f9f0;color:#0d8c4a}}
.badge-fail{{background:#fce8e8;color:#c0392b}}
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:20px}}
.metric-card{{background:#f8f9fa;border-radius:10px;padding:16px;text-align:center}}
.metric-card .metric-value{{font-size:28px;font-weight:800;color:#0d8c4a}}
.metric-card .metric-label{{font-size:12px;color:#888;margin-top:4px}}
.eval-item{{border-radius:8px;margin-bottom:8px;border:1px solid #eef0f8;overflow:hidden}}
.eval-item.eval-pass{{border-color:#c3e6cb}}
.eval-summary{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;list-style:none;user-select:none;background:#f6fff9}}
.eval-summary::-webkit-details-marker{{display:none}}
.eval-summary::before{{content:"▶";font-size:10px;color:#bbb;transition:transform .2s;flex-shrink:0}}
details[open]>.eval-summary::before{{transform:rotate(90deg)}}
.eval-id{{font-size:12px;color:#bbb;font-weight:700;min-width:26px}}
.eval-name{{font-size:13px;font-weight:500;flex:1}}
.eval-tag{{font-size:11px;color:#999;background:#f0f2f5;padding:2px 8px;border-radius:10px;white-space:nowrap}}
.eval-detail{{padding:16px 20px 20px;border-top:1px solid #eef0f8;background:#fff}}
.detail-section{{margin-bottom:12px}}
.detail-label{{font-size:11px;font-weight:700;color:#aaa;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}}
.assertion-list{{list-style:none;margin-top:6px}}
.assertion-list li{{display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid #f0f2f5;font-size:12px;color:#444}}
.assert-pass{{color:#0d8c4a;flex-shrink:0;font-weight:700;margin-top:1px}}
.assert-fail{{color:#c0392b;flex-shrink:0;font-weight:700;margin-top:1px}}
.rule-tag{{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;background:#edf2f7;border-radius:4px;font-size:12px;color:#4a5568;margin:2px;white-space:nowrap}}
.rule-tag .rule-id{{font-family:monospace;font-weight:700;color:#2d3748;font-size:11px}}
.issue-item{{padding:16px;border-radius:8px;margin-bottom:12px;border-left:4px solid}}
.issue-p0{{background:#fce8e8;border-color:#e74c3c}}
.issue-p1{{background:#fff5e6;border-color:#e07b00}}
.issue-title{{font-weight:700;font-size:14px;margin-bottom:6px}}
.issue-desc{{font-size:13px;color:#555;line-height:1.7}}
.footer{{text-align:center;font-size:12px;color:#bbb;margin-top:40px;padding-top:20px;border-top:1px solid #e8eaf0}}
</style>
</head>
<body>
<div class="container">

<div class="report-header">
  <h1>{skill_name} 测评报告</h1>
  <div class="subtitle">AI Skill 系统性测评 · {mode} 模式</div>
  <div class="meta-row">
    <div class="meta-item"><span class="label">被测 Skill</span><span class="value">{skill_name}</span></div>
    <div class="meta-item"><span class="label">测评日期</span><span class="value">{date_str}</span></div>
    <div class="meta-item"><span class="label">测评模式</span><span class="value">{mode}</span></div>
    <div class="meta-item"><span class="label">模型</span><span class="value">{model}</span></div>
  </div>
</div>

<div class="decision-banner {decision_class}">
  <div class="decision-icon">{decision_icon}</div>
  <div>
    <div class="decision-label">{decision_label}</div>
    <div class="decision-desc">全部 {len(results)} 个用例 {total_assertions} 条断言，精确通过率 {pass_rate*100:.0f}%。</div>
  </div>
</div>

<div class="card">
  <h2>二、关键指标</h2>
  <div class="metric-grid">
    <div class="metric-card"><div class="metric-value">{pass_rate*100:.0f}%</div><div class="metric-label">精确通过率（{passed_assertions}/{total_assertions}）</div></div>
    <div class="metric-card"><div class="metric-value">{len(results)}</div><div class="metric-label">测试用例</div></div>
    <div class="metric-card"><div class="metric-value">{total_assertions}</div><div class="metric-label">总断言数</div></div>
    <div class="metric-card"><div class="metric-value">{total_exact}</div><div class="metric-label">exact_match 断言</div></div>
  </div>
</div>

<div class="card">
  <h2>三、各用例执行情况</h2>
  {eval_details}
</div>

<div class="footer">
  生成时间：{date_str} · SkillSentry (OpenClaw) · {skill_name} · {mode}
</div>

</div>
</body>
</html>'''
    return html

def main():
    if len(sys.argv) < 2:
        print("用法: python3 generate_report.py <skill_name> [mode]")
        print("示例: python3 generate_report.py mify-data-factory quick")
        sys.exit(1)

    skill_name = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "quick"
    model = sys.argv[3] if len(sys.argv) > 3 else "xiaomi/mimo-v2-pro-mit"

    session_dir = find_session_dir(skill_name)
    print(f"📂 Session: {session_dir}")

    results = collect_results(session_dir)
    print(f"📋 用例数: {len(results)}")

    html = generate_html(skill_name, mode, results, model)

    output_path = os.path.join(session_dir, "report.html")
    with open(output_path, "w") as f:
        f.write(html)
    print(f"✅ 报告已生成: {output_path}")
    print(f"📊 大小: {len(html)} bytes")
    return output_path

if __name__ == "__main__":
    main()
