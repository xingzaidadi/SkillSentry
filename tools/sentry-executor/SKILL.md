---
name: sentry-executor
description: >
  执行 AI Skill 测试用例，输出带 transcript 的执行结果。需要先有 evals.json（可用 sentry-cases 生成）。
  触发场景：说"跑测试用例"、"执行eval"、"运行这些用例"、"帮我跑一下"、
  "测试结果出来了吗"、"执行用例然后评分"。
  不触发场景：只设计用例（用 sentry-cases）、只看报告（用 sentry-report）、要做完整流程（用 SkillSentry）。
---

# sentry-executor · Skill 测试用例执行层（Layer 1）

读取 evals.json，执行所有测试用例（with_skill，视模式决定是否含 without_skill），输出带 transcript 的执行结果。

**执行策略**：支持两种模式，自动选择：
- **subagent 模式**（默认）：每个 eval 启动轻量 subagent（lightContext + 预编译），保留 AI 判断能力
- **direct 模式**（降级兜底）：subagent 超时/失败时，AI 在主会话中直接执行兜底

**前置条件**：workspace_dir 下必须存在 `evals.json`（可由 sentry-cases 生成）。

---

## 输入

- `workspace_dir`：本次测评工作目录（由调用方传入）
- `skill_path`：被测 SKILL.md 路径
- `mode`：执行模式（smoke/quick/standard/full/regression），决定运行次数和并发策略

单独调用时，从用户提供的路径或最近一次 session 目录读取。

---

## Step 0：飞书用例同步（PULL）

执行前调用 sentry-sync 操作一（PULL），将飞书中 active 用例合并到本地 evals.json：

```
检查 ~/.claude/skills/SkillSentry/config.json
  → 不存在：跳过，直接进入下一步
  → 存在：调用 sentry-sync PULL
    → 拉取飞书 active 用例，写入 inputs_dir/cases.feishu.json
    → 与 evals.json 合并（飞书 human 用例 + 本地 ai-generated 用例，飞书优先）
    → 输出：「🔄 已从飞书同步 [N] 条用例」
```

合并规则：
- 飞书中存在的用例（按 case_id 匹配）：使用飞书版本（人工已 review，优先级更高）
- 飞书中不存在的本地用例：保留（AI 生成的补充覆盖用例）
- 合并结果覆盖写入 evals.json，原 evals.json 备份为 evals.json.bak

---

## 用例筛选（regression 模式专属，必须在断点续跑前执行）

```
mode == "regression"：
  读取 evals.json，过滤出 source="external" AND tag="golden" 的用例
  → 若存在：只执行这些用例（golden set），输出「🎯 regression 模式：执行 [N] 个 golden 用例」
  → 若为空：输出告警并终止：
      ⚠️ regression 模式需要 golden 用例，但 evals.json 中没有 source="external" AND tag="golden" 的用例。
      请先在 inputs/<Skill名>/ 目录下放置 *.cases.md 外部用例文件，再运行 sentry-cases 生成 evals.json。

mode != "regression"：执行全部用例，跳过本节
```

**运行次数规则**（按 mode）：

| mode | 每用例运行次数 |
|------|-------------|
| smoke | 1 |
| quick | 2 |
| regression | 1 |
| standard | 3 |
| full | 3 |

---

## Step 0.5：预编译（主会话预读文件，subagent 不再读）

执行前，主会话一次性预读以下文件，后续所有 subagent 直接从 task 参数获取内容，不再自行读取文件：

```
1. 读取被测 SKILL.md → 缓存为 skill_content
2. 读取 evals.json → 缓存为 evals_list
3. 对每个 eval，构造 task 参数时直接注入 skill_content + eval.input
```

**收益**：每个 subagent 省 2-3 个 tool call（约 3-5s）。
**验证**：subagent transcript 中不应出现 `read(evals.json)` 或 `read(SKILL.md)` 的 tool call。

---

## 断点续跑检查（执行前必须先做）

启动前扫描 `workspace_dir/eval-*/` 目录，检测已有产物：

