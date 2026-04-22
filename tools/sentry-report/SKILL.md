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
- `inputs_dir`：`~/.claude/skills/SkillSentry/inputs/<skill_name>/`（sentry-trigger 结果存于此）
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

**多次运行通过率聚合规则**：

| mode | 运行次数 | 最终通过率计算 | 稳定性告警 |
|------|---------|-------------|---------|
| smoke / regression | 1 | 直接使用 | — |
| quick | 2 | 两次均值（不取最优） | 两次差距 > 15% → ⚠️「结果不稳定，建议升级 standard」 |
| standard / full | 3 | 三次均值（不取最优、不取最差） | 最高-最低 > 15% → ⚠️「结果不稳定，请关注随机性」；连续下降 → ⚠️「通过率趋势递减」 |

> 同一 eval 有多次 grading.json 时（run-1/run-2/run-3），路径约定为 `eval-N/run-R/grading.json`；sentry-executor 按此约定写入。

---

## Step 2：效率指标聚合

从所有 `timing_with.json` / `timing_without.json` 计算：

```
P50 响应时间 = with_skill duration_ms 的中位数
P95 响应时间 = with_skill duration_ms 的 P95
平均 Token 消耗 = with_skill total_tokens 均值
额外 Token 消耗 = with_skill均值 - without_skill均值
  ↳ 若所有 eval 均 skip_without_skill（mcp_based + smoke/quick）：
      额外 Token 消耗 = N/A，E-1 检查跳过，增益 Δ = N/A
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

> **mcp_based + smoke/quick 模式**：所有 eval 均 skip_without_skill，无 without_skill 数据，增益 Δ = N/A。S/A 等级的 `Δ > 0` 条件自动豁免（以精确通过率和 P95 为唯一准入依据），发布决策标注「Δ 未采集（smoke/quick 模式）」。

> 完整准入指标（触发率、IFR、一致性、稳定性等）以及 CONDITIONAL PASS 详细条件，见 `references/admission-criteria.md`。本表仅列核心通过率列，两者如有出入以 `admission-criteria.md` 为准。

**smoke 模式**：不出具 PASS/FAIL，只输出「冒烟通过 / 冒烟失败」。

**CONDITIONAL PASS 触发条件**（S/A 级自动降级）：
- 触发率 TP < 70%（如有 `inputs_dir/trigger_eval.json`）
- 触发率置信度 low 且 TP < 80%
- TN 中有误触发预测（score ≥ 0.7）

---

## Step 4.2：基线快照生成与跨版本退化检测

读取 `inputs_dir/baseline.snapshot.json`（若存在），执行以下逻辑：

### 情况 A：基线快照不存在（首次有效测评）

- 不做对比，输出「📝 首次测评，暂无基线可对比」
- **若本次发布决策为 PASS（S/A/B 任一级）**，在生成报告后写入基线快照：

```json
{
  "created_at": "<ISO时间>",
  "skill_hash": "<SKILL.md MD5，来自 inputs_dir/rules.cache.json>",
  "mode": "<本次模式>",
  "session": "<session目录名>",
  "verdict": "<S|A|B>",
  "exact_match_pass_rate": 0.XX,
  "avg_delta": 0.XX,
  "stddev": 0.XX,
  "IFR": 0.XX,
  "p95_response_ms": XXXX
}
```

### 情况 B：基线快照存在（对比基线，检测退化）

读取基线，计算各指标的差值，输出对比区块：

```
📐 基线快照对比（基线建立于 <日期>，<verdict> 级）
─────────────────────────────────────
              基线         本次         变化
精确通过率：  87%          92%          +5% ↑
增益 Δ：     +12%         +15%         +3% ↑
Stddev：      0.12         0.08         -0.04（更稳定）
IFR：         95%          100%         +5% ↑
─────────────────────────────────────
结论：相比基线，本版本全面进步，无退化迹象 ✅
```

**退化检测规则**：

| 条件 | 输出 | 对发布决策的影响 |
|------|------|----------------|
| 精确通过率比基线低 ≥ 5% | ⚠️ `精确通过率退化 [X]%，请排查根因` | PASS → CONDITIONAL PASS |
| 精确通过率比基线低 < 5% | ℹ️ `轻微波动，在正常范围内` | 不影响发布决策 |
| Δ 由正转负 | ⚠️ `增益方向逆转（基线 Δ=[+X%]，本次 Δ=[-X%]）` | PASS → CONDITIONAL PASS |
| Stddev 显著升高（> 0.10 且比基线高 50%）| ℹ️ `稳定性下降，建议升级为 standard 模式` | 不影响发布决策 |
| skill_hash 与基线不同 | ℹ️ `SKILL.md 已变更，基线为旧版本快照` | 不影响发布决策 |

**基线更新规则**（不自动覆盖，由用户决定）：

```
本次结果比基线全面进步（所有指标均更优）时，输出提示：
  💡 本次结果全面优于基线。如需将本次作为新基线，回复「更新基线」。
