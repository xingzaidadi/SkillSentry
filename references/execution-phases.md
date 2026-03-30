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

**⚡ 触发率预评估使用 `explore` subagent**：

触发率预评估是纯文本分析任务（读 description + 生成判断），使用 `explore` subagent 即可，无需 `general`。

---

## 阶段三：测试用例设计

**⚡ 阶段零规则提炼和阶段三用例设计：优先使用轻量模型**

规则提炼（阶段零）和用例设计（阶段三）是纯分析/生成任务，不需要执行任何工具，不需要强推理能力。

如果用户在 `opencode.json` 中配置了轻量模型（如 `claude-haiku-4`），SkillSentry 应在这两个阶段切换到该模型，对执行层（Layer 1）和评审层（Grader）仍使用默认能力模型：

```json
// 可选配置示例（opencode.json）
{
  "agent": {
    "skillsentry-analyst": {
      "description": "SkillSentry 分析层：规则提炼和用例设计，使用轻量模型",
      "mode": "subagent",
      "model": "anthropic/claude-haiku-4-20250514",
      "hidden": true,
      "steps": 20,
      "permission": { "edit": "allow", "bash": "deny" }
    }
  }
}
```

> **来源**：Anthropic《Building effective agents》Routing 章节：*"Routing easy/common questions to smaller, cost-efficient models like Claude Haiku 4.5"*。规则提炼和用例设计属于"结构化分析"类任务，轻量模型完全胜任，且速度通常快 2-3 倍。

**未配置轻量模型时**：阶段零和阶段三使用当前默认模型，不受影响，功能完整。

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
□ 这条规则涉及不可逆操作（写/提交/删除）？→ 是 → 检查是否有用户确认步骤断言
```

**Human-in-the-Loop 检查（P1，涉及不可逆操作时必须执行）**：

被测 Skill 凡包含写操作、提交、删除等不可逆动作，必须在用例设计阶段额外验证：

```
HiL-1：不可逆操作前是否有明确的用户确认步骤？
  → SKILL.md 中是否有"等待用户确认"、"询问是否继续"类指令？
  → 若无：标记 ⚠️，改进建议注明「缺少 Human-in-the-Loop 确认节点」

HiL-2：用户确认失败或超时时，是否有明确的中止逻辑？
  → 若无：标记 ⚠️，注明「确认节点无超时/拒绝处理逻辑」
```

> **依据**：Anthropic《Building effective agents》明确建议，Agent 在执行任何不可逆操作前应暂停等待人工确认。缺少此机制的 Skill 一旦误触发无法回滚，直接造成业务损失。

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
- 批次大小按模式区分：**quick 模式每批 4-5 个用例**（共 16-20 个 subagent 并行）；**standard/full 模式每批 2-3 个用例**（共 4-6 个 subagent，控制资源压力）
- 一批完成后立即启动 Grader 批量评审该批次，同时启动下一批 Executor
- Executor 和 Grader 的执行形成流水线（pipeline），而非等所有 Executor 完成再启 Grader

**⚡ quick 模式：两次运行合并为 mega-batch（速度关键约束）**：

quick 模式要求每用例运行 2 次，这两次必须**合并进同一 mega-batch** 同时启动，不得分两轮顺序执行：

```
❌ 错误做法（两轮串行，时间 × 2）：
   Round-1：[eval-1 run1 ×2侧] → [eval-2 run1 ×2侧] → ... → 全部完成
   Round-2：[eval-1 run2 ×2侧] → [eval-2 run2 ×2侧] → ... → 全部完成

✅ 正确做法（mega-batch，两轮时间塌缩为一轮）：
   批次A：[eval-1 run1 with] [eval-1 run1 without] [eval-1 run2 with] [eval-1 run2 without]
          [eval-2 run1 with] [eval-2 run1 without] [eval-2 run2 with] [eval-2 run2 without]
          ... 共 4-5 用例同时启动（16-20 subagent）
   批次B：剩余用例，同上