```
单次运行模式（smoke/regression）：
  对每个 eval-N：
    eval-N/with_skill/outputs/transcript.md 存在 AND 非空 → 标记为"已完成"
    否则 → 标记为"待执行"

多次运行模式（quick/standard/full）：
  对每个 eval-N 的每个 run-R：
    eval-N/run-R/with_skill/outputs/transcript.md 存在 AND 非空 → 该 run 标记为"已完成"
    否则 → 标记为"待执行"
  所有 run 均完成 → eval-N 标记为"已完成"
  部分完成 → 列出待执行的 run（如「eval-2 run-2 待执行」）
```

有任何"已完成"用例时，输出提示：

```
⚡ 检测到上次执行记录：
  已完成：eval-1, eval-3, eval-5（共 3 个）
  待执行：eval-2, eval-4（共 2 个）

选项：
  [跳过已完成，只跑剩余] ← 默认，30 秒后自动选择
  [全部重跑]
```

30 秒无响应自动选「跳过已完成」。全部重跑时清空已有 transcript 文件再执行。

**自动模式**：prompt 中含 `自动` 或 `--ci` 时，跳过等待，立即选「跳过已完成」。

---

## 工作目录约定

**单次运行（smoke / regression，mode 运行次数 = 1）**：
```
workspace_dir/
├── evals.json
├── eval_environment.json
└── eval-N/
    ├── with_skill/outputs/
    │   ├── transcript.md
    │   ├── response.md
    │   └── metrics.json
    ├── without_skill/workspace/outputs/
    │   ├── transcript.md
    │   ├── response.md
    │   └── metrics.json
    ├── timing_with.json
    ├── timing_without.json
    └── grading.json                ← 由 grader 填写
```

**多次运行（quick=2次 / standard/full=3次）**：
```
workspace_dir/
├── evals.json
├── eval_environment.json
└── eval-N/
    ├── run-1/
    │   ├── with_skill/outputs/
    │   │   ├── transcript.md
    │   │   ├── response.md
    │   │   └── metrics.json
    │   ├── without_skill/workspace/outputs/
    │   │   ├── transcript.md
    │   │   └── response.md
    │   ├── timing_with.json
    │   ├── timing_without.json
    │   └── grading.json            ← 由 grader 填写
    ├── run-2/
    │   └── ...（同 run-1 结构）
    └── run-3/                      ← 仅 standard/full
        └── ...
```

> subagent 启动时，工作目录传入 `eval-N/run-R/`；单次运行时传入 `eval-N/`（无 run-R 层）。

**❗ 文件写入必须用绝对路径**：subagent prompt 中必须注入输出目录的绝对路径（如 `/root/.openclaw/skills/SkillSentry/sessions/xxx/eval-1/with_skill/outputs/`）。相对路径会导致 subagent 写到错误位置，产生「完成但没写文件」的问题。

---

## 每批启动前必须输出的声明（不声明禁止发出 subagent 调用）

```
【批次启动声明 · Batch-N】
执行模式：[subagent / direct]
用例：eval-[X]（共 1 个）
skill_type=[类型] | skip_without_skill=[true/false]
without_skill steps 上限：[8/6/5]（skill_type=[类型]）/ N/A（全部跳过）✓
without_skill 早退指令：[已注入 / N/A（全部跳过）] ✓
without_skill 策略：[全部跳过（mcp_based + smoke/quick 模式）/ 正常双侧执行（其他）] ✓
降级策略：[超时 180s 自动降级 direct / N/A（无降级）] ✓
```

声明写出后，在**同一消息**中发出 Agent 工具调用（subagent 模式）或启动 exec（direct 模式）。

---

## skip_without_skill 检查

**自动跳过规则**：

```
mcp_based + 任何模式：skip_without_skill = true
  → 原因：无 skill 指导时 AI 不知道调哪个 MCP 工具，Δ 数据无参考价值
  → 报告标注：Δ=N/A（设计决策：mcp_based 跳过 without_skill）

其他 skill_type：
  smoke/quick/regression：视 evals.json 中 skip_without_skill 字段
  standard/full：默认 skip_without_skill = false（保留 Δ 数据）
```

