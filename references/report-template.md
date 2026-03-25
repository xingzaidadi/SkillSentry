# 测评报告模板

测评完成后，使用本模板生成最终报告。报告的读者是**做上线决策的产品/研发负责人**，所以语言要清晰、结论要明确、数据要完整。

---

## 报告章节结构（固定顺序，不得增删）

```
📖 名词速查（固定开头，帮助不熟悉术语的读者）
一、执行摘要（3-5句，能不能上线+主要理由）
二、关键指标卡 + 发布准入达成表
三、真实 MCP 接口调用记录（正常路径用例，可展开入参/返回）[mcp_based 专有，text_generation 跳过]
四、各用例执行情况（所有用例逐条，可展开断言/with vs without/MCP调用统计）
五、发现的问题（P0/P1/P2分级）
六、测评覆盖率（路径/规则/断言，含未覆盖规则列表）
七、Benchmark 数据（with vs without 通过率/调用次数对比）
八、改进建议（P0/P1/P2优先级表格）
九、Skill 复杂度评估
十、测评环境
十一、触发率预评估（AI 模拟）[新增，所有 Skill 类型必须包含]
十二、效率指标汇总 [新增，timing.json 有数据时包含，无数据则标注 N/A]
```

---

## 报告生成注意事项

1. **名词速查是固定开头**——帮助不熟悉术语的读者理解报告，每次生成都必须包含。
2. **执行摘要是最重要的部分**——决策者可能只看这段话，用最直白的语言说明「能不能上线」和「为什么」。
3. **发布决策必须明确**——PASS、CONDITIONAL PASS 或 FAIL，不能模棱两可。
4. **所有数据必须有出处**——每个数字都要能追溯到具体的测试用例和 grading 结果。
5. **MCP 调用明细必须输出**（仅 mcp_based Skill）——来自 transcript 的真实调用记录，每条工具调用一个可展开 `<details>`，含入参+返回+状态。
6. **各用例必须逐条展示**——每个用例必须有可展开的 `<details>`，含断言列表（带 evidence）+ mcp-table（mcp_based）或 response 摘要（text_generation）+ with/without 对比。
7. **rule-tag 必须带中文描述**——不能只写 `R-06`，必须写 `<span class="rule-tag"><span class="rule-id">R-06</span> 住宿发票检测</span>`。
8. **INCONCLUSIVE 用例**：class 用 `eval-warn`，底部必须加 `detail-warn` 块说明原因和补充方式。
9. **灾难场景单独列**——它是一票否决的红线，不能埋在正常测试结果里（full 模式才有）。
10. **text_generation Skill 跳过第三章**——纯文本 Skill 没有 MCP 调用记录，第三章替换为：`<p style="color:#888;">⚠ 纯文本生成型 Skill，无 MCP 接口调用记录。</p>`
11. **触发率章节（第十一章）必须包含**——即使置信度为 low，也要如实呈现，并附 AI 模拟免责声明。
12. **效率指标章节（第十二章）**——timing.json 数据存在时展示；全部缺失时保留章节标题，正文注明「⚠ 本次测评未采集 timing 数据」。

---

## HTML 报告规范

**生成报告时必须使用以下 HTML 模板，CSS 样式和 section 结构不得自行更改。** 只需要填充 `[PLACEHOLDER]` 标注的位置。