```

> **节省估算**：quick 模式 10 用例 × 2 次，原本需要 2 轮（每轮约 6-8 分钟）= 12-16 分钟；合并后只需 1 轮 ≈ 6-8 分钟。批次从 2 轮变 1 轮，Grader 冷启动次数也从 6-8 次降到 2-3 次。

**⚡ Executor subagent 的 steps 上限（防止过度迭代）**：

Executor subagent 启动时，必须根据 Skill 类型和执行侧分别设置 `steps` 上限：

| Skill 类型 | with_skill steps 上限 | without_skill steps 上限 | 理由 |
|-----------|----------------------|------------------------|------|
| `mcp_based` | **15 steps** | **8 steps** | with_skill 需完整跑完流程；without_skill 遇到首个关键失败即可停止，无需尝试恢复 |
| `code_execution` | **10 steps** | **6 steps** | 同上 |
| `text_generation` | **5 steps** | **5 steps** | 纯文本只需一次生成，两侧相同 |

> **为什么 without_skill 要单独设置更低的上限**：实测数据显示，without_skill 在复杂业务流程（如差旅报销）中会无目的地漫游尝试，消耗远超 with_skill 的 Token 和时间（实测 without_skill 耗时 1318s、42k tokens，而 with_skill 仅 770s、18.5k tokens）。without_skill 的测评目的是"证明没有 Skill 会更差"，并不需要它跑完整流程，遇到第一个关键失败点即可得出结论。

> **来源**：OpenCode 官方文档 `steps` 字段说明：*"Control the maximum number of agentic iterations an agent can perform before being forced to respond with text only."* 不设上限时，LLM 可能无限重试，既浪费时间又消耗 Token。

**启动 without_skill subagent 时必须在 prompt 中注明**：
```
你的工作目录是 eval-N/without_skill/workspace/，禁止读取 eval-N/with_skill/ 下的任何文件。
所有操作（文件上传、中间产物）必须独立完成，不能复用 with_skill 的任何结果。
你的目标是展示没有 Skill 指导时的自然行为。遇到以下任一关键失败点时，立即停止并输出当前结果，不要尝试恢复或绕过：
- 路由选择错误（如把差旅报销当日常报销处理）
- 必填字段缺失或格式错误导致 API 拒绝
- 权限校验失败
- 流程中断且无法继续（如找不到申请单）
记录失败原因后直接退出，这已足够评估 Δ。

【自检 — 执行完成后必须回答以下问题并写入 response.md 末尾】：
沙箱隔离自检：
1. 我是否读取了 eval-N/with_skill/ 目录下的任何文件？（是/否）
2. 我使用的所有 FDS URL 或上传结果，是否全部由本次独立执行产生？（是/否）
如果任何一项答案为"是"，立即在 response.md 末尾标注：「⚠️ 沙箱隔离违规：本次结果无效，请通知 SkillSentry 主 agent 标记 INVALID」
```

> **为什么加自检**：文件系统隔离规则依赖 AI 自觉遵守，缺乏系统级拦截。自检通过强制 AI 在执行结束时声明自己是否违规，让 Grader 在评审时能发现并标记被污染的测评结果，使违规行为可被追溯而非静默通过。

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

Grader 不得逐用例单独调用。每批 Executor 完成后，**一次性**将该批次所有用例的 transcript 传给 Grader 统一评审。

**⚡ Grader 使用 `explore` subagent 类型**：

Grader 是纯读取任务（只读 transcript，不写文件），使用 `explore` subagent 而非 `general`：

```
❌ subagent_type = "general"（有写文件能力，过重）
✅ subagent_type = "explore"（只读，更快，资源消耗少）
```

> **来源**：OpenCode 官方文档 explore subagent 说明：*"A fast, read-only agent for exploring codebases. Cannot modify files."* Grader 只需要读 transcript 和输出文件，无需任何写操作，explore 完全满足且速度更快。

**⚡ Grader 输入精简化（减少 Token 消耗）**：

Grader 批量评审时，**不传完整 transcript**，只传精简版本：

```
精简传输规则：
1. 只传 [tool_calls] 区块（跳过 [agent_notes]）
2. 跳过超过 500 字的完整 JSON 返回值，改传摘要：
   Return: {"code":"200","body":"a1b2c3d4",...} → 截断为前 200 字
