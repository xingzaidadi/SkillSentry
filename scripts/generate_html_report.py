#!/usr/bin/env python3
"""
generate_html_report.py  v2.0

从 iteration workspace 读取所有 grading.json，生成可视化 HTML 测评报告。
新增功能：
  - MCP 调用链展示（从 grading.json 的 mcp_calls 字段读取）
  - Benchmark Tab（方差、Token、逐断言多次矩阵）—— 数据存在时自动启用
  - 人工反馈区（Feedback textarea，保存到 feedback.json）
  - 跨 iteration 对比视图（检测同级 iteration-* 目录）
  - 视觉风格升级（Poppins + Lora 字体，暖色调 #faf9f5）

用法：
  python3 generate_html_report.py <workspace_dir> \
    --skill-name <name> \
    --risk-level <S|A|B|C> \
    [--user <测试账号>] \
    [--output <path/to/report.html>]
"""

import json, os, sys, argparse, glob, re
from datetime import datetime

# ── 准入阈值 ─────────────────────────────────────────────────────────────────
ADMISSION = {
    "S": {"pass_rate": 0.95, "delta_min": 0.0, "stddev": 0.05,
          "coverage": 0.95, "hallucination": 0, "disaster_required": True},
    "A": {"pass_rate": 0.90, "delta_min": 0.0, "stddev": 0.10,
          "coverage": 0.85, "hallucination": 1, "disaster_required": True},
    "B": {"pass_rate": 0.80, "delta_min": -0.05, "stddev": 0.20,
          "coverage": 0.70, "hallucination": 2, "disaster_required": False},
    "C": {"pass_rate": 0.70, "delta_min": None, "stddev": 0.30,
          "coverage": 0.50, "hallucination": None, "disaster_required": False},
}
RISK_LABEL = {"S": "S级（关键）", "A": "A级（重要）",
              "B": "B级（一般）",  "C": "C级（辅助）"}

TYPE_COLOR = {
    "happy_path": "#3b82f6", "atomic": "#8b5cf6",
    "business_logic": "#f59e0b", "boundary": "#06b6d4",
    "robustness": "#10b981", "negative": "#6b7280", "consistency": "#ec4899",
    "正常路径": "#3b82f6", "原子场景": "#8b5cf6", "业务逻辑": "#f59e0b",
    "边界测试": "#06b6d4", "鲁棒性": "#10b981", "负向测试": "#6b7280", "一致性": "#ec4899",
}
TYPE_LABEL = {
    "happy_path": "正常路径", "atomic": "原子场景",
    "business_logic": "业务逻辑", "boundary": "边界测试",
    "robustness": "鲁棒性", "negative": "负向测试", "consistency": "一致性",
    "正常路径": "正常路径", "原子场景": "原子场景", "业务逻辑": "业务逻辑",
    "边界测试": "边界测试", "鲁棒性": "鲁棒性", "负向测试": "负向测试", "一致性": "一致性",
}

MCP_STATUS_COLOR = {"success": "#788c5d", "error": "#c44", "warn": "#d97757"}


def load_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return None
    return None


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def collect_evals(ws_dir):
    by_id = {}
    for d in sorted(os.listdir(ws_dir)):
        full = os.path.join(ws_dir, d)
        if not os.path.isdir(full) or not d.startswith("eval-"):
            continue
        parts = d.split("-")
        try:
            eid = int(parts[1])
        except (IndexError, ValueError):
            continue
        has_meta = os.path.exists(os.path.join(full, "eval_metadata.json"))
        if eid not in by_id:
            by_id[eid] = (d, full, has_meta)
        else:
            prev_d, prev_full, prev_meta = by_id[eid]
            if has_meta and not prev_meta:
                by_id[eid] = (d, full, has_meta)
            elif has_meta == prev_meta and len(d) > len(prev_d):
                by_id[eid] = (d, full, has_meta)

    dirs = []
    for eid, (d, full, _) in sorted(by_id.items()):
        ws_g  = load_json(os.path.join(full, "with_skill",    "grading.json"))
        wos_g = load_json(os.path.join(full, "without_skill", "grading.json"))
        meta  = load_json(os.path.join(full, "eval_metadata.json"))
        prompt = (meta.get("prompt", "") if meta else "") or ""
        display = (meta.get("display_name") or meta.get("eval_name") or d) if meta else d
        dirs.append({
            "id": eid, "dir": d, "name": display,
            "type": meta.get("type", "") if meta else "",
            "prompt": prompt, "ws_g": ws_g, "wos_g": wos_g,
        })
    dirs.sort(key=lambda x: x["id"])
    return dirs


def collect_disaster(ws_dir):
    disaster = []
    base = os.path.join(ws_dir, "disaster-scenarios") if os.path.exists(
        os.path.join(ws_dir, "disaster-scenarios")) else ws_dir
    for pattern in [os.path.join(ws_dir, "disaster-*"), os.path.join(base, "*")]:
        for d in sorted(glob.glob(pattern)):
            if not os.path.isdir(d):
                continue
            name = os.path.basename(d)
            g = (load_json(os.path.join(d, "grading.json")) or
                 load_json(os.path.join(d, "outputs", "grading.json")))
            if g:
                passed = g["summary"]["pass_rate"] >= 1.0
                disaster.append({"name": name, "grading": g, "passed": passed})
    seen = set()
    return [x for x in disaster if x["name"] not in seen and not seen.add(x["name"])]


def collect_other_iterations(ws_dir):
    """收集同级目录中其他 iteration-N 或 session 的汇总数据，用于跨版本对比。
    兼容两种模式：
    - 独立 Skill 模式：ws_dir = .../evals/iteration-N，兄弟目录为其他 iteration
    - eval-workspace 模式：ws_dir = sessions/YYYY-MM-DD_NNN/iteration-N，
      先查当前 session 内其他 iteration，再查其他 session 的最新 iteration
    """
    parent = os.path.dirname(ws_dir)
    current = os.path.basename(ws_dir)
    others = []

    def summarize_iteration(iter_dir, label):
        total_p = total_t = 0
        for ed in os.listdir(iter_dir):
            ef = os.path.join(iter_dir, ed)
            if not os.path.isdir(ef) or not ed.startswith("eval-"):
                continue
            g = load_json(os.path.join(ef, "with_skill", "grading.json"))
            if g:
                total_p += g["summary"]["passed"]
                total_t += g["summary"]["total"]
        if total_t:
            return {"name": label, "pass_rate": round(total_p / total_t, 4),
                    "passed": total_p, "total": total_t}
        return None

    # 查兄弟 iteration-N（独立 Skill 模式 或 同一 session 内多次迭代）
    for d in sorted(os.listdir(parent)):
        if d == current or not re.match(r"iteration-\d+", d):
            continue
        full = os.path.join(parent, d)
        if not os.path.isdir(full):
            continue
        result = summarize_iteration(full, d)
        if result:
            others.append(result)

    # 如果没找到兄弟 iteration，往上一级找其他 session（eval-workspace 模式）
    if not others:
        grandparent = os.path.dirname(parent)
        parent_name = os.path.basename(parent)
        if os.path.isdir(grandparent):
            for d in sorted(os.listdir(grandparent)):
                if d == parent_name:
                    continue
                full = os.path.join(grandparent, d)
                if not os.path.isdir(full) or not re.match(r"\d{4}-\d{2}-\d{2}_\d+", d):
                    continue
                # 取该 session 最新的 iteration
                iters = sorted([x for x in os.listdir(full)
                                 if re.match(r"iteration-\d+", x)
                                 and os.path.isdir(os.path.join(full, x))],
                                key=lambda x: int(x.split("-")[1]))
                if iters:
                    last_iter = os.path.join(full, iters[-1])
                    label = f"{d}/{iters[-1]}"
                    result = summarize_iteration(last_iter, label)
                    if result:
                        others.append(result)

    return others


def render_mcp_calls(mcp_calls):
    """把 grading.json 中的 mcp_calls 列表渲染为 HTML 调用链"""
    if not mcp_calls:
        return ""
    rows = ""
    total = len(mcp_calls)
    success = sum(1 for c in mcp_calls if c.get("status") == "success")
    total_ms = sum(c.get("duration_ms", 0) for c in mcp_calls)
    for i, call in enumerate(mcp_calls):
        status = call.get("status", "success")
        color = MCP_STATUS_COLOR.get(status, "#6b7280")
        icon = "✓" if status == "success" else ("!" if status == "warn" else "✗")
        name = esc(call.get("name", "unknown"))
        duration = call.get("duration_ms")
        dur_str = f"{duration}ms" if duration else ""
        note = esc(call.get("note", ""))
        result_preview = esc(str(call.get("result_preview", ""))[:120])
        fallback = esc(call.get("fallback", ""))
        rows += f"""
        <div class="mcp-row">
          <div class="mcp-step">{i+1}</div>
          <div class="mcp-name">{name}</div>
          <div class="mcp-status" style="color:{color};font-weight:700">{icon}</div>
          <div class="mcp-dur">{dur_str}</div>
          <div class="mcp-detail">
            {f'<span class="mcp-result">{result_preview}</span>' if result_preview else ""}
            {f'<span class="mcp-note">{note}</span>' if note else ""}
            {f'<span class="mcp-fallback">↳ 降级: {fallback}</span>' if fallback else ""}
          </div>
        </div>"""
    summary = f"{success}/{total} 成功"
    if total_ms:
        summary += f" · 总耗时 {total_ms}ms"
    return f"""
    <div class="mcp-chain">
      <div class="mcp-header">📡 MCP 调用链（with_skill）<span class="mcp-summary">{summary}</span></div>
      <div class="mcp-body">{rows}</div>
    </div>"""