### 完整 HTML 模板

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>[SKILL_NAME] 测评报告</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif; background: #f5f6fa; color: #2c3e50; line-height: 1.6; }
  .container { max-width: 1100px; margin: 0 auto; padding: 32px 24px; }
  .report-header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; padding: 40px; border-radius: 16px; margin-bottom: 32px; }
  .report-header h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
  .report-header .subtitle { opacity: 0.7; font-size: 14px; margin-bottom: 20px; }
  .report-header .meta-row { display: flex; gap: 28px; flex-wrap: wrap; }
  .report-header .meta-item .label { opacity: 0.6; display: block; font-size: 11px; }
  .report-header .meta-item .value { font-weight: 600; font-size: 14px; }
  .decision-banner { padding: 24px 32px; border-radius: 12px; margin-bottom: 32px; display: flex; align-items: flex-start; gap: 20px; }
  .decision-banner.conditional { background: linear-gradient(135deg, #fff8e6, #ffecc0); border: 2px solid #f0a500; }
  .decision-banner.pass        { background: linear-gradient(135deg, #f0fff4, #c6f6d5); border: 2px solid #38a169; }
  .decision-banner.fail        { background: linear-gradient(135deg, #fff5f5, #fed7d7); border: 2px solid #e53e3e; }
  .decision-icon { font-size: 40px; flex-shrink: 0; margin-top: 2px; }
  .decision-label { font-size: 22px; font-weight: 800; }
  .decision-banner.conditional .decision-label { color: #b07800; }
  .decision-banner.pass        .decision-label { color: #276749; }
  .decision-banner.fail        .decision-label { color: #9b2c2c; }
  .decision-desc { font-size: 14px; color: #555; margin-top: 8px; line-height: 1.8; }
  .card { background: white; border-radius: 12px; padding: 28px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
  .card h2 { font-size: 18px; font-weight: 700; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 2px solid #f0f2f5; color: #1a1a2e; }
  .card h3 { font-size: 15px; font-weight: 600; margin: 20px 0 12px; color: #333; }
  .summary-box { background: #f8f9ff; border-left: 4px solid #4361ee; padding: 16px 20px; border-radius: 0 8px 8px 0; font-size: 14px; line-height: 1.8; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { background: #f8f9fa; text-align: left; padding: 10px 14px; font-weight: 600; color: #555; border-bottom: 2px solid #e8eaf0; }
  td { padding: 10px 14px; border-bottom: 1px solid #f0f2f5; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fafbff; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; white-space: nowrap; }
  .badge-pass { background: #e6f9f0; color: #0d8c4a; }
  .badge-fail { background: #fce8e8; color: #c0392b; }
  .badge-warn { background: #fff5e6; color: #e07b00; }
  .badge-na   { background: #f0f2f5; color: #888; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .metric-card { background: #f8f9fa; border-radius: 10px; padding: 16px; text-align: center; }
  .metric-card .metric-value { font-size: 28px; font-weight: 800; color: #4361ee; }
  .metric-card .metric-value.green  { color: #0d8c4a; }
  .metric-card .metric-value.orange { color: #e07b00; }
  .metric-card .metric-value.red    { color: #c0392b; }
  .metric-card .metric-label { font-size: 12px; color: #888; margin-top: 4px; }
  /* ── MCP 接口调用区块 ── */
  .api-group { margin-bottom: 24px; }
  .api-group-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .api-group-title { font-size: 13px; font-weight: 700; color: #fff; padding: 5px 14px; border-radius: 6px; display: inline-block; }
  .api-group-title.daily  { background: #4361ee; }
  .api-group-title.travel { background: #e07b00; }
  .api-group-title.other  { background: #718096; }
  .api-group-desc { font-size: 12px; color: #888; }
  .api-call { border: 1px solid #eef0f8; border-radius: 8px; margin-bottom: 6px; overflow: hidden; }
  .api-call.ok   { border-left: 3px solid #0d8c4a; }
  .api-call.warn { border-left: 3px solid #e07b00; }
  .api-call.err  { border-left: 3px solid #c0392b; }
  .api-call-summary { display: flex; align-items: center; gap: 10px; padding: 9px 14px; cursor: pointer; list-style: none; user-select: none; background: #fafbff; }
  .api-call.err  .api-call-summary { background: #fff8f8; }
  .api-call.warn .api-call-summary { background: #fffdf0; }
  .api-call-summary::-webkit-details-marker { display: none; }
  .api-call-summary::before { content: "▶"; font-size: 9px; color: #ccc; transition: transform 0.15s; flex-shrink: 0; }
  details[open] > .api-call-summary::before { transform: rotate(90deg); }
  .api-call-name { font-size: 13px; font-weight: 600; color: #1a1a2e; font-family: "SF Mono","Fira Code",monospace; }
  .api-call-zh   { font-size: 12px; color: #888; flex: 1; margin-left: 6px; }
  .api-badge { display: inline-block; padding: 2px 9px; border-radius: 4px; font-size: 11px; font-weight: 700; white-space: nowrap; flex-shrink: 0; }
  .api-badge.ok   { background: #d1fae5; color: #065f46; }
  .api-badge.warn { background: #fef3c7; color: #92400e; }
  .api-badge.err  { background: #fee2e2; color: #991b1b; }
  .api-call-body { padding: 10px 14px 12px; border-top: 1px solid #f0f2f5; background: white; }
  .api-kv { display: grid; grid-template-columns: 80px 1fr; gap: 4px 12px; font-size: 12px; margin-bottom: 8px; }
  .api-kv-label { color: #aaa; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; padding-top: 1px; }
  .api-kv-value { font-family: "SF Mono","Fira Code",monospace; color: #334; line-height: 1.6; word-break: break-all; }
  .api-note { font-size: 11px; color: #e07b00; background: #fffdf0; border-radius: 4px; padding: 4px 8px; margin-top: 6px; }
  .api-note.info { color: #2b6cb0; background: #ebf8ff; }
  /* ── 各用例执行情况 ── */
  .eval-item { border-radius: 8px; margin-bottom: 8px; border: 1px solid #eef0f8; overflow: hidden; }
  .eval-item.eval-pass { border-color: #c3e6cb; }
  .eval-item.eval-warn { border-color: #ffeeba; }
  .eval-item.eval-fail { border-color: #f5c6cb; }
  .eval-summary { display: flex; align-items: center; gap: 10px; padding: 12px 16px; cursor: pointer; list-style: none; user-select: none; }
  .eval-item.eval-pass .eval-summary { background: #f6fff9; }
  .eval-item.eval-warn .eval-summary { background: #fffdf0; }
  .eval-item.eval-fail .eval-summary { background: #fff6f6; }
  .eval-summary::-webkit-details-marker { display: none; }
  .eval-summary::before { content: "▶"; font-size: 10px; color: #bbb; transition: transform 0.2s; flex-shrink: 0; }
  details[open] > .eval-summary::before { transform: rotate(90deg); }
  .eval-id   { font-size: 12px; color: #bbb; font-weight: 700; min-width: 26px; }
  .eval-name { font-size: 13px; font-weight: 500; flex: 1; }
  .eval-tag  { font-size: 11px; color: #999; background: #f0f2f5; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
  .delta     { font-size: 12px; font-weight: 700; min-width: 64px; text-align: right; white-space: nowrap; }
  .delta.pos { color: #0d8c4a; }
  .delta.neg { color: #c0392b; }
  .delta.neu { color: #bbb; }
  .eval-detail { padding: 16px 20px 20px; border-top: 1px solid #eef0f8; background: white; }
  .detail-section { margin-bottom: 12px; }
  .detail-section:last-child { margin-bottom: 0; }
  .detail-label { font-size: 11px; font-weight: 700; color: #aaa; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .detail-content { font-size: 13px; color: #444; line-height: 1.7; }
  .detail-warn .detail-label { color: #b07800; }
  .detail-warn .detail-content { color: #7a5000; background: #fffdf0; padding: 8px 12px; border-radius: 6px; }
  /* ── 用例内 MCP 调用明细表 ── */
  .mcp-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }
  .mcp-table th { background: #f0f2f5; padding: 6px 10px; text-align: left; font-weight: 600; color: #666; border-bottom: 1px solid #e0e2e8; }
  .mcp-table td { padding: 6px 10px; border-bottom: 1px solid #f0f2f5; vertical-align: top; }
  .mcp-table tr:last-child td { border-bottom: none; }
  .mcp-table tr.mcp-row-ok  td { background: #f8fffa; }
  .mcp-table tr.mcp-row-err td { background: #fff8f8; }
  .mcp-ok  { color: #0d8c4a; font-weight: 700; }
  .mcp-err { color: #c0392b; font-weight: 700; }
  /* ── 断言列表 ── */
  .assertion-list { list-style: none; margin-top: 6px; }
  .assertion-list li { display: flex; align-items: flex-start; gap: 8px; padding: 5px 0; border-bottom: 1px solid #f0f2f5; font-size: 12px; color: #444; }
  .assertion-list li:last-child { border-bottom: none; }
  .assert-pass { color: #0d8c4a; flex-shrink: 0; font-weight: 700; margin-top: 1px; }
  .assert-fail { color: #c0392b; flex-shrink: 0; font-weight: 700; margin-top: 1px; }
  .assert-body { flex: 1; }
  .assert-text { display: block; }
  .assert-evidence { font-size: 11px; color: #888; display: block; margin-top: 2px; font-family: "SF Mono","Fira Code",monospace; background: #f8f9fa; padding: 2px 6px; border-radius: 3px; border-left: 2px solid #e2e8f0; }
  /* ── Rule tags（带中文描述）── */
  .rule-tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px 2px 6px; background: #edf2f7; border-radius: 4px; font-size: 12px; color: #4a5568; margin: 2px; white-space: nowrap; }
  .rule-tag .rule-id { font-family: monospace; font-weight: 700; color: #2d3748; font-size: 11px; }
  .rule-tag.inconclusive { background: #fef3c7; color: #92400e; }
  /* ── 问题分级 ── */
  .issue-item { padding: 16px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid; }
  .issue-p0 { background: #fce8e8; border-color: #e74c3c; }
  .issue-p1 { background: #fff5e6; border-color: #e07b00; }
  .issue-p2 { background: #f8f9fa; border-color: #bbb; }
  .issue-title { font-weight: 700; font-size: 14px; margin-bottom: 6px; }
  .issue-desc  { font-size: 13px; color: #555; line-height: 1.7; }
  /* ── 覆盖率 ── */
  .coverage-bar-wrap { background: #f0f2f5; border-radius: 20px; height: 10px; overflow: hidden; margin-top: 6px; }
  .coverage-bar { height: 100%; border-radius: 20px; }
  .coverage-bar.green  { background: linear-gradient(90deg, #0d8c4a, #27ae60); }
  .coverage-bar.orange { background: linear-gradient(90deg, #e07b00, #f6ad55); }
  .coverage-row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
  /* ── Benchmark ── */
  .mono { font-family: "SF Mono","Fira Code",monospace; font-size: 13px; background: #f8f9fa; padding: 16px; border-radius: 8px; white-space: pre; overflow-x: auto; }
  /* ── 名词速查 ── */
  .glossary-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 6px 20px; }
  .glossary-item { font-size: 12px; color: #444; padding: 4px 0; border-bottom: 1px solid #e8edf8; }
  .glossary-item b { color: #2d3748; }
  /* ── 优先级 ── */
  .p0 { color: #c0392b; font-weight: 700; }
  .p1 { color: #e07b00; font-weight: 600; }
  .p2 { color: #888; }
  /* ── Warning / Info ── */
  .warning-box { background: #fffdf0; border: 1px solid #e07b00; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
  .warning-box .warning-title { font-weight: 700; color: #b07800; font-size: 13px; margin-bottom: 6px; }
  .warning-box ul { font-size: 13px; color: #7a5000; padding-left: 20px; }
  .warning-box li { margin-bottom: 4px; }
  .info-box { background: #ebf8ff; border: 1px solid #90cdf4; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
  .info-box p { font-size: 13px; color: #2b6cb0; }
  code { background: #f0f2f5; padding: 1px 6px; border-radius: 4px; font-size: 12px; font-family: "SF Mono","Fira Code",monospace; }
  .footer { text-align: center; font-size: 12px; color: #bbb; margin-top: 40px; padding-top: 20px; border-top: 1px solid #e8eaf0; }
  @media (max-width: 768px) { .metric-grid { grid-template-columns: repeat(2,1fr); } .eval-tag,.delta { display:none; } }
</style>
</head>
<body>
<div class="container">

<!-- ① Header -->
<div class="report-header">
  <h1>[SKILL_NAME] 测评报告</h1>
  <div class="subtitle">AI Skill 系统性测评 · [EVAL_MODE] 模式 · iteration-[N]</div>
  <div class="meta-row">
    <div class="meta-item"><span class="label">被测 Skill</span><span class="value">[SKILL_NAME]</span></div>
    <div class="meta-item"><span class="label">测评日期</span><span class="value">[YYYY-MM-DD]</span></div>
    <div class="meta-item"><span class="label">测评账号</span><span class="value">[ACCOUNT]</span></div>
    <div class="meta-item"><span class="label">风险等级</span><span class="value">[🔴 S / 🟠 A / 🟡 B / 🟢 C] 级（[描述]）</span></div>
    <div class="meta-item"><span class="label">测评模式</span><span class="value">[quick / standard / full]</span></div>
    <div class="meta-item"><span class="label">模型</span><span class="value">[MODEL_NAME]</span></div>
    <div class="meta-item"><span class="label">执行模式</span><span class="value">[real（真实 MCP 调用）/ simulated（规则推断）]</span></div>
  </div>
</div>

<!-- ② 发布决策横幅：class 用 pass / conditional / fail -->
<div class="decision-banner [pass|conditional|fail]">
  <div class="decision-icon">[✅|⚠️|❌]</div>
  <div>
    <div class="decision-label">[PASS — 通过 | CONDITIONAL PASS — 有条件通过 | FAIL — 不通过]</div>
    <div class="decision-desc">[一句话说明决策理由，包括：主流程是否通过、未通过的核心问题是什么、条件是什么]</div>
  </div>
</div>

<!-- ③ 名词速查（固定，每次必须包含） -->
<div class="card">
  <h2>📖 名词速查</h2>
  <div style="font-size:13px;color:#888;margin-bottom:14px;padding-bottom:12px;border-bottom:2px solid #f0f2f5;">报告中出现的专业术语，不了解可以先看这里</div>
  <div class="glossary-grid">
    <div class="glossary-item"><b>eval（测试用例）</b> — 一个具体的测试场景，如 eval-1 = 日常报销完整主流程</div>
    <div class="glossary-item"><b>PASS / FAIL</b> — 该用例所有断言通过 / 有断言未通过</div>
    <div class="glossary-item"><b>INCONCLUSIVE（无法验证）</b> — 不是 AI 出错，是测试环境缺少触发条件</div>
    <div class="glossary-item"><b>with_skill / without_skill</b> — 有 Skill 指引执行 vs 纯模型不加载 Skill 执行</div>
    <div class="glossary-item"><b>Δ（增益）</b> — with_skill 通过率 − without_skill 通过率，正数越大越好</div>
    <div class="glossary-item"><b>断言（assertion）</b> — 对 AI 行为的一条具体检查项，有明确 pass/fail 标准</div>
    <div class="glossary-item"><b>evidence（证据）</b> — 断言判定所依据的 transcript/response 原文引用</div>
    <div class="glossary-item"><b>MCP 工具调用</b> — AI 调用后台服务接口的操作，如发票识别、保存草稿</div>
    <div class="glossary-item"><b>transcript.md</b> — 完整执行过程记录（含所有工具调用入参和返回值）</div>
    <div class="glossary-item"><b>路径覆盖率</b> — 本次测试覆盖了多少条可能的执行流程路径</div>
    <div class="glossary-item"><b>IFR（指令遵循率）</b> — 硬性规则被正确遵守的次数 / 触发总次数</div>
    <div class="glossary-item"><b>quick 模式</b> — 快速冒烟，仅测主流程和关键规则，结果仅供参考</div>
    <div class="glossary-item"><b>R-XX（规则编号）</b> — SKILL.md 中定义的具体业务规则编号</div>
    <div class="glossary-item"><b>S 级（关键）</b> — 该 Skill 会直接触发系统写操作，风险最高，标准最严</div>
    <!-- 可根据被测 Skill 补充专有术语，如 saveExpenseDoc、fdMonthOfOccurrence 等 -->
  </div>
</div>

<!-- ④ 一、执行摘要 -->
<div class="card">
  <h2>一、执行摘要</h2>
  <div class="summary-box">
    [3-5 句话：① Skill 整体表现；② 关键数据（通过率/增益/幻觉次数）；③ 核心问题（如有）；④ 下一步建议。]
    <br><br>
    <strong>核心待补充验证（如有）：</strong>[INCONCLUSIVE 用例的说明，无则删除此行]
  </div>
</div>

<!-- ⑤ 二、关键指标 -->
<div class="card">
  <h2>二、关键指标</h2>
  <div class="metric-grid">
    <!-- 必须包含以下 6 个 metric-card，颜色根据数值是否达标动态选择 -->
    <div class="metric-card"><div class="metric-value [green|orange|red]">[有效通过率]%</div><div class="metric-label">有效通过率（[M]/[N]）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[路径覆盖率]%</div><div class="metric-label">路径覆盖率（目标 ≥[XX]%）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[幻觉次数]</div><div class="metric-label">幻觉 / 编造数据</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[+XX% / -XX%]</div><div class="metric-label">vs baseline 增益 (Δ)</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[P0/P1问题数]</div><div class="metric-label">待修复问题（P0+P1）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[INCONCLUSIVE数]</div><div class="metric-label">INCONCLUSIVE（环境限制）</div></div>
  </div>

  <h3>发布准入指标达成情况</h3>
  <table>
    <tr><th>指标</th><th>[风险等级] 准入要求</th><th>实际结果</th><th>状态</th></tr>
    <tr><td>通过率</td><td>≥ [XX]%</td><td>[XX]%（[M]/[N] 有效用例）</td><td><span class="badge [badge-pass|badge-fail|badge-warn]">[✅ 达标 / ❌ 未达标 / ⚠ 待确认]</span></td></tr>
    <tr><td>增益 (Δ)</td><td>&gt; 0，不允许负向</td><td>[正向/负向，具体描述]</td><td><span class="badge [badge-pass|badge-fail|badge-warn]">[结论]</span></td></tr>
    <tr><td>幻觉检测</td><td>0 次</td><td>[X] 次</td><td><span class="badge [badge-pass|badge-fail]">[结论]</span></td></tr>
    <tr><td>路径覆盖率</td><td>≥ [XX]%（[模式]）</td><td>[XX]%（[M]/[N] 条路径）</td><td><span class="badge [badge-pass|badge-fail]">[结论]</span></td></tr>
    <tr><td>指令遵循率（IFR）</td><td>= 100%</td><td>[XX]%（[具体说明]）</td><td><span class="badge [badge-pass|badge-fail|badge-warn]">[结论]</span></td></tr>
    <tr><td>触发率（AI估算）</td><td>TP ≥ 80%（参考值）</td><td>[XX]%（置信度：[high/medium/low]）</td><td><span class="badge [badge-pass|badge-warn|badge-na]">[✅ 估算达标 / ⚠ 估算偏低，建议优化 / — 未测]</span></td></tr>
    <tr><td>P95 响应时间</td><td>&lt; [XX]s</td><td>[XX]s（[M]/[N] 用例有数据 / N/A）</td><td><span class="badge [badge-pass|badge-fail|badge-na]">[结论 / N/A]</span></td></tr>
    <tr><td>灾难场景</td><td>[full 模式 S/A 级要求 / quick/standard 不适用]</td><td>[X/X 通过 / 未执行]</td><td><span class="badge [badge-pass|badge-na]">[结论]</span></td></tr>
  </table>
</div>

<!-- ⑥ 三、真实 MCP 接口调用记录（正常路径用例，每条工具调用一个 details） -->
<div class="card">
  <h2>三、真实 MCP 接口调用记录</h2>
  <p style="font-size:13px;color:#888;margin-bottom:20px;">with_skill 模式真实调用记录，来自正常路径用例 transcript。点击每行展开查看完整入参与返回值。</p>

  <!-- 每个正常路径用例一个 api-group，按场景分组 -->
  <div class="api-group">
    <div class="api-group-header">
      <div class="api-group-title [daily|travel|other]">eval-[N] · [用例中文名]</div>
      <span class="api-group-desc">共 [X] 次 MCP 调用，[X] 次出错</span>
    </div>

    <!-- 每条 MCP 调用一个 details，工具名旁边加中文注释 -->
    <details class="api-call [ok|warn|err]">
      <summary class="api-call-summary">
        <span class="api-call-name">[工具名称]</span>
        <span class="api-call-zh">— [工具中文说明，如「查询报销人信息」]</span>
        <span class="api-badge [ok|warn|err]">[✓ 成功 | ⚠ 部分结果 | ✗ 失败]</span>
      </summary>
      <div class="api-call-body">
        <div class="api-kv"><span class="api-kv-label">入参</span><span class="api-kv-value">[关键入参字段 = 值]</span></div>
        <div class="api-kv"><span class="api-kv-label">返回</span><span class="api-kv-value">[关键返回字段 = 值]</span></div>
        <!-- 有说明时加 api-note，info 类用蓝色（技术背景说明），默认橙色（警告） -->
        <div class="api-note [info可选]">[补充说明]</div>
      </div>
    </details>
    <!-- ... 重复更多工具调用 ... -->
  </div>
  <!-- ... 重复更多 eval 组 ... -->
</div>

<!-- ⑦ 四、各用例执行情况 -->
<div class="card">
  <h2>四、各用例执行情况</h2>
  <p style="font-size:13px;color:#888;margin-bottom:16px;">点击展开每个用例查看断言明细、with/without_skill 对比及 MCP 调用记录。</p>

  <!-- 按批次分组 -->
  <h3>批次 1：正常路径（Happy Path）</h3>

  <!-- 每个用例一个 details，class 根据结果选 eval-pass / eval-warn / eval-fail -->
  <details class="eval-item [eval-pass|eval-warn|eval-fail]">
    <summary class="eval-summary">
      <span class="eval-id">#[N]</span>
      <span class="eval-name">[用例中文名]</span>
      <span class="eval-tag">[用例类型]</span>
      <span class="badge [badge-pass|badge-fail|badge-warn]">with [✅|❌|⚠] [M]/[N]</span>
      <span class="badge [badge-pass|badge-fail|badge-warn|badge-na]">w/o [✅|❌|⚠|—]</span>
      <span class="delta [pos|neg|neu]" title="[Δ 详细说明]">[Δ +XX% / -XX% / ≈0 / N/A]</span>
    </summary>
    <div class="eval-detail">

      <!-- with_skill 结果 -->
      <div class="detail-section">
        <div class="detail-label">with_skill 结果</div>
        <div class="detail-content">
          [结果描述]
          <!-- 有 MCP 调用时加 mcp-table -->
          <table class="mcp-table" style="margin-top:8px;">
            <tr><th>#</th><th>工具</th><th>入参摘要</th><th>返回摘要</th><th>状态</th></tr>
            <tr class="mcp-row-ok"><td>[N]</td><td><code>[工具名]</code></td><td>[入参]</td><td>[返回]</td><td><span class="mcp-ok">✅</span></td></tr>
            <tr class="mcp-row-err"><td>[N]</td><td><code>[工具名]</code></td><td>[入参]</td><td>[错误信息]</td><td><span class="mcp-err">❌</span></td></tr>
          </table>
        </div>
      </div>

      <!-- without_skill 结果 -->
      <div class="detail-section">
        <div class="detail-label">without_skill 结果</div>
        <div class="detail-content">[结果描述]</div>
      </div>

      <!-- 断言列表（必须逐条，每条带 evidence） -->
      <div class="detail-section">
        <div class="detail-label">断言结果（[M]/[N] 通过）</div>
        <ul class="assertion-list">
          <li>
            <span class="[assert-pass|assert-fail]">[✓|✗]</span>
            <div class="assert-body">
              <span class="assert-text">[断言描述]</span>
              <span class="assert-evidence">[evidence：引用 transcript/response 原文]</span>
            </div>
          </li>
          <!-- ... 重复更多断言 ... -->
        </ul>
      </div>

      <!-- 覆盖规则（rule-tag 必须带中文描述） -->
      <div class="detail-section">
        <div class="detail-label">覆盖规则</div>
        <div class="detail-content">
          <span class="rule-tag"><span class="rule-id">R-[XX]</span> [规则中文描述]</span>
          <span class="rule-tag inconclusive"><span class="rule-id">R-[XX]</span> [规则描述]（INCONCLUSIVE）</span>
        </div>
      </div>

      <!-- INCONCLUSIVE 时必须加此块 -->
      <div class="detail-section detail-warn">
        <div class="detail-label">INCONCLUSIVE 原因</div>
        <div class="detail-content">[环境限制说明]<br>补充方式：[如何补充测试资产]</div>
      </div>

    </div>
  </details>
  <!-- ... 重复更多用例 ... -->

  <!-- INCONCLUSIVE 汇总（有 INCONCLUSIVE 用例时必须加） -->
  <div class="warning-box" style="margin-top:16px;">
    <div class="warning-title">⚠ INCONCLUSIVE 用例说明（不计入通过率）</div>
    <ul>
      <li><strong>eval-[N]（[规则编号]）</strong>：[原因] 补充方式：[操作]</li>
    </ul>
  </div>
</div>

<!-- ⑧ 五、发现的问题 -->
<div class="card">
  <h2>五、发现的问题</h2>

  <!-- P0：必须修复，否则 FAIL -->
  <div class="issue-item issue-p0">
    <div class="issue-title">P0 · 严重：[问题标题]</div>
    <div class="issue-desc">[问题描述，包括：现象、根因、影响范围]<br><br><strong>修复方式：</strong>[具体步骤]</div>
  </div>
  <!-- P1：重要，CONDITIONAL PASS 须修复 -->
  <div class="issue-item issue-p1">
    <div class="issue-title">P1 · 中等风险：[问题标题]</div>
    <div class="issue-desc">[描述]<br><strong>建议：</strong>[修复建议]</div>
  </div>
  <!-- P2：低风险，可延后 -->
  <div class="issue-item issue-p2">
    <div class="issue-title">P2 · 低风险：[问题标题]</div>
    <div class="issue-desc">[描述]<br><strong>建议：</strong>[修复建议]</div>
  </div>
</div>

<!-- ⑨ 六、测评覆盖率 -->
<div class="card">
  <h2>六、测评覆盖率</h2>

  <!-- 三条进度条 -->
  <div style="margin-bottom:20px;">
    <div class="coverage-row"><span>路径覆盖率</span><span style="font-weight:600;">[XX]%（[M]/[N] 条）</span></div>
    <div class="coverage-bar-wrap"><div class="coverage-bar [green|orange]" style="width:[XX]%"></div></div>
    <div style="font-size:12px;color:#888;margin-top:4px;">[模式] 目标 ≥[XX]% [✅ 达标 / ❌ 未达标]</div>
  </div>
  <div style="margin-bottom:20px;">
    <div class="coverage-row"><span>规则覆盖率</span><span style="font-weight:600;">[XX]%（[M]/[N] 条规则）</span></div>
    <div class="coverage-bar-wrap"><div class="coverage-bar [green|orange]" style="width:[XX]%"></div></div>
    <div style="font-size:12px;color:#888;margin-top:4px;">[模式] 目标 ≥[XX]% [✅ 达标 / ❌ 未达标]</div>
  </div>
  <div style="margin-bottom:20px;">
    <div class="coverage-row"><span>断言覆盖率</span><span style="font-weight:600;">[XX]%（[M]/[N] 条断言有 evidence）</span></div>
    <div class="coverage-bar-wrap"><div class="coverage-bar [green|orange]" style="width:[XX]%"></div></div>
    <div style="font-size:12px;color:#888;margin-top:4px;">目标 ≥90% [✅ 达标 / ❌ 未达标]</div>
  </div>

  <!-- 已覆盖规则（rule-tag 带中文） -->
  <h3>已覆盖规则（[X] 条）</h3>
  <p style="font-size:13px;color:#4a5568;margin-bottom:10px;">
    <span class="rule-tag"><span class="rule-id">R-[XX]</span> [描述]</span>
    <span class="rule-tag inconclusive"><span class="rule-id">R-[XX]</span> [描述]（INCONCLUSIVE）</span>
  </p>

  <!-- 未覆盖规则 -->
  <h3>未覆盖规则（[X] 条，保留至下次迭代）</h3>
  <table>
    <tr><th>规则</th><th>描述</th><th>未覆盖原因</th></tr>
    <tr><td>[R-XX]</td><td>[描述]</td><td>[原因]</td></tr>
  </table>
</div>

<!-- ⑩ 七、Benchmark 数据 -->
<div class="card">
  <h2>七、Benchmark 数据</h2>
  <div class="mono">┌──────────────────────┬──────────────────┬────────────────────────────────────────────┐
│ Configuration        │ 通过率            │ 关键差异                                    │
├──────────────────────┼──────────────────┼────────────────────────────────────────────┤
│ with_skill           │ [XX]% ([M]/[N])  │ [Skill 核心优势描述]                        │
│ without_skill        │ [XX]% ([M]/[N])  │ [without 的主要问题]                        │
├──────────────────────┼──────────────────┼────────────────────────────────────────────┤
│ Delta (Δ)            │ [+XX%]           │                                            │
└──────────────────────┴──────────────────┴────────────────────────────────────────────┘

MCP 调用次数对比（正常路径用例）：
  eval-[N] [场景名]：with_skill = [X]次/[X]错 → [结果]  vs  without_skill = [X]次/[X]错 → [结果]</div>
  <p style="font-size:12px;color:#a0aec0;margin-top:8px;">⚠ [模式] 模式[单次/N次]运行，耗时受网络和接口响应影响，仅供参考。</p>
</div>

<!-- ⑪ 八、改进建议 -->
<div class="card">
  <h2>八、改进建议</h2>
  <table>
    <tr><th>优先级</th><th>改进方向</th><th>具体建议</th><th>预期影响</th></tr>
    <tr><td><span class="p0">P0</span></td><td>[方向]</td><td>[精确到文件名/函数名/行号的操作]</td><td>[量化预期效果]</td></tr>
    <tr><td><span class="p1">P1</span></td><td>[方向]</td><td>[具体操作]</td><td>[预期效果]</td></tr>
    <tr><td><span class="p2">P2</span></td><td>[方向]</td><td>[具体操作]</td><td>[预期效果]</td></tr>
  </table>
</div>

<!-- ⑫ 九、Skill 复杂度评估 -->
<div class="card">
  <h2>九、Skill 复杂度评估</h2>
  <table>
    <tr><th>指标</th><th>数值</th><th>健康范围</th><th>状态</th></tr>
    <tr><td>模块数量</td><td>[X]（[模块名]）</td><td>2-3</td><td><span class="badge [badge-pass|badge-fail]">[✅ 正常 / ❌ 超标]</span></td></tr>
    <tr><td>SKILL.md 行数</td><td>[X] 行</td><td>&lt; 200 行</td><td><span class="badge [badge-pass|badge-warn]">[✅ 精简 / ⚠ 偏多]</span></td></tr>
    <tr><td>硬性规则条数</td><td>[X] 条</td><td>—</td><td><span class="badge badge-pass">✅ 正常</span></td></tr>
    <tr><td>条件分支深度</td><td>≤ [X] 层</td><td>≤ 3 层</td><td><span class="badge [badge-pass|badge-fail]">[✅ 正常 / ❌ 超标]</span></td></tr>
    <tr><td><strong>复杂度得分</strong></td><td><strong>[XX] 分</strong></td><td>≤ 20 分</td><td><span class="badge [badge-pass|badge-warn|badge-fail]">[✅ 适中 / ⚠ 偏高 / ❌ 超标]</span></td></tr>
  </table>
  <div class="info-box" style="margin-top:12px;"><p>[Skill 架构评价，1-2句]</p></div>
</div>

<!-- ⑬ 十、测评环境 -->
<div class="card">
  <h2>十、测评环境</h2>
  <table>
    <tr><th style="width:180px;">项目</th><th>值</th></tr>
    <tr><td>模型</td><td>[MODEL_NAME]</td></tr>
    <tr><td>Skill 类型</td><td>[mcp_based / text_generation / code_execution]</td></tr>
    <tr><td>执行模式</td><td>[real（真实 MCP 调用）/ text（纯文本模式）/ simulated（规则推断）]</td></tr>
    <tr><td>Skill 路径</td><td>[SKILL_PATH]</td></tr>
    <tr><td>Skill 版本</td><td>[git commit / last_modified_YYYY-MM-DD]</td></tr>
    <tr><td>测评账号</td><td>[ACCOUNT]</td></tr>
    <tr><td>测试素材</td><td>[文件名（类型，¥金额，日期）/ 无文件（口述代替）/ 纯文本 Skill 不适用]</td></tr>
    <tr><td>workspace_dir</td><td>[WORKSPACE_DIR]</td></tr>
    <tr><td>每用例运行次数</td><td>[1 次（quick）/ 3 次（standard/full）]</td></tr>
    <tr><td>总用例数</td><td>[N] 个（[M] PASS · [K] INCONCLUSIVE · [J] FAIL）</td></tr>
  </table>
  <!-- quick 或 simulated 模式必须加此说明框 -->
  <div class="warning-box" style="margin-top:16px;">
    <div class="warning-title">⚠ [quick / simulated / text_generation] 模式限制说明</div>
    <ul>
      <li>[quick] 单次运行，无方差数据，结果稳定性未知</li>
      <li>[quick] 不包含 E2E 多轮对话测试</li>
      <li>[quick] 不包含灾难场景测试（S 级必须在 full 模式下补充）</li>
      <li>[simulated] MCP 工具未真实调用，通过率仅反映规则自洽性</li>
      <li>[text_generation] 纯文本模式：无 MCP 调用链路，断言仅验证输出内容质量，不涵盖系统集成</li>
    </ul>
  </div>
</div>

<!-- ⑭ 十一、触发率预评估（AI 模拟）— 所有 Skill 类型必须包含 -->
<div class="card">
  <h2>十一、触发率预评估（AI 模拟）</h2>
  <div class="info-box" style="margin-bottom:16px;">
    <p>⚠️ 以下数据为 AI 模拟估算，基于对 Skill description 的语义分析，<strong>非真实测量值</strong>。精确触发率需 skill-creator run_eval.py（需 claude CLI 环境）。</p>
  </div>
  <div class="metric-grid">
    <div class="metric-card"><div class="metric-value [green|orange|red]">[XX]%</div><div class="metric-label">TP 估算触发率（[M]/[N] 应触发场景）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[XX]%</div><div class="metric-label">TN 估算不触发率（[M]/[N] 不应触发场景）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange]">[N] 条</div><div class="metric-label">边界情况（uncertain）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[high|medium|low]</div><div class="metric-label">整体置信度</div></div>
  </div>
  <h3>触发测试用例明细</h3>
  <table>
    <tr><th>类型</th><th>测试 Prompt</th><th>预测</th><th>置信度</th><th>判断依据</th></tr>
    <tr><td><span class="badge badge-pass">TP</span></td><td>[prompt文本]</td><td>[trigger/no_trigger/uncertain]</td><td>[0.X]</td><td>[引用 description 的判断依据]</td></tr>
    <tr><td><span class="badge badge-na">TN</span></td><td>[prompt文本]</td><td>[no_trigger]</td><td>[0.X]</td><td>[判断依据]</td></tr>
    <tr><td><span class="badge badge-warn">边界</span></td><td>[prompt文本]</td><td>[uncertain]</td><td>[0.X]</td><td>[模糊原因]</td></tr>
  </table>
  <!-- TP 触发率 < 70% 时必须加此警告 -->
  <!-- <div class="warning-box"><div class="warning-title">⚠ 触发率估算偏低</div><ul><li>建议优化 description，明确「何时触发」的场景描述</li><li>建议增加典型触发场景举例</li></ul></div> -->
</div>

<!-- ⑮ 十二、效率指标汇总 — timing.json 有数据时展示，全部缺失时注明 N/A -->
<div class="card">
  <h2>十二、效率指标汇总</h2>
  <!-- timing 数据存在时填充以下内容 -->
  <div class="metric-grid">
    <div class="metric-card"><div class="metric-value [green|orange|red]">[XX]ms</div><div class="metric-label">P50 响应时间</div></div>
    <div class="metric-card"><div class="metric-value [green|orange|red]">[XX]ms</div><div class="metric-label">P95 响应时间（准入阈值 [XX]s）</div></div>
    <div class="metric-card"><div class="metric-value [green|orange]">[XX]</div><div class="metric-label">平均 Token 消耗/用例</div></div>
    <div class="metric-card"><div class="metric-value [green|orange]">[+XX%/token]</div><div class="metric-label">Token 效率比（Δ/额外消耗）</div></div>
  </div>
  <h3>逐用例响应时间</h3>
  <table>
    <tr><th>#</th><th>用例名称</th><th>with_skill 耗时</th><th>without_skill 耗时</th><th>Token（with）</th><th>P95 达标</th></tr>
    <tr><td>[N]</td><td>[用例名]</td><td>[XX]ms</td><td>[XX]ms</td><td>[XX]</td><td><span class="badge [badge-pass|badge-fail|badge-na]">[✅ / ❌ / N/A]</span></td></tr>
  </table>
  <!-- timing 数据全部缺失时替换为以下内容 -->
  <!-- <div class="warning-box"><div class="warning-title">⚠ 本次测评未采集 timing 数据</div><ul><li>原因：subagent 执行结束时未写入 timing.json</li><li>下次测评时，请确保在 subagent 完成后立即写入 executor_start_ms、executor_end_ms、total_tokens 字段</li></ul></div> -->
</div>

<!-- Footer -->
<div class="footer">
  生成时间：[YYYY-MM-DD] · SkillSentry · [SKILL_NAME] · iteration-[N]<br>
  <span style="margin-top:4px;display:block;">⚠ 本报告基于 [模式] 模式[单次/N次]运行，[quick: 结果仅供参考，不适合作为 S 级正式发布依据]</span>
</div>

</div>
</body>
</html>
```

---

## 各章节填写规则（重要）

### 名词速查
- **每次生成报告都必须包含**，不得省略
- 基础 14 条术语固定保留
- 根据被测 Skill 的特有术语（如 `saveExpenseDoc`、`fdMonthOfOccurrence`）在末尾追加，最多补充 4 条

### 第三章：真实 MCP 接口调用记录
- **只展示正常路径（happy path）用例的 with_skill 记录**
- 每个 MCP 工具调用一个 `<details>`，工具名旁必须加中文注释（`api-call-zh`）
- `simulated` 模式时替换为：`<p style="color:#e07b00;">⚠ 规则推断模式，无真实 MCP 调用记录。</p>`

### 第四章：各用例执行情况
- **所有用例全部展示，一个都不能省**
- 每条断言必须有 `assert-evidence`，引用 transcript/response 原文
- INCONCLUSIVE 用例：`eval-warn` class，必须加 `detail-warn` 说明原因和补充方式
- rule-tag 必须带中文描述，格式：`<span class="rule-tag"><span class="rule-id">R-XX</span> 中文描述</span>`

### 颜色选择规则

| 指标值 | metric-value class | coverage-bar class |
|--------|-------------------|--------------------|
| 达标 / 正向 / 0 问题 | `green` | `green` |
| 临近阈值 / 有待确认 | `orange` | `orange` |
| 未达标 / 负向 / 有 P0 | `red` | （默认蓝）|
