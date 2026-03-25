# execution-phases.md — 阶段三 & 阶段四 详细执行规范

> 由 SkillSentry 主文件在阶段三开始时加载。阶段零~二无需读取本文件。

---

## 阶段三：测试用例设计

**核心逻辑：双源合流**
1. **注入外部用例**：优先加载阶段零发现的「外部用例」，标记为「[外部导入]」。
2. **AI 补齐设计**：根据当前模式的覆盖率目标，针对外部用例未覆盖的路径，AI 自动设计补齐用例。
3. **一致性检查**：确保所有导入的断言符合 Layer 2/3 的评审规范。

**断言强度分级（P1 必须执行）**：

每条断言在设计时必须标注 `precision` 字段，这决定了它在通过率计算中的权重：

| 强度级别 | `precision` 值 | 定义 | 示例 |
|---------|--------------|------|------|
| 精确断言 | `exact_match` | 有具体可验证的字段值/计数/格式，失败风险真实存在 | `saveExpenseDoc 入参 docStatus="10"` |
| 语义断言 | `semantic` | 需要理解语义才能判断，存在主观空间 | `输出的报销主题描述清晰完整` |
| 存在性断言 | `existence` | 只验证某内容存在/不存在，无 Skill 也大概率通过 | `输出非空` / `没有编造发票` |

> **为什么要区分断言强度**：如果所有断言都是"输出非空"这种 existence 级别，那么有没有 Skill 结果都差不多，测评失去意义。精确断言才是真正衡量 Skill 价值的指标，应占主体。

**通过率拆分规则**：
- `精确通过率` = exact_match 断言通过数 / exact_match 断言总数（**这才是核心质量指标**）
- `语义通过率` = semantic 断言通过数 / semantic 断言总数（参考）
- `综合通过率` = 全部断言通过数 / 全部断言总数（兼容旧逻辑，显示时标注构成）

**准入阈值应用 `精确通过率`**：对照 admission-criteria.md 的通过率要求，以 `精确通过率` 为准。`existence` 断言不计入准入判断。

**断言设计自检（每条断言写完后必须过一遍）**：
```
□ 这条断言如果没有 Skill，会不会照样通过？→ 是 → precision = existence，注明原因
□ 这条断言的 PASS/FAIL 标准是否唯一确定？→ 否 → 改写为更具体的描述
□ 这条断言对应 SKILL.md 中的哪条规则？→ 填写 rule_ref 字段
```

**纯文本 Skill 的用例设计补充规则**（当 `skill_type = "text_generation"` 时）：

纯文本 Skill 没有工具调用，断言必须聚焦在**可验证的输出内容**上，避免不可量化的主观描述：

| 断言类型 | 好的写法 | 坏的写法 |
|---------|---------|---------|
| 格式规范 | "输出包含三级标题结构，H1/H2/H3 层次清晰" | "格式看起来不错" |
| 内容完整性 | "输出覆盖了用户问题的全部 3 个子问题" | "回答比较完整" |
| 规则遵守 | "回复长度在 200 字以内（SKILL.md 要求简洁）" | "回复很简洁" |
| 负向断言 | "输出没有包含用户明确说不需要的代码示例" | "没有多余内容" |
| 边界行为 | "当输入为空时，Skill 提示用户补充信息而非直接执行" | "处理了异常输入" |

---

## 阶段四：分组流式执行（四层验证体系）

### Layer 0：执行模式分发

根据阶段零检测的 `skill_type`，自动选择执行模式：

```
mcp_based      → 标准模式：真实 MCP 工具调用，记录完整 tool_call transcript
code_execution → 代码模式：真实 Bash/脚本执行，记录命令输出
text_generation → 纯文本模式：subagent 生成文本输出，记录完整 response
```

**纯文本模式的执行规范**：
- with_skill subagent：加载 SKILL.md 后执行用例 prompt，输出保存到 `response.md`
- without_skill subagent：不加载任何 Skill，直接执行相同 prompt，输出保存到 `response.md`
- transcript 内容：完整的推理过程 + 最终输出（无工具调用时，记录模型的思考链和输出）
- **注意**：纯文本模式下 `execution_metrics.total_mcp_calls` 填 0，不影响 Grader 判断

### Layer 1：Executor — 真实执行，记录 transcript

每个用例同时派出两个 subagent（with_skill + without_skill）并行启动。

**启动 without_skill subagent 时必须在 prompt 中注明**：
```
你的工作目录是 eval-N/without_skill/workspace/，禁止读取 eval-N/with_skill/ 下的任何文件。
所有操作（文件上传、中间产物）必须独立完成，不能复用 with_skill 的任何结果。
```

**transcript 格式规范（P2 双分离结构）**：

transcript.md 必须严格区分两类内容，**不允许混写**：

```markdown
## [tool_calls] Step N: <工具名>
<!-- 原始工具调用日志，禁止添加 AI 注释 -->
Tool: <exact_tool_name>
Args: <完整 JSON 入参，原样复制，不得修改>
Return: <完整返回值，原样复制，不得修改>
Status: success | error | timeout

## [agent_notes] Step N: <简短标题>
<!-- AI 主观解释区，清晰标注这是 AI 解读而非原始数据 -->
解读：<AI 对上一步工具调用结果的解释，或流程决策的说明>
```

> **为什么要双分离结构**：混写会导致 Grader 评审时无法区分"真实执行结果"和"AI 的自我解读"，从而产生误判。`[tool_calls]` 区块是客观证据，`[agent_notes]` 是主观分析，两者的可信度权重不同。