3. 必须完整保留的部分：
   - 所有工具调用的名称（Tool: xxx）
   - 所有工具调用的入参（Args: ...）
   - 返回值的状态码和关键字段（如 fdId、code、status）
   - 最终 response.md 全文（这是断言验证的主要来源）
```

示例精简：
```markdown
[原始 transcript 约 8000 tokens]
         ↓ 精简后
[tool_calls] Step 1: queryExpenseApplier
Tool: mcp_queryExpenseApplier
Args: {"docApplierUsername":"zhangsan"}
Return: {"fdCompanyId":"abc","fdBankName":"招商银行"} [已截断]
Status: success

[tool_calls] Step 5: saveExpenseDoc
Tool: mcp_saveExpenseDoc
Args: {"docStatus":"10","expenseType":"1","fdApplyMoney":"168.00",...}
Return: {"code":"200","body":"a1b2c3d4"} [已截断]
Status: success

[精简后约 1500-2000 tokens]
```

> **为什么安全**：Grader 评审断言时，精确断言（exact_match）验证的是工具调用名称、入参字段值、返回状态码，这些全部保留。只截断的是冗余的完整 JSON 返回体（几百行）和 agent_notes 解释文字，这两类信息对断言判定没有实质贡献。

**批量评审的 prompt 结构**：
```
你需要评审以下 [N] 个用例的 transcript，逐一输出 grading.json：

用例 1：eval-1
transcript（精简版）：[见上方精简规则]
response.md：[完整内容]
expectations：[断言列表]

用例 2：eval-2
...

请按用例顺序依次输出 grading-1.json、grading-2.json...
```

> **为什么批量评审能节省时间**：每次启动 Grader subagent 有约 10-30 秒的冷启动开销（API 初始化 + SKILL.md 加载）。10 个用例逐个评审 = 10 次冷启动；批量评审 = 1-2 次冷启动。

**纯文本模式下的 Grader 特别说明**：当 `skill_type = "text_generation"` 时，Grader 使用 `agents/grader.md` 中的「纯文本评审规范」章节，而非 MCP transcript 验证标准。

### Layer 3：盲测对比与根因分析

**⚡ Comparator/Analyzer 范围限定（速度关键约束）**：

**smoke 模式完全跳过 Layer 3**：smoke 模式只做冒烟验证，不出具发布决策，Comparator 和 Analyzer 的增益分析没有意义，直接跳过。

其他模式，Layer 3 **仅对以下类型的用例运行**，其他类型跳过：
- `happy_path`（正常路径用例）
- `e2e`（端到端用例）

```
❌ 对所有用例跑 Comparator（浪费时间）
✅ 仅对 happy_path + e2e 用例跑 Comparator

quick 模式（8-10 个用例）中，happy_path + e2e 通常 2-3 个
→ Comparator 只运行 2-3 次，而非 8-10 次

smoke 模式：Layer 3 完全跳过，节省 1-3 分钟
```

> **为什么不对所有用例跑 Comparator**：Comparator 的核心价值在于发现「主流程」上 with_skill vs without_skill 的质量差异。边界/负向/鲁棒性用例的对比意义有限（这些场景下 without_skill 本来就表现差），做了也是噪音。

- **Comparator**：盲测对比两个输出的质量胜负。
- **Analyzer**：定位胜负原因，生成改进建议。

**⚡ Comparator/Analyzer 必须非阻塞启动（速度关键约束）**：

Comparator 和 Analyzer 是独立 subagent，启动后主流程**不得等待其完成**，应立即继续处理下一批用例：

```
✅ 正确做法（非阻塞）：
   Grader(batch-1) 完成 → 启动 Comparator(batch-1) [非阻塞，后台运行]
                         → 同时继续 Grader(batch-2) / Executor(batch-3)
   等所有批次和 Grader 全部完成后，进入阶段五前，再收集所有 Comparator/Analyzer 的结果

❌ 错误做法（阻塞）：
   Grader(batch-1) 完成 → 等 Comparator(batch-1) → 等 Analyzer(batch-1) → 才启动下一批
