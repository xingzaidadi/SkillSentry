# output-format.md — 步骤完成消息格式规范

> 主调度器产物验收（动作 3）的完整输出格式。
> 所有步骤（executor/grader/report）的 completion message 必须遵循此格式。

---

## executor completion message 格式

按用例类型分组，四列表头展示决策过程：

```
**{type}({N})**
| 用例 | 用户输入 | 路由决策 | 执行结果 |
|------|---------|---------|----------|
| hp_01 | "查BR单号" | BR前缀→budget MCP | 返回详情:已撤回 ¥3.00 |
| ec_01 | "查我的单据" | 未指定类型→不调MCP | 引导选择 |
| sec_01 | "撤回报销单" | 写操作→触发HiL | 复述动作,等待确认 |
| e2e_01 | 查单据→选预算→单号 | 引导→budget | 最终返回详情 |
```

格式要求：
- 按 type 分组（happy_path / edge_case / negative / robustness / security / e2e）
- 四列：用例ID | 用户输入(简写) | 路由决策(输入→决策→目标) | 执行结果(关键数据)
- 每行一目了然：看到输入、看到决策、看到结果
- 最后总结：成功率 + 1-2句关键发现
- **禁止只写"成功/失败/返回 1 条"，必须有具体数据**

---

## 多轮展示规则（standard/full 模式 3 runs）

- Run-1：完整展示（按类型分组 + 四列表头）
- Run-2/3：只展示与 Run-1 的差异 + 一行总结
- 格式：
  ```
  ✅ Run-2 完成(23/23)· 与 Run-1 一致,无差异。
  ```
  或：
  ```
  ⚠️ Run-3 完成(21/23 一致,2 处差异)
  | 用例 | Run-1 结果 | Run-3 结果 | 差异原因 |
  |------|-----------|-----------|----------|
  | hp_02 | ⚠️ code=1009 | ❌ 参数异常加剧 | MCP 间歇性 |
  ```

---

## grader/report 最终结果消息格式

### eval 展示规则（通过折叠，失败展开）

| 结果 | 展示方式 |
|------|----------|
| ✅ 通过 | 一行摘要：`eval名 ✅ N/N 断言通过` |
| ❌ 失败 | 完整展开：断言详情 + evidence + 失败原因 |

**目的**：减少卡片长度，让用户聚焦失败项。完整详情通过末尾 HTML 报告链接查看。

**第一部分：per-eval 结果表**（按类型分组）
```
**{type}({N})**

✅ 通过的 eval（折叠展示）：
• hp_01 ✅ 3/3 | hp_02 ✅ 2/2 | hp_03 ✅ 4/4

❌ 失败的 eval（展开详情）：
| 用例 | 用户输入 | 路由决策 | 执行结果 | 断言 | 失败详情 |
|------|---------|---------|----------|------|----------|
| ec_01 | "查单据" | 未指定→引导 | 返回错误 | ❌ 1/3 | E2:缺少引导词(semantic) |
```

**第二部分：断言统计 (Assertion Stats)**
```
断言 (Assertions):15/15 通过 (Passed)(exact_match: 11/11 + semantic: 4/4)
```

**第三部分：质量指标**
```
质量指标:
• A1 可用性(Availability):有响应 ✅ | A2 崩溃率(Crash Rate):无崩溃 ✅ | A3 响应率(Response Rate):100% ✅
• C1 工具完整率(Tool Completeness):100% | C2 工具越界率(Tool Violation):0% | C4 副作用率(Side Effect):0%
• C5 参数正确率(Param Correctness):100% | E3 效率(Efficiency):达标
• V1-V8 否决项(Veto Checks):0 项触发
• Delta 增益(with_skill vs without_skill):{具体数值 或 N/A+原因}
```

Delta 说明（按模式）：
- smoke/quick(mcp_based)：展示 "N/A(跳过 without_skill，mcp_based 无法在无 Skill 时调用工具)"
- standard/full(mcp_based)：展示 delta 值（数据来源: eval-*/run-1/without_skill/outputs/response.md）
- text_generation 所有模式：始终展示 delta（数据来源同上）
- V1-V8：只要有 1 项触发必须标注 ⚠️

**Delta 数据来源**：executor-without 步骤产物 `eval-{N}/run-1/without_skill/outputs/response.md`。
若该步骤被跳过（见 mode-levels.md 跳过规则），则 Delta 展示 N/A + 原因。

**第四部分：基线对比 (Baseline Comparison)**
```
基线对比 (Baseline):上次 S 级 100% → 本次 S 级 100%,无退化 (No Regression)
```

**第五部分：汇总 (Summary)**
```
评级 (Grade):S | 决策 (Decision):PASS | 总耗时 (Duration):~12min
```

**禁止只写"100% 通过"。**用户需要看到每个 eval 的具体数据+所有质量指标+否决项+基线对比。

---

## 主调度器结果通知模板

```
message(action=send, msg_type="text", message="
🦞 SkillSentry · Step {N} {step_name} 完成

✅ {passed}/{total} 用例成功

| Eval | 用例 | MCP Server | 结果 |
|------|------|-----------|------|
| eval-1 | {摘要} | {server} | {结果} |
| eval-2 | ... | ... | ... |

关键发现:
• {发现 1}
• {发现 2}

🔧 Step {N+1} {next_step_name} 执行中...
")
```

---

---

## Completion Gate（硬阻断，非建议）

publish 步骤的最终状态只能是以下三种之一：

| 状态 | 条件 | 用户看到的 |
|------|------|----------|
| **COMPLETE** | 下方 7 项 Gate 全过 | 完整五部分卡片 + HTML 链接 |
| **PARTIAL** | 1-2 项缺失（非关键） | 卡片 + 标注缺失项 + "ℹ️ 以下项未满足" |
| **BLOCKED** | 关键项缺失（无 grading / 无 report） | 纯文本告警 + 说明阻断原因 |

**7 项 Gate 检查**（主调度器在发送前执行，不是建议是强制）：

```
G1: per-eval 结果表存在？（按类型分组 + 断言通过率）
G2: 断言统计存在？（exact/semantic/existence）
G3: 质量指标存在？（A1-A3/C1-C5/E3/V1-V8）
G4: Delta 存在？（有值或有明确 N/A+原因）
G5: 评级+决策+总耗时存在？
G6: HTML 报告链接存在？（standard/full 模式）
G7: 所有权已转让？（standard/full 模式）
```

**规则**：
- G1-G5 为所有模式必须
- G6-G7 仅 standard/full 必须（smoke/quick 自动 pass）
- 任何 Gate 失败 → 状态不能写 COMPLETE
- session.json 写入 `verdict.completion_status: "COMPLETE"|"PARTIAL"|"BLOCKED"`
- 消息中必须显示状态（不能隐藏 PARTIAL/BLOCKED）

---

---

## 卡片末尾“查看完整详情”入口

所有模式的最终结果卡片末尾必须保留 HTML 报告链接：

```
📎 查看完整详情：{report_html_url}
（包含所有 eval 的完整断言详情、evidence 引用、趋势图）
```

此链接为「通过折叠」策略的补充——用户想看通过用例的完整断言时，点击此链接即可。

---

*v1.2 · 2026-05-03 · 新增通过折叠/失败展开策略 + HTML报告入口*
*v1.1 · 2026-05-02 · 新增 Delta 数据来源说明 + 发送前自检清单*