读取 evals.json 中每个用例的 `skip_without_skill` 字段：
- `true`：只启动 with_skill，在声明中注明「eval-[N] without_skill 已跳过」
- `false` 或不存在：正常启动双侧
- **手动覆盖**：用户明确要求出 Δ 时，可设 skip_without_skill: false 强制双侧执行

---

## 执行策略选择

Executor 使用 subagent 模式（通过 `sessions_spawn` 启动子代理），并应用以下优化：

### subagent 启动优化

```
sessions_spawn(
  mode: "run",
  lightContext: true,      ← 第 2 层：轻量启动，跳过工作区文件
  task: "[  ← 第 1 层：预编译内容直接注入
    固定前缀（SKILL.md + 规范）
    +
    变量后缀（eval_id + input + 输出路径）
  ]",
  runTimeoutSeconds: 180   ← 超时后触发降级
)
```

### with_skill prompt 构造规范（触发 prompt cache）

prompt 必须按以下顺序组织，**固定前缀放最前，变量放最后**，以触发模型提供商的 prompt prefix cache：

```
[固定前缀 · 所有 eval 完全相同，可缓存]
你是 SkillSentry Executor subagent。

## 被测 SKILL.md
{skill_content}    ← 主会话预读，直接注入

## transcript 格式规范
[tool_calls] Step N: <工具名>
Tool: <exact_tool_name>
Args: <完整 JSON>
Return: <完整返回值>
Status: success | error | timeout

## 执行规则
1. 按 SKILL.md 指导处理用户输入
2. 所有工具调用记录到 transcript.md
3. 最终回复写入 response.md
4. 文件必须写入指定的绝对路径

[变量后缀 · 每个 eval 不同，放最后]
## 本次任务
eval_id: {eval_id}
用户输入: {eval_input}
输出路径: {absolute_output_path}/
```

**注意**：prompt cache 是 Claude API 特有优化，其他模型提供商可能无效（但不会出错）。

### 降级规则

当 subagent 超时或失败时，Executor AI 直接在主会话中执行该用例（direct 降级），而不是再次启动 subagent。详见「超时降级机制」章节。

---

## 并发适配（动态探测）

### Step 0.8：网关并发探测（首次执行时自动运行）

```
1. 同时 spawn 2 个轻量 subagent：
   sessions_spawn(mode: "run", lightContext: true,
     task: "exec: echo ok > /tmp/probe_1.txt，然后回复 done",
     runTimeoutSeconds: 30)

2. 记录完成时间：
   - 两个都在 15s 内完成 → gateway_concurrency >= 2
   - 一个完成后另一个才开始 → gateway_concurrency = 1
   - 两个都超时 → gateway_concurrency = 0（网关异常，退回串行）

3. 写入 eval_environment.json：
   {"gateway_concurrency": N, "probe_time": "ISO时间"}

4. 整个测评期间只探测一次，结果缓存
```

### 批次大小（由探测结果决定）

```
gateway_concurrency = N

smoke/regression：每批 N 个 eval
quick：每批 N 个 eval，每 eval 的 run1+run2 同批（mega-batch 保留）
standard/full：每批 N 个 eval，run 分批

探测失败或未探测 → 默认 N=1（串行）
```

- 利用断点续跑加速（已完成的跳过）
- direct 降级天然串行，不受影响

---

## Executor subagent steps 上限

| Skill 类型 | with_skill | without_skill |
|-----------|-----------|--------------|
| mcp_based | 15 steps | 8 steps |
| code_execution | 10 steps | 6 steps |
| text_generation | 5 steps | 5 steps |

---

## without_skill subagent prompt 构造

**❗ 不注入被测 SKILL.md**：without_skill 测的是「没有 skill 指导时的自然行为」，注入 SKILL.md 违背测试目的。