def render_benchmark_tab(evals):
    """渲染 Benchmark Tab：方差、Token、逐断言多次运行矩阵"""
    has_benchmark = any(
        ev["ws_g"] and ev["ws_g"].get("runs") for ev in evals
    )
    if not has_benchmark:
        return "", False

    rows_html = ""
    for ev in evals:
        ws_g = ev["ws_g"]
        wos_g = ev["wos_g"]
        if not ws_g:
            continue
        runs_w  = ws_g.get("runs", [])
        runs_wo = (wos_g or {}).get("runs", [])
        if not runs_w:
            continue

        # 计算均值和标准差
        def stats(runs):
            rates = [r.get("pass_rate", 0) for r in runs]
            if not rates:
                return 0, 0
            mean = sum(rates) / len(rates)
            variance = sum((r - mean) ** 2 for r in rates) / len(rates)
            return mean, variance ** 0.5

        mean_w,  std_w  = stats(runs_w)
        mean_wo, std_wo = stats(runs_wo)
        delta = mean_w - mean_wo

        delta_col = "#788c5d" if delta > 0 else ("#c44" if delta < 0 else "#b0aea5")
        delta_str = f"+{delta:.0%}" if delta > 0 else (f"{delta:.0%}" if delta < 0 else "持平")
        std_cls = "warn" if std_w > 0.3 else ""

        # 逐断言多次运行矩阵
        assertions = ws_g.get("expectations", [])
        matrix_rows = ""
        for ai, exp in enumerate(assertions):
            run_cells = ""
            for ri, run in enumerate(runs_w):
                run_exps = run.get("expectations", [])
                if ai < len(run_exps):
                    p = run_exps[ai].get("passed", False)
                    run_cells += f'<td class="{"mp" if p else "mf"}">{" ✓" if p else "✗"}</td>'
                else:
                    run_cells += '<td>—</td>'
            matrix_rows += f"<tr><td class='at'>{esc(exp['text'][:60])}</td>{run_cells}</tr>"

        run_headers = "".join(f"<th>R{i+1}</th>" for i in range(len(runs_w)))

        rows_html += f"""
      <div class="bm-eval">
        <div class="bm-eval-header">
          <span class="bm-id">#{ev['id']}</span>
          <span class="bm-name">{esc(ev['name'])}</span>
          <span class="bm-rate">{mean_w:.0%} <span class="bm-std {std_cls}">±{std_w:.0%}</span></span>
          <span class="bm-delta" style="color:{delta_col}">{delta_str}</span>
        </div>
        <div class="bm-matrix">
          <table>
            <thead><tr><th>断言</th>{run_headers}</tr></thead>
            <tbody>{matrix_rows}</tbody>
          </table>
        </div>
      </div>"""

    return rows_html, True


def _render_trigger_eval(trigger_eval):
    """渲染触发率预评估章节（来自 trigger_eval.json）"""
    if not trigger_eval:
        return """
<div class="section">
  <div class="section-title">🎯 十一、触发率预评估（AI 模拟）</div>
  <div class="chart-container">
    <p style="color:#b0aea5;font-size:13px;">⚠ 本次测评未生成触发率预评估数据（trigger_eval.json 不存在）。触发率测评在阶段一执行，请确认 SKILL.md 流程完整运行。</p>
  </div>
</div>"""

    summary = trigger_eval.get("summary", {})
    tp_rate = summary.get("tp_trigger_rate", 0)
    tn_rate = summary.get("tn_no_trigger_rate", 0)
    boundary_rate = summary.get("boundary_uncertain_rate", 0)
    confidence = summary.get("overall_confidence", "unknown")
    issues = summary.get("issues", [])

    tp_color = "#788c5d" if tp_rate >= 0.8 else ("#d97757" if tp_rate >= 0.7 else "#c44")
    tn_color = "#788c5d" if tn_rate >= 0.9 else "#d97757"
    conf_color = {"high": "#788c5d", "medium": "#d97757", "low": "#c44"}.get(confidence, "#b0aea5")

    # 按类型分组渲染 prompt 列表
    prompts = trigger_eval.get("prompts", [])
    type_badge = {
        "true_positive": '<span style="background:#eef2e8;color:#788c5d;font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600">应触发</span>',
        "true_negative": '<span style="background:#f0f2f5;color:#6b7280;font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600">不应触发</span>',
        "boundary":      '<span style="background:#fef3e8;color:#d97757;font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600">边界情况</span>',
    }
    pred_badge = {
        "trigger":     '<span style="color:#788c5d;font-weight:700">✓ 触发</span>',
        "no_trigger":  '<span style="color:#6b7280;font-weight:700">— 不触发</span>',
        "uncertain":   '<span style="color:#d97757;font-weight:700">? 不确定</span>',
    }
    prompt_rows = ""
    for p in prompts:
        ptype = p.get("type", "")
        conf = p.get("confidence", 0)
        conf_cls = "color:#788c5d" if conf >= 0.8 else ("color:#d97757" if conf >= 0.5 else "color:#c44")
        prompt_rows += f"""
      <tr>
        <td>{type_badge.get(ptype, ptype)}</td>
        <td style="font-size:12px;color:#374151;max-width:300px">{esc(p.get('prompt',''))}</td>
        <td>{pred_badge.get(p.get('prediction',''), p.get('prediction',''))}</td>
        <td style="{conf_cls};font-weight:600;font-family:Poppins,sans-serif">{conf:.1f}</td>
        <td style="font-size:11px;color:#b0aea5">{esc(p.get('reasoning','')[:80])}</td>
      </tr>"""

    issues_html = ""
    if issues:
        issues_html = "<ul style='margin:8px 0 0 18px;font-size:12px;color:#7a3a00'>" + \
            "".join(f"<li>{esc(i)}</li>" for i in issues) + "</ul>"

    tp_warn = ""
    if tp_rate < 0.7:
        tp_warn = """
    <div style="background:#fceaea;border:1px solid #c44;border-radius:6px;padding:10px 14px;margin-top:12px">
      <span style="font-weight:700;color:#c44">❌ 触发率估算偏低（&lt;70%）</span>
      <ul style="margin:6px 0 0 18px;font-size:12px;color:#922">
        <li>建议优化 description，明确「何时触发」的场景描述</li>
        <li>建议在 description 中增加典型触发场景举例</li>
        <li>建议区分应触发和不应触发的情况</li>
      </ul>
    </div>"""

    return f"""
<div class="section">
  <div class="section-title">🎯 十一、触发率预评估（AI 模拟）</div>
  <div class="chart-container">
    <div style="background:#ebf8ff;border:1px solid #90cdf4;border-radius:6px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:#2b6cb0">
      ⚠️ 以下数据为 <strong>AI 模拟估算</strong>，基于对 Skill description 的语义分析，<strong>非真实测量值</strong>。精确触发率需 skill-creator run_eval.py（需 claude CLI 环境）。
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px">
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:{tp_color}">{int(tp_rate*100)}%</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">TP 估算触发率</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:{tn_color}">{int(tn_rate*100)}%</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">TN 估算不触发率</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:#d97757">{int(boundary_rate*100)}%</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">边界情况 uncertain</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:18px;font-weight:700;color:{conf_color}">{esc(confidence)}</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">整体置信度</div>
      </div>
    </div>
    {f'<div style="background:#fff3e0;border:1px solid #d97757;border-radius:6px;padding:10px 14px;margin-bottom:12px"><span style="font-weight:700;color:#7a3a00">发现问题：</span>{issues_html}</div>' if issues else ''}
    {tp_warn}
    <h3 style="font-size:13px;font-weight:600;color:#374151;margin:16px 0 8px">触发测试用例明细</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f8f9fa">
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">类型</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">测试 Prompt</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">预测</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">置信度</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">判断依据</th>
        </tr>
      </thead>
      <tbody>{prompt_rows}</tbody>
    </table>
  </div>
</div>"""