```

**smoke 模式**：不触发此步骤（smoke 不出 PASS/FAIL，没有可存储的基线）。
**regression 模式**：触发对比，但不写入新基线（regression 用于验证，不更新基线）。

---

## Step 4.5：历史趋势对比

读取 `inputs_dir/history.json`（若存在），对比本次结果与历史：

```
历史记录存在（≥ 2 条）时，输出趋势区块：

  📈 历史趋势（最近 5 次 quick/standard/full，不含 smoke）
  ─────────────────────────────────────────
  日期        模式     精确通过率  Δ       判决
  2026-04-03  quick    75.0%   +3.2%   B
  2026-04-07  quick    78.5%   +4.1%   B
  2026-04-10  quick    83.0%   +5.0%   A   ← 本次
  ─────────────────────────────────────────
  趋势：精确通过率 ↑ 持续上升（+8.0% over 3 runs）
```

**趋势判断规则**：
- 取同类型模式（quick 对比 quick）最近 5 条记录
- 比较首尾值，差距 > 5% 视为显著趋势
- 连续 2 次下降 → ⚠️ 标红「质量趋势下降」
- 连续 3 次稳定（差距 < 3%）→ ✅「质量稳定」

**smoke 模式**：历史趋势区块显示但不影响发布决策，仅展示最近 3 次 smoke 结果。

**首次测评或历史数据 < 2 条**：输出「📝 首次测评，建立历史基线」，不输出趋势。

---

## Step 5：生成报告

读取 `~/.claude/skills/SkillSentry/references/report-template.md`，填充以下章节：

```
一、测评概览（Skill名/模式/日期/总用例数）
二、核心指标（精确/语义/综合通过率 + 等级）
三、基线对比（与首次 PASS 基线的指标变化，来自 baseline.snapshot.json）← 改动3新增
四、历史趋势（折线图：最近 10 次精确通过率，来自 history.json）
五、用例覆盖（类型分布饼图文字描述）
六、失败用例分析（grading.json 中 passed=false 的断言列表）
七、增益分析（with vs without Δ，若有 Comparator 结果则附上）
八、HiL 合规检查（来自 grading.json 中的 HiL 断言）
九、效率指标（P50/P95 响应时间，Token 消耗）
十、改进建议（来自 Grader eval_feedback + Analyzer analysis.json）
十一、发布决策（PASS/CONDITIONAL PASS/FAIL + 等级）
十二、下一步行动（具体可执行的改进项）
十三、触发率预评估（若有 `inputs_dir/trigger_eval.json`，由 sentry-trigger 写入）
十四、效率诊断（E-1/E-2/E-3 结果）
```

保存为 `workspace_dir/report.html`（使用 report-template.md 中的 HTML 模板）。

**历史折线图规范**（嵌入 HTML）：
```html
<!-- 用内联 SVG 或 Chart.js CDN，折线图显示精确通过率随时间变化 -->
<!-- 数据来源：history.json 最近 10 条记录（仅 quick/standard/full 模式） -->
<!-- X 轴：日期，Y 轴：精确通过率（0-100%），参考线：80%（B 级）和 90%（A 级） -->
```

---

## Step 6：更新历史记录

报告生成完成后，将本次结果追加到 `inputs_dir/history.json`：

```bash
python3 ~/.claude/skills/SkillSentry/scripts/update_history.py \
  --skill <skill_name> \
  --session-dir <workspace_dir> \
  --mode <mode> \
  --avg-delta <Step1计算的增益Δ，如 0.12 或 -0.05，无 without_skill 数据时省略此参数>
```

若脚本不可用，手动构造条目并追加：
```json
{
  "run_at": "<ISO时间>",
  "session": "<session目录名>",
  "mode": "<mode>",
  "eval_count": <N>,
  "exact_pass_rate": <0.xx>,
  "avg_delta": <0.xx>,
  "verdict": "<S|A|B|C|FAIL>"
}
```

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