**沙箱隔离声明（所有 skill_type 通用，必须注入）**：
```
你的工作目录是 {absolute_output_path}/without_skill/workspace/，禁止读取 with_skill/ 下的任何文件。
所有操作必须独立完成，不能复用 with_skill 的任何结果。
你的目标是展示没有 Skill 指导时的自然行为。

【沙箱隔离自检 - 执行完成后写入 response.md 末尾】：
1. 我是否读取了 eval-N/with_skill/ 目录下的任何文件？（是/否）
2. 我使用的所有结果，是否全部由本次独立执行产生？（是/否）
如果任何一项答案为「是」：标注「⚠️ 沙箱隔离违规：本次结果无效」
```

**早退 + 计数指令（仅 mcp_based / code_execution，text_generation 跳过）**：
```
遇到以下任一关键失败点时，立即停止：
- mcp_based：路由选择错误 / 必填字段缺失 / 权限校验失败 / 流程中断无法继续
- code_execution：命令执行报错且无法恢复 / 必要文件生成失败

【工具调用自计数】每次调用工具前累加次数（从0开始），达到上限立即停止：
- mcp_based：6 次    code_execution：5 次
「[STOPPED: tool_call_limit_reached, calls=[N]]」
```

**text_generation without_skill 目标说明（text_generation 专用，替换早退指令）**：
```
你的目标是在没有任何 Skill 指导的情况下，用自然方式回答以下问题：
[eval_prompt]

正常生成回复即可，不受 Skill 规则约束。完成后将完整回复写入 response.md。
```

---

## transcript 格式规范

```markdown
## [tool_calls] Step N: <工具名>
Tool: <exact_tool_name>
Args: <完整 JSON，原样复制>
Return: <完整返回值，原样复制>
Status: success | error | timeout

## [agent_notes] Step N: <简短标题>
解读：<AI 对上一步的解释>
```

**强制规则**：`[tool_calls]` 区块内容一字不改原样复制，禁止在其中添加 AI 解释语句。

---

## 时间与 Token 采集

每个 subagent 完成后**立即**写入 `timing_with.json` / `timing_without.json`（字段：`executor_start_ms`、`executor_end_ms`、`duration_ms`、`total_tokens`、`input_tokens`、`output_tokens`）。
task notification 是一次性事件，不可事后补填。

---

## 批次完成后并行度审计（自动执行）

每批所有 subagent 完成后，计算并行度：

```python
# 跳过条件：该批所有用例均 skip_without_skill=true（无 without_skill 侧，无需对比）
if all(eval.skip_without_skill for eval in batch):
    write eval_environment.json: parallelism_audit = "N/A (all evals skip_without_skill)"
    continue  # 不触发任何告警规则

start_gap = abs(eval.with_skill.start_ms - eval.without_skill.start_ms)
parallel = start_gap <= 30_000  # 30秒内视为并行
batch_parallel_rate = parallel_count / total_count
```

写入 `workspace_dir/eval_environment.json` 的 `parallelism_audit` 字段。

触发规则（仅当存在双侧用例时）：
- ≥ 80%：正常继续 ✓
- 50-80%：下批次额外输出并行率警告
- < 50%：暂停，列出所有串行用例 start_gap，询问用户是否继续

---

## 指标提取（执行完成后自动执行）

每个用例的 transcript 生成后，自动从 transcript 中提取以下指标原始数据，写入各用例目录下的 `metrics_raw.json`：

| 指标 | 提取方式 | 数据来源 | 实现状态 |
|------|---------|---------|----------|
| A1 触发命中 | transcript 中是否出现 Skill 核心工具的 tool_calls | `[tool_calls]` 区块 | ✅ |
| A2 崩溃率 | 是否有 abnormal_stop、error、空响应 | `[tool_calls]` Status 字段 | ✅ |
| A3 响应率 | response.md 是否非空且非超时 | response.md 文件 | ✅ |
| C1 工具完整率 | tools_required 是否都在 tools_called 中 | evals.json `tools_required` + transcript | 🔧 需 evals.json 有该字段 |
| C2 工具越界率 | tools_forbidden 是否出现在 tools_called 中 | evals.json `tools_forbidden` + transcript | 🔧 需 evals.json 有该字段 |
| C4 副作用率 | 是否有非预期的写操作（write/delete/patch/create/update/submit） | `[tool_calls]` Tool 名称 | 🔧 |
| C5 参数正确率 | critical_params 中的参数值是否匹配 | evals.json `critical_params` + transcript Args | 🔧 需 evals.json 有该字段 |
| E3 效率达标率 | Token ≤ 100,000 且耗时 ≤ 120s | timing_with.json | ✅ |