def _render_efficiency_section(evals, ws_dir, crit):
    """渲染效率指标汇总章节（聚合各用例的 timing.json）"""
    timings = []
    for ev in evals:
        t_path = os.path.join(ws_dir, f"eval-{ev['id']}", "with_skill", "timing.json")
        t_data = load_json(t_path)
        if t_data and t_data.get("duration_ms"):
            timings.append({
                "id": ev["id"],
                "name": ev["name"],
                "duration_ms": t_data["duration_ms"],
                "total_tokens": t_data.get("total_tokens"),
                "wos_duration_ms": None,  # without_skill timing（可选）
            })
            # 尝试读取 without_skill timing
            wos_t = load_json(os.path.join(ws_dir, f"eval-{ev['id']}", "without_skill", "timing.json"))
            if wos_t:
                timings[-1]["wos_duration_ms"] = wos_t.get("duration_ms")

    if not timings:
        return """
<div class="section">
  <div class="section-title">⏱ 十二、效率指标汇总</div>
  <div class="chart-container">
    <div style="background:#fff3e0;border:1px solid #d97757;border-radius:6px;padding:12px 16px">
      <span style="font-weight:700;color:#7a3a00">⚠ 本次测评未采集 timing 数据</span>
      <ul style="margin:6px 0 0 18px;font-size:12px;color:#7a3a00">
        <li>原因：subagent 执行结束时未写入 timing.json</li>
        <li>下次测评时，请确保在 subagent 完成后立即写入 executor_start_ms、executor_end_ms、total_tokens 字段</li>
      </ul>
    </div>
  </div>
</div>"""

    durations = sorted(t["duration_ms"] for t in timings)
    n = len(durations)
    p50 = durations[n // 2]
    p95 = durations[min(int(n * 0.95), n - 1)]
    avg_tokens = sum(t["total_tokens"] for t in timings if t["total_tokens"]) / max(1, sum(1 for t in timings if t["total_tokens"]))

    # P95 准入阈值（毫秒）
    p95_threshold_ms = crit.get("p95_ms", 15000)  # 默认 15s
    p95_ok = p95 <= p95_threshold_ms
    p95_color = "#788c5d" if p95_ok else "#c44"
    p50_color = "#788c5d" if p50 <= p95_threshold_ms * 0.6 else "#d97757"

    rows = ""
    for t in timings:
        dur = t["duration_ms"]
        dur_ok = dur <= p95_threshold_ms
        dur_color = "#788c5d" if dur_ok else "#c44"
        wos_str = f"{t['wos_duration_ms']}ms" if t["wos_duration_ms"] else "N/A"
        tok_str = str(t["total_tokens"]) if t["total_tokens"] else "N/A"
        rows += f"""
      <tr>
        <td style="color:#b0aea5;font-family:Poppins,sans-serif;font-size:11px">#{esc(str(t['id']))}</td>
        <td style="font-size:12px;color:#374151">{esc(t['name'][:40])}</td>
        <td style="font-weight:600;color:{dur_color};font-family:Poppins,sans-serif">{dur}ms</td>
        <td style="font-size:12px;color:#6b7280">{wos_str}</td>
        <td style="font-size:12px;color:#6b7280">{tok_str}</td>
        <td><span style="background:{'#eef2e8' if dur_ok else '#fceaea'};color:{'#788c5d' if dur_ok else '#c44'};font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600">{'✅ 达标' if dur_ok else '❌ 超标'}</span></td>
      </tr>"""

    return f"""
<div class="section">
  <div class="section-title">⏱ 十二、效率指标汇总</div>
  <div class="chart-container">
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px">
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:{p50_color}">{p50}ms</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">P50 响应时间</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:{p95_color}">{p95}ms</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">P95（阈值 {p95_threshold_ms}ms）</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:24px;font-weight:700;color:#6b7280">{int(avg_tokens)}</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">平均 Token/用例</div>
      </div>
      <div style="background:#f8f9fa;border-radius:8px;padding:14px;text-align:center">
        <div style="font-family:Poppins,sans-serif;font-size:18px;font-weight:700;color:#{'788c5d' if p95_ok else 'c44'}">{len(timings)}/{len(evals)}</div>
        <div style="font-size:11px;color:#b0aea5;margin-top:4px">用例有 timing 数据</div>
      </div>
    </div>
    <h3 style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px">逐用例响应时间</h3>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f8f9fa">
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">#</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">用例名称</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">with_skill</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">without_skill</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">Token (with)</th>
          <th style="padding:7px 10px;text-align:left;color:#6b7280;font-weight:600">P95 达标</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""


def _check_run_stability(ws_dir, evals):
    """P3: 检测 quick 模式两次运行的稳定性，返回稳定性报告。
    约定：两次运行分别存放在 eval-N_run1/、eval-N_run2/ 或 grading_run*.json 中。
    如果只有单次运行数据，返回 None（不做稳定性判断）。
    """
    run_rates = []
    for ev in evals:
        ws_g = ev.get("ws_g") or {}
        runs = ws_g.get("runs", [])
        if len(runs) >= 2:
            for r in runs[:2]:
                rate = r.get("pass_rate", None)
                if rate is not None:
                    run_rates.append(rate)
            break  # 找到就够了

    if len(run_rates) < 2:
        return None  # 无多次运行数据

    gap = abs(run_rates[0] - run_rates[1])
    return {
        "run1": run_rates[0],
        "run2": run_rates[1],
        "gap": gap,
        "unstable": gap > 0.15,
        "gap_pct": f"{gap:.0%}"
    }


def _build_precision_summary_html(exact_pass_rate, semantic_pass_rate, has_precision_data,
                                   total_exact_p, total_exact_t,
                                   total_semantic_p, total_semantic_t,
                                   total_existence_p, total_existence_t):
    """P1: 生成断言强度分级摘要 HTML"""
    if not has_precision_data:
        return ""

    exact_color   = "#788c5d" if (exact_pass_rate or 0) >= 0.9 else ("#d97757" if (exact_pass_rate or 0) >= 0.7 else "#c44")
    sem_color     = "#788c5d" if (semantic_pass_rate or 0) >= 0.9 else "#d97757"

    return f"""
<div style="margin-top:14px;padding:12px 16px;background:#f8f9fa;border-radius:8px;border:1px solid var(--border)">
  <div style="font-family:Poppins,sans-serif;font-size:11px;font-weight:600;color:var(--text-muted);
    text-transform:uppercase;letter-spacing:.04em;margin-bottom:10px">
    断言强度分级通过率（准入判断依据：精确断言）
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
    <div style="text-align:center;padding:8px;background:white;border-radius:6px;border:1px solid var(--border)">
      <div style="font-family:Poppins,sans-serif;font-size:20px;font-weight:700;color:{exact_color}">
        {int((exact_pass_rate or 0)*100)}%
      </div>
      <div style="font-size:10px;color:var(--text-muted);margin-top:2px">
        精确断言 ★ ({total_exact_p}/{total_exact_t})
      </div>
      <div style="font-size:10px;color:#788c5d;font-weight:600">准入判断依据</div>
    </div>
    <div style="text-align:center;padding:8px;background:white;border-radius:6px;border:1px solid var(--border)">
      <div style="font-family:Poppins,sans-serif;font-size:20px;font-weight:700;color:{sem_color}">
        {int((semantic_pass_rate or 0)*100)}%
      </div>
      <div style="font-size:10px;color:var(--text-muted);margin-top:2px">
        语义断言 ({total_semantic_p}/{total_semantic_t})
      </div>
      <div style="font-size:10px;color:var(--text-muted)">辅助参考</div>
    </div>
    <div style="text-align:center;padding:8px;background:#f0f2f5;border-radius:6px;border:1px dashed var(--border)">
      <div style="font-family:Poppins,sans-serif;font-size:20px;font-weight:700;color:var(--text-muted)">
        {total_existence_p}/{total_existence_t}
      </div>
      <div style="font-size:10px;color:var(--text-muted);margin-top:2px">
        存在性断言 (不计入)
      </div>
      <div style="font-size:10px;color:var(--text-muted)">不计入准入</div>
    </div>
  </div>
</div>"""


def build_report(ws_dir, skill_name, risk_level, user, output_path):
    crit = ADMISSION.get(risk_level, ADMISSION["B"])
    evals = collect_evals(ws_dir)
    disaster = collect_disaster(ws_dir)
    other_iterations = collect_other_iterations(ws_dir)
    current_iter_name = os.path.basename(ws_dir)

    if not evals:
        print("WARNING: No eval directories found. Report will be empty.")

    # ── Aggregate stats ───────────────────────────────────────────────────
    total_ws_p = total_ws_t = total_wos_p = total_wos_t = 0
    # P1: 断言强度分级聚合
    total_exact_p = total_exact_t = 0
    total_semantic_p = total_semantic_t = 0
    total_existence_p = total_existence_t = 0
    neg_delta = []
    type_stats = {}

    for ev in evals:
        ws_g, wos_g = ev["ws_g"], ev["wos_g"]
        ws_r  = ws_g["summary"]["pass_rate"]  if ws_g  else 0.0
        wos_r = wos_g["summary"]["pass_rate"] if wos_g else 0.0
        ws_p  = ws_g["summary"]["passed"]     if ws_g  else 0
        ws_t  = ws_g["summary"]["total"]      if ws_g  else 0
        wos_p = wos_g["summary"]["passed"]    if wos_g else 0
        wos_t = wos_g["summary"]["total"]     if wos_g else 0
        ev["ws_rate"]  = ws_r;  ev["wos_rate"] = wos_r
        ev["ws_p"] = ws_p;  ev["ws_t"] = ws_t
        ev["wos_p"] = wos_p; ev["wos_t"] = wos_t
        ev["delta"] = ws_r - wos_r
        total_ws_p  += ws_p;  total_ws_t  += ws_t
        total_wos_p += wos_p; total_wos_t += wos_t
        if ev["delta"] < 0:
            neg_delta.append(ev)
        etype = ev.get("type", "unknown")
        if etype not in type_stats:
            type_stats[etype] = {"p": 0, "t": 0}
        type_stats[etype]["p"] += ws_p
        type_stats[etype]["t"] += ws_t

        # P1: 从 grading.json 提取分级断言数据
        if ws_g:
            pb = ws_g.get("summary", {}).get("precision_breakdown", {})
            if pb:
                em = pb.get("exact_match", {}); total_exact_p += em.get("passed", 0); total_exact_t += em.get("total", 0)
                sm = pb.get("semantic", {});    total_semantic_p += sm.get("passed", 0); total_semantic_t += sm.get("total", 0)
                ex = pb.get("existence", {});   total_existence_p += ex.get("passed", 0); total_existence_t += ex.get("total", 0)
            else:
                # 旧版 grading.json 无 precision_breakdown，全部计入综合
                total_exact_p += ws_p; total_exact_t += ws_t

    overall_ws  = total_ws_p  / total_ws_t  if total_ws_t  else 0
    overall_wos = total_wos_p / total_wos_t if total_wos_t else 0
    overall_delta = overall_ws - overall_wos

    # P1: 计算分级通过率（准入判断用 exact_match）
    exact_pass_rate    = total_exact_p    / total_exact_t    if total_exact_t    else None
    semantic_pass_rate = total_semantic_p / total_semantic_t if total_semantic_t else None
    # 准入判断：有 exact 数据用 exact，否则 fallback 到综合
    authoritative_rate = exact_pass_rate if exact_pass_rate is not None else overall_ws
    has_precision_data = total_exact_t > 0 and (total_semantic_t > 0 or total_existence_t > 0)

    # P3: quick 模式两次运行稳定性检测
    run_stability = _check_run_stability(ws_dir, evals)

    disaster_pass = all(d["passed"] for d in disaster) if disaster else True

    # Decision（P4: 触发率降级逻辑在后段 trigger_html 生成后合并）
    # 先用通用逻辑得到 base decision，后段可降级
    if (authoritative_rate >= crit["pass_rate"] and len(neg_delta) == 0
            and (not crit["disaster_required"] or disaster_pass)):
        decision = "PASS"
        decision_color = "#1a3a2a"
        decision_text_color = "#6ee7b7"
        decision_icon = "✅"
    elif authoritative_rate >= crit["pass_rate"] - 0.05:
        decision = "CONDITIONAL PASS"
        decision_color = "#3a2a0a"
        decision_text_color = "#fde68a"
        decision_icon = "⚠️"
    else:
        decision = "FAIL"
        decision_color = "#3a0a0a"
        decision_text_color = "#fca5a5"
        decision_icon = "❌"

    # P3: quick 不稳定降级
    if run_stability and run_stability.get("unstable"):
        if decision == "PASS":
            decision = "CONDITIONAL PASS"
            decision_color = "#3a2a0a"
            decision_text_color = "#fde68a"
            decision_icon = "⚠️"

    # ── Bar chart ─────────────────────────────────────────────────────────
    bars_html = ""
    for ev in evals:
        ws_r = ev["ws_rate"]
        delta = ev["delta"]
        bar_cls = "pass" if ws_r >= 0.95 else ("partial" if ws_r >= 0.5 else "fail")
        rate_cls = "s10" if ws_r >= 0.95 else ("s05" if ws_r >= 0.5 else "s00")
        bar_w = int(ws_r * 100)
        tc = TYPE_COLOR.get(ev.get("type", ""), "#6b7280")
        delta_col = "#788c5d" if delta > 0 else ("#c44" if delta < 0 else "#b0aea5")
        delta_str = f"+{delta:.0%}" if delta > 0 else (f"{delta:.0%}" if delta < 0 else "持平")
        label = esc(f"#{ev['id']} {ev['name'][:30]}")
        bars_html += f"""
      <div class="bar-item">
        <div class="bar-label">
          <span class="type-dot" style="background:{tc}"></span>{label}
        </div>
        <div class="bar-track">
          <div class="bar-fill {bar_cls}" style="width:{bar_w}%">
            <span class="bar-pct">{ev['ws_p']}/{ev['ws_t']}</span>
          </div>
        </div>
        <div class="bar-score {rate_cls}">{int(ws_r*100)}%</div>
        <div style="color:{delta_col};font-size:12px;font-weight:600;width:50px;text-align:right;flex-shrink:0">{delta_str}</div>
      </div>"""

    # ── Type stats ────────────────────────────────────────────────────────
    type_stats_html = ""
    for etype, s in type_stats.items():
        r = s["p"] / s["t"] if s["t"] else 0
        tc = TYPE_COLOR.get(etype, "#6b7280")
        tl = TYPE_LABEL.get(etype, etype)
        fill_color = "#788c5d" if r >= 0.95 else ("#d97757" if r >= 0.5 else "#c44")
        type_stats_html += f"""
      <div style="margin-bottom:14px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:13px;color:#374151;display:flex;align-items:center;gap:6px">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{tc}"></span>{tl}
          </span>
          <span style="font-size:13px;font-weight:600;color:{fill_color}">{int(r*100)}%</span>
        </div>
        <div style="height:6px;background:#e8e6dc;border-radius:3px;overflow:hidden">
          <div style="width:{int(r*100)}%;height:100%;border-radius:3px;background:{fill_color}"></div>
        </div>
        <div style="font-size:11px;color:#b0aea5;margin-top:2px">{s['p']}/{s['t']} 断言通过</div>
      </div>"""

    # ── Criteria table ────────────────────────────────────────────────────
    # P1: 准入判断优先用 exact_match 通过率
    auth_label = "精确断言通过率 ★" if has_precision_data else "通过率"
    auth_rate_str = f"{int(authoritative_rate*100)}%"
    if has_precision_data:
        auth_rate_str += f" (综合{int(overall_ws*100)}%)"

    criteria_rows_html = ""
    for label, std, actual, ok in [
        (auth_label, f"≥ {int(crit['pass_rate']*100)}%", auth_rate_str, authoritative_rate >= crit["pass_rate"]),
        ("增益 Δ", "> 0（不允许负向）" if risk_level in ("S","A") else "≥ -5%",
         f"{overall_delta:+.0%}", overall_delta >= (crit["delta_min"] or -999)),
        ("负向增益", "0 个", f"{len(neg_delta)} 个", len(neg_delta) == 0),
        ("灾难场景", "全部通过" if crit["disaster_required"] else "不要求",
         f"{sum(1 for d in disaster if d['passed'])}/{len(disaster)} 通过" if disaster else "未执行",
         disaster_pass if crit["disaster_required"] else True),
    ]:
        badge = f'<span class="badge {"pass" if ok else "fail"}">{"✓ 达标" if ok else "✗ 未达标"}</span>'
        criteria_rows_html += f"<tr><td>{label}</td><td>{std}</td><td><strong>{esc(actual)}</strong></td><td>{badge}</td></tr>"

    # P3: quick 稳定性警告行
    if run_stability and run_stability.get("unstable"):
        gap_pct = run_stability["gap_pct"]
        criteria_rows_html += (
            f'<tr style="background:#fff3e0"><td>结果稳定性</td><td>两次差距 ≤ 15%</td>'
            f'<td><strong style="color:#d97757">差距 {gap_pct}（不稳定）</strong></td>'
            f'<td><span class="badge warn">⚠ 建议升级 standard</span></td></tr>'
        )

    # 触发率行（占位，trigger_eval 在后段读取后填充）
    criteria_rows_html += '<tr><td>触发率（AI估算）</td><td>TP ≥ 80%（参考）</td><td id="trigger-rate-cell"><em style="color:#b0aea5">见第十一章</em></td><td><span class="badge warn">⚠ 参考值</span></td></tr>'

    # P1: 断言强度分级 HTML
    precision_summary_html = _build_precision_summary_html(
        exact_pass_rate, semantic_pass_rate, has_precision_data,
        total_exact_p, total_exact_t,
        total_semantic_p, total_semantic_t,
        total_existence_p, total_existence_t,
    )

    # ── Disaster cards ────────────────────────────────────────────────────
    disaster_html = ""
    for d in disaster:
        cls = "pass" if d["passed"] else "fail"
        icon = "✅" if d["passed"] else "❌"
        assertions = ""
        for exp in d["grading"].get("expectations", []):
            ecls = "pass" if exp["passed"] else "fail"
            assertions += f"""
            <div class="assertion {ecls}">
              <div class="assertion-icon">{"✅" if exp["passed"] else "❌"}</div>
              <div class="assertion-text">
                <div class="text">{esc(exp['text'])}</div>
                <div class="evidence">{esc(exp.get('evidence',''))}</div>
              </div>
            </div>"""
        disaster_html += f"""
      <div class="disaster-card {cls}">
        <div style="display:flex;align-items:flex-start;gap:12px">
          <div style="font-size:20px;flex-shrink:0">{icon}</div>
          <div style="flex:1"><strong>{esc(d['name'])}</strong>
            <div class="assertions" style="margin-top:8px">{assertions}</div>
          </div>
        </div>
      </div>"""

    # ── Eval detail cards (with MCP + feedback) ───────────────────────────
    eval_cards_html = ""
    for i, ev in enumerate(evals):
        ws_r = ev["ws_rate"]
        badge_cls = "pass" if ws_r >= 0.95 else ("partial" if ws_r >= 0.5 else "fail")
        rate_cls  = "s10"  if ws_r >= 0.95 else ("s05"     if ws_r >= 0.5 else "s00")
        tc = TYPE_COLOR.get(ev.get("type", ""), "#6b7280")
        tl = TYPE_LABEL.get(ev.get("type", ""), ev.get("type", ""))
        delta_col = "#788c5d" if ev["delta"] > 0 else ("#c44" if ev["delta"] < 0 else "#b0aea5")
        delta_str = f"+{ev['delta']:.0%}" if ev["delta"] > 0 else (f"{ev['delta']:.0%}" if ev["delta"] < 0 else "持平")

        # MCP 调用链
        mcp_calls = (ev["ws_g"] or {}).get("mcp_calls", [])
        mcp_html = render_mcp_calls(mcp_calls)

        # execution_metrics
        metrics = (ev["ws_g"] or {}).get("execution_metrics", {})
        timing  = (ev["ws_g"] or {}).get("timing", {})
        metrics_html = ""
        if metrics or timing:
            mcp_total = metrics.get("total_mcp_calls", 0)
            errors    = metrics.get("errors_encountered", 0)
            dur_s     = timing.get("total_duration_seconds") or timing.get("duration_ms", 0) / 1000 if timing.get("duration_ms") else None
            tokens    = timing.get("total_tokens")
            parts = []
            if mcp_total:  parts.append(f"MCP调用 {mcp_total} 次")
            if errors:     parts.append(f'<span style="color:#c44">{errors} 个错误</span>')
            if dur_s:      parts.append(f"耗时 {dur_s:.1f}s")
            if tokens:     parts.append(f"tokens {tokens:,}")
            if parts:
                metrics_html = f"""
          <div style="margin-top:10px;padding:6px 10px;background:#f3f1ea;border-radius:6px;font-size:11px;color:#b0aea5;display:flex;gap:14px;flex-wrap:wrap">
            <span style="font-weight:600;color:#141413">执行统计</span> {'  ·  '.join(parts)}
          </div>"""

        # claims（隐含声明验证）
        claims = (ev["ws_g"] or {}).get("claims", [])
        claims_html = ""
        if claims:
            rows = ""
            for c in claims:
                ok = c.get("verified", False)
                color = "#788c5d" if ok else "#c44"
                icon  = "✓" if ok else "✗"
                rows += f"""
              <tr>
                <td style="color:{color};font-weight:700;width:18px">{icon}</td>
                <td style="font-size:12px;color:#374151">{esc(c.get('claim',''))}</td>
                <td style="font-size:11px;color:#b0aea5;font-style:italic">{esc(c.get('evidence',''))}</td>
              </tr>"""
            claims_html = f"""
          <div style="margin-top:12px">
            <div style="font-size:12px;font-weight:600;color:#b0aea5;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">
              隐含声明验证（幻觉检测）
            </div>
            <table style="width:100%;border-collapse:collapse;font-size:12px">
              <tbody>{rows}</tbody>
            </table>
          </div>"""

        # eval_feedback（断言质量建议）
        ef = (ev["ws_g"] or {}).get("eval_feedback", {})
        ef_html = ""
        if ef and ef.get("suggestions"):
            sugg_rows = ""
            for s in ef["suggestions"]:
                if s.get("assertion"):
                    sugg_rows += f'<li><code style="font-size:11px">{esc(s["assertion"])}</code><br><span style="color:#7a3a00">{esc(s["reason"])}</span></li>'
                else:
                    sugg_rows += f'<li style="color:#7a3a00">{esc(s["reason"])}</li>'
            overall = esc(ef.get("overall", ""))
            ef_html = f"""
          <div style="margin-top:12px;padding:10px 12px;background:#fff3e0;border:1px solid #d97757;border-radius:6px">
            <div style="font-size:12px;font-weight:600;color:#7a3a00;margin-bottom:6px">💡 断言质量建议</div>
            <ul style="font-size:12px;color:#374151;padding-left:16px;line-height:1.8">{sugg_rows}</ul>
            {f'<div style="font-size:11px;color:#b0aea5;margin-top:6px;border-top:1px solid #f0c080;padding-top:6px">{overall}</div>' if overall else ''}
          </div>"""

        # ground_truth（Layer2a 精确校验，单独读取）
        gt_path = os.path.join(ws_dir, f"eval-{ev['id']}", "with_skill", "ground_truth.json")
        gt_data = load_json(gt_path)
        gt_html = ""
        if gt_data and gt_data.get("checks"):
            gt_rows = ""
            for chk in gt_data["checks"]:
                ok    = chk.get("passed", False)
                color = "#788c5d" if ok else "#c44"
                icon  = "✓" if ok else "✗"
                gt_rows += f"""
              <div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #e8e6dc;font-size:12px">
                <span style="color:{color};font-weight:700;width:14px;flex-shrink:0">{icon}</span>
                <span style="flex:1;color:#374151">{esc(chk.get('assertion',''))}</span>
                <span style="color:#b0aea5;font-size:11px;max-width:260px;text-align:right">{esc(chk.get('evidence','')[:80])}</span>
              </div>"""
            gt_summary = gt_data.get("summary", {})
            gt_html = f"""
          <div style="margin-top:12px">
            <div style="font-size:12px;font-weight:600;color:#b0aea5;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">
              Layer2a 字段精确校验
              <span style="font-weight:400;font-size:11px;text-transform:none">（{gt_summary.get('passed',0)}/{gt_summary.get('total',0)} 通过）</span>
            </div>
            {gt_rows}
          </div>"""

        # with_skill 断言
        assertions_html = ""
        if ev["ws_g"]:
            for exp in ev["ws_g"].get("expectations", []):
                ecls   = "pass" if exp["passed"] else "fail"
                method = exp.get("method", "")
                method_tag = f'<span style="font-size:10px;color:#b0aea5;margin-left:4px">[{method}]</span>' if method else ""
                # P1: precision badge
                precision = exp.get("precision", "")
                precision_colors = {
                    "exact_match": ("★ 精确", "#788c5d", "#eef2e8"),
                    "semantic":    ("◆ 语义", "#6b7280", "#f0f2f5"),
                    "existence":   ("○ 存在性", "#b0aea5", "#f8f8f8"),
                }
                if precision in precision_colors:
                    plabel, pcolor, pbg = precision_colors[precision]
                    precision_badge = (
                        f'<span style="font-size:10px;font-weight:600;padding:1px 5px;border-radius:3px;'
                        f'color:{pcolor};background:{pbg};margin-left:5px">{plabel}</span>'
                    )
                else:
                    precision_badge = ""
                # P2: evidence_source badge
                esource = exp.get("evidence_source", "")
                esource_label = {"tool_calls": "🔧 tool_calls", "response": "📄 response", "agent_notes": "💬 agent_notes"}.get(esource, "")
                esource_tag = (
                    f'<span style="font-size:10px;color:#b0aea5;margin-left:4px">{esource_label}</span>'
                ) if esource_label else ""
                # evidence 为空时高亮提示
                evidence = exp.get("evidence", "")
                # P2: agent_notes 来源时降权提示
                agent_notes_warning = ""
                if esource == "agent_notes":
                    agent_notes_warning = '<div style="font-size:10px;color:#d97757;margin-top:2px">⚠ evidence 来自 agent_notes（AI 主观解释），可信度较低</div>'
                evidence_html = (
                    f'<div class="evidence">{esc(evidence)}</div>{agent_notes_warning}'
                ) if evidence else (
                    '<div class="evidence" style="color:#c44">⚠ evidence 为空，需补充原文引用</div>'
                )
                assertions_html += f"""
            <div class="assertion {ecls}">
              <div class="assertion-icon">{"✅" if exp["passed"] else "❌"}</div>
              <div class="assertion-text">
                <div class="text">{esc(exp['text'])}{precision_badge}{method_tag}{esource_tag}</div>
                {evidence_html}
              </div>
            </div>"""

        # without_skill 断言（折叠）
        wos_assertions_html = ""
        if ev["wos_g"]:
            for exp in ev["wos_g"].get("expectations", []):
                ecls = "pass" if exp["passed"] else "fail"
                wos_assertions_html += f"""
              <div class="assertion {ecls}" style="font-size:12px">
                <div class="assertion-icon">{"✅" if exp["passed"] else "❌"}</div>
                <div class="assertion-text">
                  <div class="text">{esc(exp['text'])}</div>
                </div>
              </div>"""

        expanded = "expanded" if i == 0 else ""
        eval_id = ev['id']
        eval_cards_html += f"""
      <div class="eval-card {expanded}" id="eval-card-{eval_id}">
        <div class="eval-card-header">
          <div class="eval-badge {badge_cls}">{eval_id}</div>
          <div class="eval-title">
            <strong>{esc(ev['name'])}</strong>
            <span>
              <span class="type-tag" style="background:{tc}20;color:{tc}">{tl}</span>
              {ev['ws_p']}/{ev['ws_t']} 断言
              {f'· <span style="color:#d97757;font-size:11px">{len(mcp_calls)} MCP调用</span>' if mcp_calls else ''}
              {f'· <span style="color:#c44;font-size:11px">⚠ {sum(1 for e in (ev["ws_g"] or {}).get("expectations",[]) if not e.get("evidence",""))}</span>' if any(not e.get("evidence","") for e in (ev["ws_g"] or {}).get("expectations",[])) else ''}
            </span>
          </div>
          <div style="text-align:right;flex-shrink:0">
            <div class="eval-pass-rate {rate_cls}">{int(ws_r*100)}%</div>
            <div style="font-size:11px;color:{delta_col}">vs无Skill: {delta_str}</div>
          </div>
          <div class="eval-expand">▼</div>
        </div>
        <div class="eval-card-body">
          <div class="prompt-box">{esc(ev.get('prompt',''))}</div>

          {metrics_html}

          <div style="font-size:12px;font-weight:600;color:#b0aea5;text-transform:uppercase;letter-spacing:.04em;margin:12px 0 6px">
            Layer2b Grader 断言结果
          </div>
          <div class="assertions">{assertions_html}</div>

          {gt_html}
          {mcp_html}
          {claims_html}
          {ef_html}

          <div class="wos-toggle" onclick="toggleWos({eval_id})">
            <span class="wos-arrow" id="wos-arrow-{eval_id}">▶</span>
            无Skill基线结果 ({int(ev['wos_rate']*100)}% · {ev['wos_p']}/{ev['wos_t']})
          </div>
          <div class="wos-body" id="wos-body-{eval_id}" style="display:none">
            <div class="assertions" style="margin-top:6px">{wos_assertions_html}</div>
          </div>

          <div class="feedback-area">
            <div style="font-size:12px;font-weight:600;color:#b0aea5;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px">
              人工反馈（可选）
            </div>
            <textarea class="feedback-input" id="fb-{eval_id}"
              placeholder="这个用例的执行结果是否符合预期？有什么问题或建议？"
              onchange="saveFeedback({eval_id}, this.value)"
            ></textarea>
            <div class="feedback-status" id="fb-status-{eval_id}"></div>
          </div>
        </div>
      </div>"""

    # ── 跨 iteration 对比 ─────────────────────────────────────────────────
    iter_compare_html = ""
    if other_iterations:
        rows = ""
        for it in other_iterations:
            rate = it["pass_rate"]
            color = "#788c5d" if rate >= 0.95 else ("#d97757" if rate >= 0.5 else "#c44")
            delta_vs_current = rate - overall_ws
            dc = "#788c5d" if delta_vs_current > 0 else "#c44"
            ds = f"+{delta_vs_current:.0%}" if delta_vs_current > 0 else f"{delta_vs_current:.0%}"
            rows += f"""<tr>
              <td>{esc(it['name'])}</td>
              <td style="color:{color};font-weight:600">{int(rate*100)}%</td>
              <td>{it['passed']}/{it['total']}</td>
              <td style="color:{dc};font-weight:600">{ds}</td>
            </tr>"""
        rows += f"""<tr style="font-weight:700;background:#f3f1ea">
              <td>{esc(current_iter_name)} (本次)</td>
              <td style="color:#788c5d">{int(overall_ws*100)}%</td>
              <td>{total_ws_p}/{total_ws_t}</td>
              <td>—</td>
            </tr>"""
        iter_compare_html = f"""
<div class="section">
  <div class="section-title">🔄 历史 Iteration 对比</div>
  <div class="chart-container">
    <table class="criteria-table">
      <thead><tr><th>Iteration</th><th>通过率</th><th>断言通过</th><th>vs 本次</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""

    # ── Benchmark Tab ─────────────────────────────────────────────────────
    bm_rows_html, has_benchmark = render_benchmark_tab(evals)

    # ── Limitation section ────────────────────────────────────────────────
    # eval_environment.json 查找顺序：
    # 1. workspace_dir/../eval_environment.json  (iteration-N 的上级 session 目录)
    # 2. workspace_dir/../../eval_environment.json (eval-workspace/sessions/date_NNN/iteration-N)
    # 3. workspace_dir/eval_environment.json (兜底)
    env_config = (
        load_json(os.path.join(ws_dir, "..", "eval_environment.json")) or
        load_json(os.path.join(ws_dir, "..", "..", "eval_environment.json")) or
        load_json(os.path.join(ws_dir, "eval_environment.json"))
    )
    env_data = (env_config or {}).get("eval_environment") or (env_config or {})

    # 从 execution_mode 字段判断，fallback 到旧的关键词检测
    execution_mode = env_data.get("execution_mode", "")
    skill_type = env_data.get("skill_type", "")  # 新增：从 eval_environment.json 读取 skill_type
    if not execution_mode:
        # 兼容旧版：通过 notes 或 skill 名称猜测
        note = str(env_data.get("notes", ""))
        is_invoice = any(kw in skill_name.lower()
                         for kw in ["reimbursement", "invoice", "expense", "报销", "发票"])
        if "模拟" in note or "simulate" in note.lower() or is_invoice:
            execution_mode = "simulated"
        else:
            execution_mode = "real"

    is_simulated = (execution_mode == "simulated")
    is_text_generation = (skill_type == "text_generation" or execution_mode == "text")

    # 收集 unavailable_tools 字段（预检阶段记录的不可用工具列表）
    unavailable_tools = env_data.get("unavailable_tools", [])

    limitation_html = ""
    if is_simulated:
        tools_list = ""
        if unavailable_tools:
            tools_list = "<ul style='margin:8px 0 0 18px'>" + \
                "".join(f"<li><code>{esc(t)}</code></li>" for t in unavailable_tools) + \
                "</ul>"
        else:
            tools_list = "<p style='margin-top:6px;color:#78350f'>（未记录具体工具，请查看 eval_environment.json）</p>"

        limitation_html = f"""
<div class="section">
  <div class="section-title">⚠️ 测评局限性</div>
  <div class="chart-container">
    <div style="background:#fff3e0;border:1px solid #d97757;border-radius:8px;padding:16px 18px;margin-bottom:16px">
      <div style="font-weight:600;color:#7a3a00;margin-bottom:8px;font-size:14px;display:flex;align-items:center;gap:8px">
        <span style="background:#d97757;color:white;font-size:11px;padding:2px 8px;border-radius:10px;font-family:Poppins,sans-serif">规则推断模式</span>
        MCP 工具不可用，结论仅反映规则逻辑自洽性
      </div>
      <div style="font-size:13px;color:#7a3a00;line-height:1.7">
        测评执行时以下 MCP 工具无法调用，with_skill 断言结果为基于 Skill 规则文档的逻辑推断，
        <strong>不代表真实运行质量</strong>：{tools_list}
        <div style="margin-top:12px;padding:10px 14px;background:rgba(217,119,87,.1);border-radius:6px">
          <div style="font-weight:600;margin-bottom:6px">修复步骤：</div>
          <ol style="margin-left:16px;font-size:12px;line-height:1.8">
            <li>确认 MCP Server 已在 <code>opencode.json</code> 中配置且 <code>enabled: true</code></li>
            <li>确认网络可达（curl 测试端点返回非超时）</li>
            <li>确认账号有权限调用该 MCP Server</li>
            <li>修复后重新开始测评（创建新 iteration），真实执行结果才有发布参考价值</li>
          </ol>
        </div>
      </div>
    </div>
  </div>
</div>"""
    elif is_text_generation:
        limitation_html = f"""
<div class="section">
  <div class="section-title">ℹ️ 纯文本模式说明</div>
  <div class="chart-container">
    <div style="background:#ebf8ff;border:1px solid #90cdf4;border-radius:8px;padding:16px 18px">
      <div style="font-weight:600;color:#2b6cb0;margin-bottom:8px;font-size:14px;display:flex;align-items:center;gap:8px">
        <span style="background:#3b82f6;color:white;font-size:11px;padding:2px 8px;border-radius:10px;font-family:Poppins,sans-serif">纯文本生成型 Skill</span>
        断言验证基于输出文本内容，无 MCP 工具调用链路
      </div>
      <div style="font-size:13px;color:#2c5282;line-height:1.7">
        该 Skill 为纯文本生成型，测评通过对比 response.md 输出内容验证断言。
        以下能力<strong>不在本次测评范围内</strong>：
        <ul style="margin:8px 0 0 18px">
          <li>系统集成与外部接口调用</li>
          <li>MCP 工具调用链路验证</li>
          <li>文件上传/下载等 I/O 操作</li>
        </ul>
      </div>
    </div>
  </div>
</div>"""

    # ── 触发率预评估（读取 trigger_eval.json）────────────────────────────────
    trigger_eval = (
        load_json(os.path.join(ws_dir, "..", "trigger_eval.json")) or
        load_json(os.path.join(ws_dir, "trigger_eval.json"))
    )
    trigger_html = _render_trigger_eval(trigger_eval)

    # ── 效率指标汇总（从各用例 timing.json 聚合）──────────────────────────────
    efficiency_html = _render_efficiency_section(evals, ws_dir, crit)

    # ── Decision text ─────────────────────────────────────────────────────
    mode_warning = ""
    if is_simulated:
        mode_warning = " ⚠️【规则推断模式，非真实执行，结论仅供参考】"
    elif is_text_generation:
        mode_warning = " ℹ️【纯文本模式，无 MCP 调用链路验证】"
    decision_reason = {
        "PASS": f"with_skill 通过率 {int(overall_ws*100)}%，超出 {RISK_LABEL[risk_level]} 准入阈值（≥{int(crit['pass_rate']*100)}%），无负向增益，灾难场景全部通过。{mode_warning}",
        "CONDITIONAL PASS": f"with_skill 通过率 {int(overall_ws*100)}%，达到准入阈值 {int(crit['pass_rate']*100)}%，但灾难场景未执行，建议升级至 full 模式后再作正式发布决策。{mode_warning}",
        "FAIL": f"with_skill 通过率 {int(overall_ws*100)}%，未达到 {RISK_LABEL[risk_level]} 准入阈值（≥{int(crit['pass_rate']*100)}%），请修复后重新测评。{mode_warning}",
    }.get(decision, "")

    # ── Full HTML ─────────────────────────────────────────────────────────
    benchmark_tab_btn = '<button class="view-tab" onclick="switchTab(\'benchmark\')">Benchmark</button>' if has_benchmark else ""
    benchmark_panel = f"""
    <div class="view-panel" id="panel-benchmark">
      <div class="bm-container">
        <h3 style="font-family:Poppins,sans-serif;margin-bottom:1rem">逐用例 Benchmark（多次运行矩阵）</h3>
        {bm_rows_html}
      </div>
    </div>""" if has_benchmark else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(skill_name)} 测评报告</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Lora:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #faf9f5;
    --surface: #ffffff;
    --border: #e8e6dc;
    --text: #141413;
    --text-muted: #b0aea5;
    --accent: #d97757;
    --accent-hover: #c4613f;
    --green: #788c5d;
    --green-bg: #eef2e8;
    --red: #c44;
    --red-bg: #fceaea;
    --warn: #d97757;
    --warn-bg: #fef3e8;
    --header-bg: #141413;
    --header-text: #faf9f5;
    --radius: 8px;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ font-family:'Lora',Georgia,serif; background:var(--bg); color:var(--text) }}

  /* Header */
  .header {{ background:var(--header-bg); color:var(--header-text); padding:28px 40px }}
  .header h1 {{ font-family:Poppins,sans-serif; font-size:22px; font-weight:700; margin-bottom:6px }}
  .header .subtitle {{ font-size:12px; opacity:.6; margin-bottom:14px }}
  .header-meta {{ display:flex; gap:8px; flex-wrap:wrap }}
  .header-meta span {{ font-size:11px; opacity:.85; background:rgba(255,255,255,.12); padding:3px 10px; border-radius:20px }}

  /* View tabs */
  .view-tabs {{ display:flex; gap:0; padding:0 40px; background:var(--surface); border-bottom:1px solid var(--border) }}
  .view-tab {{ font-family:Poppins,sans-serif; padding:10px 20px; font-size:13px; font-weight:500; cursor:pointer;
    border:none; background:none; color:var(--text-muted); border-bottom:2px solid transparent; transition:all .15s }}
  .view-tab:hover {{ color:var(--text) }}
  .view-tab.active {{ color:var(--accent); border-bottom-color:var(--accent) }}
  .view-panel {{ display:none }}
  .view-panel.active {{ display:block }}

  /* Main */
  .main {{ max-width:1200px; margin:0 auto; padding:28px 20px }}

  /* Decision banner */
  .decision-banner {{ background:{decision_color}; border-radius:12px; padding:24px 32px; text-align:center; margin-bottom:28px }}
  .decision-banner .verdict {{ font-family:Poppins,sans-serif; font-size:36px; font-weight:800;
    letter-spacing:2px; color:{decision_text_color} }}
  .decision-banner .reason {{ font-size:13px; opacity:.9; margin-top:8px; color:white; line-height:1.6 }}

  /* Summary grid */
  .summary-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:28px }}
  .summary-card {{ background:var(--surface); border-radius:var(--radius); padding:16px 18px;
    box-shadow:0 1px 4px rgba(0,0,0,.07); border-left:4px solid var(--border) }}
  .summary-card.green {{ border-left-color:var(--green) }}
  .summary-card.blue  {{ border-left-color:#3b82f6 }}
  .summary-card.orange{{ border-left-color:var(--accent) }}
  .summary-card.purple{{ border-left-color:#8b5cf6 }}
  .summary-card .label {{ font-family:Poppins,sans-serif; font-size:10px; color:var(--text-muted);
    text-transform:uppercase; letter-spacing:.5px; margin-bottom:6px }}
  .summary-card .value {{ font-family:Poppins,sans-serif; font-size:28px; font-weight:700; color:var(--text); line-height:1 }}
  .summary-card .desc  {{ font-size:11px; color:var(--text-muted); margin-top:4px }}

  /* Sections */
  .section {{ margin-bottom:28px }}
  .section-title {{ font-family:Poppins,sans-serif; font-size:15px; font-weight:600; color:var(--text);
    margin-bottom:12px; padding-bottom:6px; border-bottom:2px solid var(--border) }}
  .chart-container {{ background:var(--surface); border-radius:var(--radius); padding:20px;
    box-shadow:0 1px 4px rgba(0,0,0,.07); border:1px solid var(--border) }}

  /* Bar chart */
  .bar-item {{ display:flex; align-items:center; margin-bottom:10px; gap:10px }}
  .bar-label {{ width:280px; font-size:12px; color:#374151; flex-shrink:0; display:flex; align-items:center; gap:5px }}
  .bar-track {{ flex:1; background:#e8e6dc; border-radius:4px; height:20px; overflow:hidden }}
  .bar-fill {{ height:100%; border-radius:4px; display:flex; align-items:center; padding-left:6px }}
  .bar-fill.pass    {{ background:linear-gradient(90deg,#788c5d,#9aae7a) }}
  .bar-fill.partial {{ background:linear-gradient(90deg,#d97757,#e89570) }}
  .bar-fill.fail    {{ background:linear-gradient(90deg,#c44,#e06666) }}
  .bar-pct {{ font-size:11px; font-weight:600; color:white; white-space:nowrap }}
  .bar-score {{ width:38px; font-size:12px; font-weight:700; text-align:right; flex-shrink:0 }}
  .bar-score.s10 {{ color:var(--green) }}
  .bar-score.s05 {{ color:var(--accent) }}
  .bar-score.s00 {{ color:var(--red) }}
  .type-dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; flex-shrink:0 }}
  .type-tag {{ display:inline-block; padding:1px 6px; border-radius:10px; font-size:11px; font-weight:600; margin-right:3px }}

  /* Two-col */
  .two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:18px }}
  @media(max-width:768px) {{ .two-col {{ grid-template-columns:1fr }} }}

  /* Criteria table */
  .criteria-table {{ width:100%; border-collapse:collapse; font-size:13px }}
  .criteria-table th {{ text-align:left; padding:7px 10px; background:var(--bg); color:var(--text-muted);
    font-family:Poppins,sans-serif; font-size:10px; text-transform:uppercase; font-weight:600 }}
  .criteria-table td {{ padding:8px 10px; border-bottom:1px solid var(--border) }}
  .criteria-table tr:hover td {{ background:var(--bg) }}
  .badge {{ display:inline-block; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600 }}
  .badge.pass {{ background:var(--green-bg); color:var(--green) }}
  .badge.fail {{ background:var(--red-bg);   color:var(--red) }}
  .badge.warn {{ background:var(--warn-bg);  color:var(--warn) }}

  /* Eval cards */
  .eval-grid {{ display:flex; flex-direction:column; gap:10px }}
  .eval-card {{ background:var(--surface); border-radius:var(--radius);
    box-shadow:0 1px 4px rgba(0,0,0,.07); border:1px solid var(--border); overflow:hidden }}
  .eval-card-header {{ padding:12px 16px; display:flex; align-items:center; gap:10px;
    cursor:pointer; user-select:none }}
  .eval-card-header:hover {{ background:var(--bg) }}
  .eval-badge {{ width:26px; height:26px; border-radius:6px; display:flex; align-items:center;
    justify-content:center; font-family:Poppins,sans-serif; font-size:11px; font-weight:700; flex-shrink:0 }}
  .eval-badge.pass    {{ background:var(--green-bg); color:var(--green) }}
  .eval-badge.partial {{ background:var(--warn-bg);  color:var(--warn) }}
  .eval-badge.fail    {{ background:var(--red-bg);   color:var(--red) }}
  .eval-title {{ flex:1 }}
  .eval-title strong {{ font-size:13px; color:var(--text); display:block; margin-bottom:2px }}
  .eval-title span   {{ font-size:12px; color:var(--text-muted) }}
  .eval-pass-rate {{ font-family:Poppins,sans-serif; font-size:18px; font-weight:700 }}
  .eval-pass-rate.s10 {{ color:var(--green) }}
  .eval-pass-rate.s05 {{ color:var(--accent) }}
  .eval-pass-rate.s00 {{ color:var(--red) }}
  .eval-expand {{ color:var(--text-muted); font-size:11px; flex-shrink:0; transition:transform .2s; margin-left:6px }}
  .eval-card.expanded .eval-expand {{ transform:rotate(180deg) }}
  .eval-card-body {{ display:none; padding:0 16px 16px; border-top:1px solid var(--border) }}
  .eval-card.expanded .eval-card-body {{ display:block }}
  .prompt-box {{ background:var(--bg); border-radius:6px; padding:9px 13px; font-size:12px;
    color:#475569; margin:12px 0; border-left:3px solid var(--border);
    font-family:'SF Mono',Menlo,monospace; white-space:pre-wrap; word-break:break-word }}

  /* Assertions */
  .assertions {{ display:flex; flex-direction:column; gap:4px; margin-top:6px }}
  .assertion {{ display:flex; gap:8px; padding:7px 10px; border-radius:6px; align-items:flex-start }}
  .assertion.pass {{ background:var(--green-bg) }}
  .assertion.fail {{ background:var(--red-bg) }}
  .assertion-icon {{ font-size:13px; flex-shrink:0; margin-top:1px }}
  .assertion-text .text {{ font-size:13px; font-weight:500; color:var(--text); margin-bottom:2px }}
  .assertion-text .evidence {{ font-size:12px; color:var(--text-muted); line-height:1.4 }}

  /* MCP call chain */
  .mcp-chain {{ margin:14px 0; border:1px solid var(--border); border-radius:6px; overflow:hidden }}
  .mcp-header {{ background:var(--bg); padding:8px 12px; font-family:Poppins,sans-serif;
    font-size:12px; font-weight:600; color:var(--text); border-bottom:1px solid var(--border);
    display:flex; align-items:center; gap:8px }}
  .mcp-summary {{ font-weight:400; color:var(--text-muted); font-size:11px }}
  .mcp-body {{ padding:8px 12px; display:flex; flex-direction:column; gap:6px }}
  .mcp-row {{ display:grid; grid-template-columns:22px 180px 18px 50px 1fr; align-items:start; gap:6px; font-size:12px }}
  .mcp-step {{ color:var(--text-muted); font-family:Poppins,sans-serif; font-size:11px; padding-top:1px }}
  .mcp-name {{ font-family:'SF Mono',Menlo,monospace; font-size:12px; color:#1a1a2e; font-weight:600 }}
  .mcp-dur  {{ color:var(--text-muted); font-size:11px; padding-top:1px }}
  .mcp-detail {{ display:flex; flex-direction:column; gap:2px }}
  .mcp-result {{ color:#475569; font-family:'SF Mono',Menlo,monospace; font-size:11px;
    background:var(--bg); padding:2px 6px; border-radius:3px }}
  .mcp-note {{ color:var(--text-muted); font-size:11px; font-style:italic }}
  .mcp-fallback {{ color:var(--accent); font-size:11px }}

  /* without_skill toggle */
  .wos-toggle {{ display:flex; align-items:center; gap:6px; margin-top:14px; cursor:pointer;
    font-family:Poppins,sans-serif; font-size:12px; font-weight:500; color:var(--text-muted);
    user-select:none; padding:6px 0; border-top:1px dashed var(--border) }}
  .wos-toggle:hover {{ color:var(--text) }}
  .wos-arrow {{ font-size:10px; transition:transform .15s }}
  .wos-arrow.open {{ transform:rotate(90deg) }}
  .wos-body {{ padding-left:8px }}

  /* Feedback area */
  .feedback-area {{ margin-top:14px; padding-top:12px; border-top:1px dashed var(--border) }}
  .feedback-input {{ width:100%; min-height:72px; padding:8px 10px; border:1px solid var(--border);
    border-radius:6px; font-family:'Lora',Georgia,serif; font-size:13px; resize:vertical;
    color:var(--text); background:var(--bg) }}
  .feedback-input:focus {{ outline:none; border-color:var(--accent);
    box-shadow:0 0 0 2px rgba(217,119,87,.15) }}
  .feedback-status {{ font-size:11px; color:var(--text-muted); margin-top:4px; min-height:1em }}

  /* Disaster cards */
  .disaster-grid {{ display:flex; flex-direction:column; gap:8px }}
  .disaster-card {{ background:var(--surface); border-radius:8px; padding:14px 16px;
    border-left:4px solid var(--green) }}
  .disaster-card.fail {{ border-left-color:var(--red) }}

  /* Benchmark */
  .bm-container {{ max-width:1200px; margin:0 auto; padding:24px 20px }}
  .bm-eval {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius);
    margin-bottom:16px; overflow:hidden }}
  .bm-eval-header {{ display:flex; align-items:center; gap:12px; padding:12px 16px;
    background:var(--bg); border-bottom:1px solid var(--border) }}
  .bm-id {{ font-family:Poppins,sans-serif; font-size:11px; color:var(--text-muted) }}
  .bm-name {{ font-family:Poppins,sans-serif; font-size:13px; font-weight:600; flex:1 }}
  .bm-rate {{ font-family:Poppins,sans-serif; font-size:14px; font-weight:700; color:var(--green) }}
  .bm-std {{ font-size:11px; font-weight:400 }}
  .bm-std.warn {{ color:var(--red) }}
  .bm-delta {{ font-family:Poppins,sans-serif; font-size:13px; font-weight:600 }}
  .bm-matrix {{ padding:12px 16px; overflow-x:auto }}
  .bm-matrix table {{ border-collapse:collapse; font-size:12px; width:100% }}
  .bm-matrix th {{ background:var(--header-bg); color:var(--header-text); padding:6px 10px;
    font-family:Poppins,sans-serif; font-size:11px; text-align:center }}
  .bm-matrix td {{ padding:6px 10px; border-bottom:1px solid var(--border) }}
  .bm-matrix td.at {{ max-width:400px; color:var(--text); font-size:12px }}
  .bm-matrix td.mp {{ text-align:center; color:var(--green); font-weight:700 }}
  .bm-matrix td.mf {{ text-align:center; color:var(--red); font-weight:700 }}

  .note-banner {{ background:#fffbeb; border:1px solid #f0d060; border-radius:8px;
    padding:12px 16px; font-size:13px; color:#92400e; margin-bottom:18px }}
  .footer {{ text-align:center; padding:20px; color:var(--text-muted); font-size:11px; margin-top:12px }}
</style>
</head>
<body>

<div class="header">
  <h1>🧾 {esc(skill_name)} 测评报告</h1>
  <div class="subtitle">skill-eval-master · 系统性多维度测评</div>
  <div class="header-meta">
    <span>📅 {datetime.now().strftime('%Y-%m-%d')}</span>
    <span>⚠️ {RISK_LABEL.get(risk_level, risk_level)}</span>
    {"<span>👤 " + esc(user) + "</span>" if user else ""}
    <span>📊 {len(evals)} 个用例 + {len(disaster)} 个灾难场景</span>
    <span>🔖 {esc(current_iter_name)}</span>
  </div>
</div>

<!-- View Tabs -->
<div class="view-tabs">
  <button class="view-tab active" onclick="switchTab('report')">测评报告</button>
  {benchmark_tab_btn}
</div>

<!-- Report Panel -->
<div class="view-panel active" id="panel-report">
<div class="main">

<div class="decision-banner">
  <div class="verdict">{decision_icon} {esc(decision)}</div>
  <div class="reason">{esc(decision_reason)}</div>
</div>

<div class="summary-grid">
  <div class="summary-card {"green" if authoritative_rate >= crit["pass_rate"] else "orange"}">
    <div class="label">{"精确断言通过率 ★" if has_precision_data else "WITH_SKILL 通过率"}</div>
    <div class="value">{int(authoritative_rate*100)}%</div>
    <div class="desc">{"准入判断依据 · 综合" + str(int(overall_ws*100)) + "%" if has_precision_data else str(total_ws_p) + "/" + str(total_ws_t) + " 断言通过"}</div>
  </div>
  <div class="summary-card blue">
    <div class="label">vs 基线增益 Δ</div>
    <div class="value">{overall_delta:+.0%}</div>
    <div class="desc">without_skill: {int(overall_wos*100)}%</div>
  </div>
  <div class="summary-card {"green" if disaster_pass else "orange"}">
    <div class="label">灾难场景红线</div>
    <div class="value">{sum(1 for d in disaster if d["passed"])}/{len(disaster)}</div>
    <div class="desc">{"全部通过" if disaster_pass and len(disaster) > 0 else ("有失败项" if not disaster_pass else "未执行")}</div>
  </div>
  <div class="summary-card {"green" if not neg_delta else "orange"}">
    <div class="label">负向增益用例</div>
    <div class="value">{len(neg_delta)}</div>
    <div class="desc">{"无" if not neg_delta else "需修复后才可上线"}</div>
  </div>
  <div class="summary-card purple">
    <div class="label">测试用例总数</div>
    <div class="value">{len(evals)}</div>
    <div class="desc">{len(type_stats)} 种用例类型</div>
  </div>
  <div class="summary-card orange">
    <div class="label">准入阈值</div>
    <div class="value">≥{int(crit["pass_rate"]*100)}%</div>
    <div class="desc">{RISK_LABEL.get(risk_level, risk_level)}</div>
  </div>
</div>

{f'''<div style="margin:0 0 20px;padding:12px 18px;background:#fff3e0;border:1px solid #d97757;border-radius:8px;
  display:flex;align-items:center;gap:10px">
  <span style="font-size:18px">⚠️</span>
  <div>
    <div style="font-weight:700;color:#7a3a00;font-size:13px">结果不稳定警告（quick 模式）</div>
    <div style="font-size:12px;color:#7a3a00;margin-top:2px">
      两次运行通过率差距 {run_stability["gap_pct"]}（run1: {int(run_stability["run1"]*100)}%，run2: {int(run_stability["run2"]*100)}%）。
      建议升级到 standard 模式（3次运行）以获得可信结论。
    </div>
  </div>
</div>''' if run_stability and run_stability.get("unstable") else ""}

{precision_summary_html}

<div class="section">
  <div class="section-title">📈 各场景通过率（with_skill vs without_skill Δ）</div>
  <div class="chart-container">{bars_html}</div>
</div>

<div class="section">
  <div class="two-col">
    <div>
      <div class="section-title">📊 按用例类型统计</div>
      <div class="chart-container">{type_stats_html}</div>
    </div>
    <div>
      <div class="section-title">🎯 准入指标达成</div>
      <div class="chart-container">
        <table class="criteria-table">
          <thead><tr><th>指标</th><th>标准</th><th>实际</th><th>状态</th></tr></thead>
          <tbody>{criteria_rows_html}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

{iter_compare_html}

{"<div class='note-banner'>⚠️ <strong>测评说明</strong>：MCP 工具调用为规则符合性分析模式（mcporter 不可用），建议在真实接口环境下补充集成测试。</div>" if evals else ""}

{"<div class='section'><div class='section-title'>🔴 灾难场景红线测试（一票否决）</div><div class='disaster-grid'>" + disaster_html + "</div></div>" if disaster else ""}

<div class="section">
  <div class="section-title">📋 详细测评结果（点击展开 / 收起）</div>
  <div class="eval-grid">{eval_cards_html}</div>
</div>

{limitation_html}

{trigger_html}

{efficiency_html}

</div>
</div><!-- end panel-report -->

{benchmark_panel}

<div class="footer">
  skill-eval-master · {esc(skill_name)} · {datetime.now().strftime('%Y-%m-%d')} · {RISK_LABEL.get(risk_level, risk_level)}
</div>

<script>
// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(tab) {{
  document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('[onclick="switchTab(\\''+tab+'\\')"]').classList.add('active');
  const panel = document.getElementById('panel-' + tab);
  if (panel) panel.classList.add('active');
}}

// ── Eval card expand/collapse ─────────────────────────────────────────────
document.querySelectorAll('.eval-card-header').forEach(h => {{
  h.addEventListener('click', () => h.parentElement.classList.toggle('expanded'));
}});

// ── without_skill toggle ──────────────────────────────────────────────────
function toggleWos(id) {{
  const body = document.getElementById('wos-body-' + id);
  const arrow = document.getElementById('wos-arrow-' + id);
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : 'block';
  arrow.classList.toggle('open', !isOpen);
}}

// ── Feedback auto-save ─────────────────────────────────────────────────────
const feedbackMap = {{}};
function saveFeedback(id, value) {{
  feedbackMap[id] = value;
  const status = document.getElementById('fb-status-' + id);
  if (status) status.textContent = value.trim() ? '已记录' : '';
  // 尝试保存到 feedback.json（需要本地服务器支持）
  const reviews = Object.entries(feedbackMap)
    .filter(([k, v]) => v.trim())
    .map(([k, v]) => ({{ eval_id: k, feedback: v, timestamp: new Date().toISOString() }}));
  fetch('/api/feedback', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ reviews }})
  }}).catch(() => {{
    if (status) status.textContent = '（静态模式，反馈将在导出时保存）';
  }});
}}

// ── Export feedback ────────────────────────────────────────────────────────
function exportFeedback() {{
  const reviews = Object.entries(feedbackMap)
    .filter(([k, v]) => v.trim())
    .map(([k, v]) => ({{ eval_id: k, feedback: v, timestamp: new Date().toISOString() }}));
  if (!reviews.length) {{ alert('暂无反馈内容'); return; }}
  const blob = new Blob([JSON.stringify({{ reviews }}, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'feedback.json';
  a.click();
}}

// ── Keyboard navigation ────────────────────────────────────────────────────
document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowDown') {{
    const cards = document.querySelectorAll('.eval-card.expanded');
    if (cards.length) {{
      const next = cards[0].nextElementSibling;
      if (next && next.classList.contains('eval-card')) {{
        cards[0].classList.remove('expanded');
        next.classList.add('expanded');
        next.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }}
  }}
  if (e.key === 'ArrowUp') {{
    const cards = document.querySelectorAll('.eval-card.expanded');
    if (cards.length) {{
      const prev = cards[0].previousElementSibling;
      if (prev && prev.classList.contains('eval-card')) {{
        cards[0].classList.remove('expanded');
        prev.classList.add('expanded');
        prev.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
      }}
    }}
  }}
}});
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML report written: {output_path}  ({len(html):,} chars)")


def main():
    parser = argparse.ArgumentParser(description="Generate HTML eval report v2.0")
    parser.add_argument("workspace_dir")
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--risk-level", choices=["S","A","B","C"], default="B")
    parser.add_argument("--user", default="")
    parser.add_argument("--output")
    args = parser.parse_args()

    if not os.path.isdir(args.workspace_dir):
        print(f"Error: not a directory: {args.workspace_dir}")
        sys.exit(1)

    out = args.output or os.path.join(args.workspace_dir, "eval-report.html")
    build_report(args.workspace_dir, args.skill_name, args.risk_level, args.user, out)


if __name__ == "__main__":
    main()
