---
name: sentry-report
description: >
  汇总测评结果，生成 HTML 报告和发布决策。需要先完成用例执行和 Grader 评审。
  触发场景：说"生成测评报告"、"出报告"、"给我看结果"、"通过了吗"、"能上线吗"、
  "汇总测评结果"、"帮我写发布报告"。
  不触发场景：要执行测试用例（用 sentry-executor）、要做完整流程（用 SkillSentry）。
---

# sentry-report · 测评报告生成与发布决策

读取 session 目录下所有 grading.json，汇总指标，生成 HTML 报告和 PASS/FAIL 发布决策。

**前置条件**：workspace_dir 下各 eval-N 目录中存在 grading.json（由 Grader 填写）。

---

## 输入

- `workspace_dir`：本次测评工作目录
- `mode`：测评模式（smoke/quick/standard/full）
- `skill_name`：被测 Skill 名称

单独调用时，从用户指定路径或最近一次 session 目录读取。

---

## Step 1：汇总通过率

从所有 `eval-N/grading.json` 提取：

```
精确通过率 = exact_match 断言通过数 / exact_match 断言总数  ← 准入判断用这个
语义通过率 = semantic 断言通过数 / semantic 断言总数（参考）
综合通过率 = 全部断言通过数 / 全部断言总数（兼容显示）
```

quick 模式（2次运行）：
- 最终通过率 = 两次均值（不取最优）
- 两次差距 > 15% → 标红「⚠️ 结果不稳定（差距 [X]%），建议升级 standard 模式」

---

## Step 2：效率指标聚合

从所有 `timing_with.json` / `timing_without.json` 计算：

```
P50 响应时间 = with_skill duration_ms 的中位数
P95 响应时间 = with_skill duration_ms 的 P95
平均 Token 消耗 = with_skill total_tokens 均值
额外 Token 消耗 = with_skill均值 - without_skill均值
```

---

## Step 3：效率维度诊断

```
E-1：Token 消耗合理性
  额外消耗 > 2000 tokens/用例 且 Δ < 10% → ⚠️「Token 效率偏低」

E-2：工具调用次数合理性（mcp_based）
  平均调用次数 > 预期次数的 1.5 倍 → ⚠️「工具调用疑似冗余」

E-3：复杂度（从 execution-phases 数据中读取，若有）
  复杂度得分 > 20 → ⚠️  > 30 → ❌
```

---

## Step 4：发布准入判断

对照准入标准（以 `精确通过率` 为准，existence 断言不计入）：

| 等级 | 精确通过率 | 增益 Δ | P95 响应时间 |
|------|----------|--------|------------|
| S | ≥ 95% | > 0 | < 15s |
| A | ≥ 90% | > 0 | < 15s |
| B | ≥ 80% | ≥ -5% | < 30s |
| C | ≥ 70% | - | < 30s |
| FAIL | < 70% | - | - |

**smoke 模式**：不出具 PASS/FAIL，只输出「冒烟通过 / 冒烟失败」。

**CONDITIONAL PASS 触发条件**（S/A 级自动降级）：
- 触发率 TP < 70%（如有 sentry-trigger 结果）
- 触发率置信度 low 且 TP < 80%
- TN 中有误触发预测

---

## Step 5：生成报告

读取 `~/.claude/skills/SkillSentry/references/report-template.md`，填充以下章节：

```
一、测评概览（Skill名/模式/日期/总用例数）
二、核心指标（精确/语义/综合通过率 + 等级）
三、用例覆盖（类型分布饼图文字描述）
四、失败用例分析（grading.json 中 passed=false 的断言列表）
五、增益分析（with vs without Δ，若有 Comparator 结果则附上）
六、HiL 合规检查（来自 grading.json 中的 HiL 断言）
七、效率指标（P50/P95 响应时间，Token 消耗）
八、改进建议（来自 Grader eval_feedback + Analyzer analysis.json）
九、发布决策（PASS/CONDITIONAL PASS/FAIL + 等级）
十、下一步行动（具体可执行的改进项）
十一、触发率预评估（若有 trigger_eval.json）
十二、效率诊断（E-1/E-2/E-3 结果）
```

保存为 `workspace_dir/report.html`（使用 report-template.md 中的 HTML 模板）。

---

## 输出

```
✅ 报告生成完成

📊 测评结果摘要
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Skill：<名称>  模式：<模式>  日期：<日期>

精确通过率：[X]%（[N]/[N]）  ← 准入判断依据
语义通过率：[X]%（参考）
综合通过率：[X]%

P95 响应时间：[X]ms
增益 Δ：[+X%] / [-X%]

发布决策：[PASS S级 / CONDITIONAL PASS / FAIL]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 P0 必修（[N]项）：[第一条改进建议，一句话] / ✅ 无
🟡 P1 建议（[N]项）：见完整报告

📁 完整报告：
  macOS/Linux： <workspace_dir>/report.html
  Windows：     <workspace_dir 转换为 Windows 路径>\report.html
                示例：C:\Users\<用户名>\.claude\skills\SkillSentry\sessions\<Skill名>\<日期>\report.html
```

---

## 准则

- smoke 模式不出 PASS/FAIL，只出「冒烟通过/失败」
- 精确通过率是唯一准入依据，existence 断言不参与判断
- 失败用例必须列出具体失败断言和 evidence，不允许「通过率低」的模糊表述
- 改进建议按 P0/P1/P2 优先级排序，使用以下固定格式输出，每条建议对应具体的 SKILL.md 修改位置：

```
🔴 P0 · 必须修复（影响发布决策）
  1. [规则缺失] Step 3 未处理用户拒绝确认的情况 → 在 SKILL.md Step 3 补充「用户拒绝 → 终止流程并告知」
  2. ...

🟡 P1 · 建议修复（影响可靠性）
  1. [断言过弱] eval-4 的金额校验断言为 existence 级，建议升级为 exact_match
  2. ...

🟢 P2 · 可选优化（提升质量）
  1. [冗余规则] 规则 7 与规则 3 重叠，可合并
  2. ...
```

P0 为空时输出「✅ 无必须修复项」，不输出空标题。