**强制规则**：
- `[tool_calls]` 区块内容来自真实 MCP/Bash 返回，**一字不改**原样复制
- `[agent_notes]` 区块是 AI 的主观解释，Grader 评审时**降权使用**（只作辅助参考，不作 PASS 的主要 evidence）
- 禁止在 `[tool_calls]` 区块内添加「按任务要求自动选择...」之类的 AI 解释语句

**时间与 Token 采集（所有模式必须执行）**：

每个 subagent 执行完毕后，立即记录以下指标到 `timing.json`：
```json
{
  "executor_start_ms": 1711234567000,
  "executor_end_ms": 1711234573500,
  "duration_ms": 6500,
  "total_tokens": 2340,
  "input_tokens": 1200,
  "output_tokens": 1140
}
```
这些数据来自 task notification 的 `total_tokens` 和 `duration_ms` 字段，**必须在 subagent 完成时立即保存**，不可事后补填。

> **为什么必须立即保存**：task notification 是一次性事件，完成后无法回溯。事后补填只能靠估算，会污染效率指标数据，影响 P95 响应时间的准确性。

### Layer 2：独立评审与精确校验

- **Layer 2a**：字段精确校验（Ground Truth）
- **Layer 2b**：独立 Grader 评审（根据 transcript 判卷）

**纯文本模式下的 Grader 特别说明**：当 `skill_type = "text_generation"` 时，Grader 使用 `agents/grader.md` 中的「纯文本评审规范」章节，而非 MCP transcript 验证标准。

### Layer 3：盲测对比与根因分析

- **Comparator**：盲测对比两个输出的质量胜负。
- **Analyzer**：定位胜负原因，生成改进建议。

---

## 阶段五：生成报告与发布决策

### 测评模式运行次数规范（P3）

每种模式的运行次数下限是为了保证基本的可重现性判断：

| 模式 | 覆盖率目标 | 每用例最少运行次数 | 稳定性判断 |
|------|----------|----------------|----------|
| **quick** | ≥ 40% | **2 次** | 两次通过率差距 > 15% → 报告标红「结果不稳定」，建议升级 standard |
| **standard** | ≥ 70% | 3 次 | 计算 Stddev，对照准入阈值 |
| **full** | ≥ 90% | 3 次 | 计算 Stddev，对照准入阈值（S/A 级要求 < 0.05） |

> **为什么 quick 模式固定跑 2 次**：单次执行存在随机性，2 次能检测结果是否稳定，且不显著增加测评时间。如果两次差距 > 15%，说明 Skill 本身存在不稳定性，这比通过率更值得关注。

**quick 模式 2 次运行的处理规则**：
- 两次通过率均值作为最终通过率（不是取最优）
- 两次差距 = |run1_pass_rate - run2_pass_rate|
- 差距 > 15%：报告关键指标区域标红，标注「⚠️ 结果不稳定（两次差距 [X]%），建议升级 standard 模式」
- 差距 ≤ 15%：正常展示，标注「quick 2次」

### 发布准入标准 (Admission Criteria)

| 指标 | S级 | A级 | B级 | C级 |
|------|-----|-----|-----|-----|
| 通过率 | ≥ 95% | ≥ 90% | ≥ 80% | ≥ 70% |
| 增益 (Δ) | > 0 | > 0 | ≥ -5% | - |
| 触发率（AI估算） | TP ≥ 80% | TP ≥ 80% | TP ≥ 70% | 参考 |
| P95 响应时间 | < 15s | < 15s | < 30s | < 30s |

**触发率说明**：触发率为 AI 模拟估算，按以下规则处理：

| 情况 | S/A 级处理 | B/C 级处理 |
|------|----------|----------|
| TP 估算 ≥ 80%，置信度 high/medium | 正常（参考值，标注）| 正常 |
| TP 估算 ≥ 80%，置信度 low | **强制降为 CONDITIONAL PASS**，注明「触发率估算置信度不足，建议精确测量」 | 警告标注 |
| TP 估算 70-80% | 警告标注，建议优化 description | 警告标注 |
| TP 估算 < 70% | **强制降为 CONDITIONAL PASS**，注明「触发率估算不足，须优化 description 后重测」 | 同左 |
| TN 有误触发预测 | **强制降为 CONDITIONAL PASS**，标红 | 警告标注 |

> 精确测量路径（适用于 S/A 级正式发布前）：使用 skill-creator run_eval.py（需 claude CLI）。

### 报告中新增章节

在现有报告结构后，追加「触发率预评估」章节：
```
十一、触发率预评估（AI 模拟）
  - TP 估算触发率：[XX]%（[N]/[N] 条应触发场景）
  - TN 估算不触发率：[XX]%（[N]/[N] 条不应触发场景）
  - 边界情况：[N] 条，其中 [N] 条 uncertain
  - 整体置信度：[high/medium/low]
  - ⚠️ 免责声明：此为 AI 模拟估算，精确数据需 skill-creator run_eval.py
```

**效率层指标汇总**（来自 timing.json 聚合）：
```
十二、效率指标
  - P50 响应时间：[XX]ms
  - P95 响应时间：[XX]ms（准入阈值：[XX]s）
  - 平均 Token 消耗：[XX] tokens/用例
  - Token 效率比：[Δ通过率 / 额外Token消耗]
```