```

> **为什么安全**：阶段五（报告生成）只需要 Comparator/Analyzer 的输出（comparison.json / analysis.json），不影响其他批次的执行和 Grader 评审。只需在进入阶段五之前确认所有 Comparator/Analyzer 已完成即可。

---

## 阶段五：生成报告与发布决策

### 测评模式运行次数规范（P3）

每种模式的运行次数下限是为了保证基本的可重现性判断：

| 模式 | 覆盖率目标 | **用例数上限** | 每用例最少运行次数 | 稳定性判断 |
|------|----------|------------|----------------|----------|
| **smoke** | ≥ 20% | **4-5 个** | **1 次** | 仅判断核心路径是否崩溃，不出具发布决策 |
| **quick** | ≥ 40% | **8-10 个** | **2 次** | 两次通过率差距 > 15% → 报告标红「结果不稳定」，建议升级 standard |
| **standard** | ≥ 70% | 20-25 个 | 3 次 | 计算 Stddev，对照准入阈值 |
| **full** | ≥ 90% | 30-35 个 | 3 次 | 计算 Stddev，对照准入阈值（S/A 级要求 < 0.05） |

> **smoke 模式的适用场景**：Skill 开发迭代中修改了某条规则，只需验证"主流程没有崩"，不需要统计置信度。smoke 模式只跑 4-5 个 happy_path + 核心原子用例、每个只跑 1 次，**不出具 PASS/FAIL 发布决策**，仅输出「冒烟通过 / 冒烟失败」结论，适合高频开发循环使用。

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

### 阶段五额外执行 — 效率维度诊断（P2 级别）

> **学术依据**：Kapoor et al.（*AI Agents That Matter*, arXiv:2407.01502, 2024）指出：Agent 普遍过度复杂，准确率相近时成本差异可达数十倍。SkillSentry 将效率纳入测评，防止「功能正确但过度昂贵」的 Skill 上线。

在阶段五汇总指标时，额外执行以下三项效率诊断：

```
E-1：Token 消耗合理性
  额外 Token 消耗 = with_skill均值 - without_skill均值
  如果额外消耗 > 2000 tokens/用例 且 Δ < 10%：
    → 报告标注 ⚠️「Token 效率偏低：额外消耗 [X] tokens，增益仅 [X]%，建议精简 SKILL.md」

E-2：工具调用次数合理性（仅 mcp_based）
  如果平均调用次数 > 预期次数的 1.5 倍：
    → 报告标注 ⚠️「工具调用疑似冗余：平均 [X] 次，建议检查是否有重复调用」

E-3：复杂度自检
  复杂度得分 = SKILL.md行数/50 + 模块数×2 + 硬性规则数×0.5
  得分 > 20：报告标注 ⚠️「Skill 复杂度偏高（得分 [X]），建议评估是否可精简」
  得分 > 30：报告标注 ❌「Skill 过度复杂（得分 [X]），建议重构」
```

**冗余规则自检**（在报告改进建议章节输出）：
```
对被测 SKILL.md 中的每条 P1/P2 规则，问：
「如果删掉这条规则，会出现什么问题？」
如果答案是「可能没问题」→ 该规则是冗余候选，标注供人工复核。
```

---

## ⚡ 报告模板预加载（阶段四执行期间后台执行）

`references/report-template.md` 的读取**不得等到阶段五才触发**，应在以下时机提前加载：

```
触发时机：第一批 Executor 全部完成（即阶段四开始后约 1-2 分钟）时，
         在等待 Grader 评审的同时，后台读取 report-template.md 缓存到上下文。

等效于：
  阶段四执行中（后台）：read report-template.md  ←── 新增，并行不阻塞
  阶段四执行中（前台）：Grader 批量评审 batch-1
  ...
  阶段五开始时：report-template.md 已就绪，直接生成报告，无需等待文件读取
```

**节省估算**：report-template.md 读取约需 10-30 秒（文件较大），预加载后阶段五的启动延迟从 30-60 秒降到 < 5 秒。

> **安全性**：报告模板不依赖测评结果，任何时候读取内容都相同，提前加载不影响正确性。