**C3、C6、E1 由 Grader 判定**，不在 executor 里提取。
**E2 由 report 跨轮次汇总**，不在 executor 里提取。

### metrics_raw.json 格式

```json
{
  "eval_id": "eval-1",
  "A1_triggered": true,
  "A1_tools_called": ["queryExpenseItems", "saveExpenseDoc"],
  "A2_has_crash": false,
  "A2_error_count": 0,
  "A3_has_response": true,
  "A3_response_length": 1245,
  "C1_tools_complete": true,
  "C1_missing_tools": [],
  "C2_tools_violated": false,
  "C2_violation_tools": [],
  "C4_has_side_effect": false,
  "C4_unexpected_writes": [],
  "C5_params_correct": true,
  "C5_param_mismatches": [],
  "E3_token_total": 45000,
  "E3_duration_s": 12.3,
  "E3_efficient": true
}
```

**向后兼容**：如果 evals.json 中没有 tools_required / tools_forbidden / critical_params 字段，对应指标标记为 `null`（不是 false），表示“无法判定”而非“未通过”。report 统计时跳过 null 值的指标。

**失败处理**：指标提取失败不影响用例执行结果，仅在 metrics_raw.json 中标记 `"extraction_error": "<原因>"`。

---

## 超时降级机制（subagent → 主会话直跑）

当 subagent 超时或失败时，Executor AI 在主会话中直接执行该用例（不再启动新 subagent）。

### 降级触发条件

1. **subagent 超时**：`sessions_spawn` 后等待 `runTimeoutSeconds`（默认 180s）无响应
2. **subagent 返回空 transcript**：task 完成但 `eval-N/with_skill/outputs/transcript.md` 不存在或为空
3. **subagent 异常退出**：task 返回错误状态

### 降级不触发的场景

- subagent 返回错误但有 transcript（记录错误即可，不降级）
- text_generation 类型（必须 AI 执行，无法主会话直跑）

### 降级执行流程（Executor AI 在主会话中执行）

```
1. 输出：「⚠️ eval-N subagent 超时，降级到主会话直跑」
2. 读取被测 SKILL.md
3. 读取 evals.json 中 eval-N 的 input
4. 在主会话中直接调用工具（feishu_* 等）执行用例
5. 将工具调用过程写入 transcript.md（绝对路径）
6. 将最终回复写入 response.md
7. transcript 开头标注：「⚠️ 降级执行：主会话直跑（非 subagent）」
8. timing_with.json 标记 "mode": "direct_fallback"
9. 继续下一个 eval
```

### 降级后的 grading 处理

- 降级用例的 metrics_raw.json 标记 `"direct_fallback": true`
- grading 时：A1/A2/A3/E3 正常评分，C3/C6 标记为 `null`（非 subagent 执行，无法评判 skill 指导效果）
- report 中单独统计降级比例：`direct_fallback_rate = N/total`

---

## 执行完成后的输出

```
✅ 执行完成
📊 完成：[N] 个用例 × [R] 次运行
⏱️ 总耗时：约 [X] 分钟
🔄 执行模式：[subagent / direct / 混合（subagent + N 个降级 direct）]
📊 指标采集：✅ A1/A2/A3/E3 已提取 | 🔧 C1/C2/C4/C5 视 evals.json 字段 | ⏳ C3/C6/E1/E2 待 Grader/Report

下一步：
  评分 → 使用 SkillSentry 内置 Grader，或说「帮我评审这批结果」
  报告 → 先运行 Grader，再使用 sentry-report
```
