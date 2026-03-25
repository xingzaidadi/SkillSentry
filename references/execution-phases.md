# execution-phases.md — 阶段三 & 阶段四 详细执行规范

> 由 SkillSentry 主文件在阶段三开始时加载。阶段零~二无需读取本文件。

---

## 阶段一（速度优化）：触发率测评的跳过规则

触发率 AI 模拟需要生成并评估 10 条 prompt，耗时约 2-3 分钟。按以下规则决定是否执行：

| 测评模式 | 默认行为 | 用户可覆盖 |
|---------|---------|---------|
| **quick** | **跳过触发率测评**，直接进入阶段三 | 用户明确说「需要触发率」时执行 |
| **standard** | 执行触发率测评 | 用户明确说「跳过触发率」时跳过 |
| **full** | 强制执行，不可跳过 | — |

quick 模式跳过时，报告第十一章标注：「触发率预评估已跳过（quick 模式默认优化）。升级 standard 模式可启用。」

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

**⚡ 强制并行规则（速度关键约束）**：

每个用例的 with_skill 和 without_skill **必须在同一批次同时启动**，不得串行。

```
❌ 错误做法（串行，时间 × 2）：
   eval-1 with_skill → 等完成 → eval-1 without_skill → 等完成 → eval-2 ...

✅ 正确做法（并行，时间不变）：
   同时启动：eval-1 with_skill + eval-1 without_skill（并行）
   同时启动：eval-2 with_skill + eval-2 without_skill（并行）
   ...
   所有用例可分批并行，每批 2-3 个用例同时执行，取决于资源限制
```

**分批并行策略**：
- 每批同时执行 2-3 个用例（共 4-6 个 subagent 并行）
- 一批完成后立即启动 Grader 批量评审该批次，同时启动下一批 Executor
- Executor 和 Grader 的执行形成流水线（pipeline），而非等所有 Executor 完成再启 Grader

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

**⚡ Grader 批量评审规则（速度关键约束）**：

Grader 不得逐用例单独调用。每批 Executor 完成后，**一次性**将该批次所有用例的 transcript 传给 Grader 统一评审：

```
❌ 错误做法（逐用例，N次冷启动）：
   启动 Grader-1（评 eval-1）→ 启动 Grader-2（评 eval-2）→ ...

✅ 正确做法（批量，1次冷启动）：
   启动 Grader（同时评 eval-1 + eval-2 + eval-3 的 transcript）
   → 输出 grading-1.json + grading-2.json + grading-3.json
```

**批量评审的 prompt 结构**：
```
你需要评审以下 [N] 个用例的 transcript，逐一输出 grading.json：

用例 1：eval-1
transcript 路径：[路径]
expectations：[断言列表]

用例 2：eval-2
...

请按用例顺序依次输出 grading-1.json、grading-2.json...
```

> **为什么批量评审能节省时间**：每次启动 Grader subagent 有约 10-30 秒的冷启动开销（API 初始化 + SKILL.md 加载）。10 个用例逐个评审 = 10 次冷启动；批量评审 = 1-2 次冷启动。

**纯文本模式下的 Grader 特别说明**：当 `skill_type = "text_generation"` 时，Grader 使用 `agents/grader.md` 中的「纯文本评审规范」章节，而非 MCP transcript 验证标准。

### Layer 3：盲测对比与根因分析

**⚡ Comparator/Analyzer 范围限定（速度关键约束）**：

Layer 3 **仅对以下类型的用例运行**，其他类型跳过：
- `happy_path`（正常路径用例）
- `e2e`（端到端用例）

```
❌ 对所有用例跑 Comparator（浪费时间）
✅ 仅对 happy_path + e2e 用例跑 Comparator

quick 模式（8-10 个用例）中，happy_path + e2e 通常 2-3 个
→ Comparator 只运行 2-3 次，而非 8-10 次
```

> **为什么不对所有用例跑 Comparator**：Comparator 的核心价值在于发现「主流程」上 with_skill vs without_skill 的质量差异。边界/负向/鲁棒性用例的对比意义有限（这些场景下 without_skill 本来就表现差），做了也是噪音。

- **Comparator**：盲测对比两个输出的质量胜负。
- **Analyzer**：定位胜负原因，生成改进建议。

---

## 阶段五：生成报告与发布决策

### 测评模式运行次数规范（P3）

每种模式的运行次数下限是为了保证基本的可重现性判断：

| 模式 | 覆盖率目标 | **用例数上限** | 每用例最少运行次数 | 稳定性判断 |
|------|----------|------------|----------------|----------|
| **quick** | ≥ 40% | **8-10 个** | **2 次** | 两次通过率差距 > 15% → 报告标红「结果不稳定」，建议升级 standard |
| **standard** | ≥ 70% | 20-25 个 | 3 次 | 计算 Stddev，对照准入阈值 |
| **full** | ≥ 90% | 30-35 个 | 3 次 | 计算 Stddev，对照准入阈值（S/A 级要求 < 0.05） |

> **quick 模式用例数控制在 8-10 个的理由**：quick 模式的核心价值是「快速反馈」。超过 10 个用例后，每新增一个用例带来的覆盖率收益递减（因为主要路径已被前 8 个覆盖），但时间线性增加。8-10 个用例约覆盖 40-50% 路径，足够完成冒烟测试。

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
