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

> 飞书同步 PULL 由主编排（SkillSentry）在调用 executor 前自动完成。单独调用 executor 时跳过同步。

```
检查 {skill-eval-测评根目录}/config.json
  → 不存在：跳过，直接进入下一步
  → 存在：由主编排自动完成（单独调用时跳过）
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

**❗ 文件写入必须用绝对路径**：subagent prompt 中必须注入输出目录的绝对路径（如 `{workspace_dir}/xxx/eval-1/with_skill/outputs/`）。相对路径会导致 subagent 写到错误位置，产生「完成但没写文件」的问题。

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

## MCP 执行后端适配

读取 session.json 的 `mcp_backend` 字段，自动选择工具调用方式：

| mcp_backend | 执行方式 | 说明 |
|-------------|---------|------|
| `native` | subagent 直接调用原生 MCP 工具 | openclaw.json 已配置，子 agent 可直接访问 |
| `mcporter` | 主会话通过 `exec` 调用 `HOME=/root/.openclaw mcporter call <server>.<tool>(params)` | mcporter 已配置，自带 OAuth 认证 |
| 未设置/空 | 降级为纯对话模式（不调用工具，仅验证路由逻辑） | MCP 不可用时的兑底 |

**mcporter 模式执行流程**：
```
1. subagent 负责「思考」：读 SKILL.md → 解析用户输入 → 决定调哪个 MCP/工具/参数
2. subagent 写出工具调用意图到 transcript（server + tool + params）
3. 主会话拦截，用 mcporter call 实际执行
4. 把返回结果注入 subagent 继续处理
5. 循环直到 subagent 完成最终回复
```

对 sentry-executor 其余逻辑透明，transcript 格式不变。

### mcporter 已知问题与全局规避策略

**问题 1：mcporter 返回的不是标准 JSON**

mcporter 返回的是 JavaScript 对象字面量（无引号 key、单引号字符串），不是标准 JSON。
`json.loads()` 直接解析必然失败。

**规避策略**：
subagent 调用 mcporter 时，必须用以下方式之一解析返回值：
- 方案 A：用正则提取 `text:` 字段中的内容（跳过外层包装）
- 方案 B：用 `python3 -c "import ast; ..."` 解析 JS 对象字面量
- **禁止**：直接用 `json.loads()` 解析 mcporter 原始输出

**问题 2：MCP 返回大响应（>10KB，含 base64 PDF/文件）**

部分 MCP 工具会把文件内容（PDF、图片）的 base64 编码直接塞进 JSON 返回值，
导致响应超过 100KB。subagent 解析崩溃，并浪费 token。

**规避策略**：
subagent task 中注入以下规则：
```
mcporter 返回值处理规则：
1. 如果返回值 > 10KB，只提取 code、msg、核心业务字段，丢弃 base64/filePath/二进制数据
2. 禁止把完整的大响应写入 transcript.md（截断到前 2000 字符）
3. transcript 中标注：[truncated: original response {N}KB, showing first 2000 chars]
```

**问题 3：参数截断（编号提取不完整）**

subagent 用正则提取用户输入中的单号时，可能截断字母+数字混合编号（如 25BY27IN00016273 → 00016273）。

**规避策略**：
subagent task 中注入：
```
参数提取规则：
- 用户输入中的编号必须完整保留，不可截断前缀
- 单号可能包含字母+数字混合（如 BR202603170001、25BY27IN00016273）
- 禁止用纯数字正则提取，必须保留完整字符串
```

**问题 4：未按 SKILL.md 输出模板格式化响应**

查询失败时 subagent 直接输出 MCP 原始错误消息，没按 SKILL.md 的输出模板格式化。

**规避策略**：
subagent task 中注入：
```
输出规则：
- 即使查询失败，也必须按 SKILL.md 的输出模板格式化 response.md
- 禁止直接输出 MCP 原始错误消息
- response.md 最少 100 字符，包含结构化提示
- 空字段用 `-` 填充，禁止留空
- 多编号场景必须清晰分隔每个编号的结果
```

**问题 5：multi_turn 用例上下文未影响路由决策**

多轮对话用例中，用户在后续轮次纠正/补充信息，但 subagent 仍然按第 1 轮的判断执行。

**规避策略**：
subagent task 中注入：
```
multi_turn 规则：
- 如果 evals.json 中该用例包含 multi_turn 字段：
  1. 前几轮对话是上下文，必须影响当前轮的路由和参数决策
  2. 用户在后续轮次的纠正/补充必须被采纳
  3. 禁止只看当前轮 prompt 而忽略历史对话
```

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

## 并发策略（配置驱动，不探测）

**不再做并发探测**。直接读取 OpenClaw 配置确定并发数：

```
读取顺序：
1. 平台配置中（如 openclaw.json agents.defaults.subagents.maxConcurrent
2. 找不到 → agents.defaults.maxConcurrent
3. 都找不到 → 默认 4

max_concurrent = min(配置值, eval总数)
```

写入 eval_environment.json：
```json
{"max_concurrent": N, "source": "平台配置"}
```

### 按 run 分组模式（核心架构 v2.0）

**按 run 编号分组**，而不是按 eval 分组。每个 subagent 处理所有 eval 的同一个 run，确保同一 eval 的不同 run 在不同 subagent 中执行（run 独立性）。

```
架构：
  Subagent-A：所有 eval 的 run-1（N 个 eval × 1 run）
  Subagent-B：所有 eval 的 run-2
  Subagent-C：所有 eval 的 run-3（仅 standard/full）

subagent 总数：
  smoke/regression：1 个（只有 run-1）
  quick：2 个（run-1 + run-2）
  standard/full：3 个（run-1 + run-2 + run-3）

spawn 策略：
  第 1 轮：同时 spawn A + B（2 并发，gateway 安全值）
  第 2 轮：A 或 B 完成后 spawn C
  → 总共 2 轮，3 次 spawn

runTimeoutSeconds = 600（10min，足够 30 eval × 1 run）
```

**为什么按 run 分组而不是按 eval 分组：**
- 稳定性测试要求同一 eval 的 3 次 run 相互独立
- 按 run 分组 → eval-1 的 run-1/run-2/run-3 在不同 subagent → 完全独立 ✅
- 按 eval 分组 → eval-1 的 3 次 run 在同一 subagent → 上下文污染 ❌

**检查点机制（progress.json）**：

subagent 每完成 1 个 eval 后立即写入检查点文件：

```json
// {session_dir}/progress-run-{R}.json
{
  "run": 1,
  "completed": ["eval-1", "eval-2", "eval-3"],
  "current": "eval-4",
  "failed": [],
  "updated_at": "ISO时间"
}
```

**subagent task 构造（按 run 分组）**：

```
你是 SkillSentry Executor subagent。你负责所有 eval 的 run-{R}。
每个 eval 处理完后：
  1. 写入 transcript.md + response.md
  2. 更新 progress-run-{R}.json（添加到 completed 列表）
  3. 继续下一个 eval

## 被测 SKILL.md
{skill_content}

## eval 列表（共 N 个 eval，每个执行 1 次）

### eval-1
用户输入：{prompt}
transcript → {path}/eval-1/run-{R}/with_skill/outputs/transcript.md
response → {path}/eval-1/run-{R}/with_skill/outputs/response.md

### eval-2
...

## 执行规则
1. 严格按顺序处理每个 eval
2. 每个 eval 独立处理，不复用上一个 eval 的结果
3. 处理完立即写文件 + 更新 progress
4. 单个 eval 写入失败→记录到 failed 列表，继续下一个
5. 全部完成后回复汇总（格式见下方）
```

**completion message 格式（所有模式统一，subagent 必须按此格式返回）**：

```
## Run-{R} 执行完成

| Eval | 输入摘要 | MCP Server | 结果摘要 |
|------|---------|-----------|----------|
| eval-1 | {prompt前20字} | {server} | {结果：成功/失败/超时 + 关键信息} |
| eval-2 | ... | ... | ... |

共 {N} 个 eval，{X} 个成功，{Y} 个失败。
```

**完成后验证（主会话执行）**：
```
subagent 完成 → 主会话检查：
  1. 读取 progress-run-{R}.json
  2. 统计实际文件数：find eval-*/run-{R} -name transcript.md -size +0c | wc -l
  3. 完成数 == eval 总数 → ✅ 该 run 完成
  4. 完成数 < eval 总数 → 读取 failed 列表 → re-spawn 只跑缺失的 eval
  5. 重试 1 次后仍失败 → 标记为 failed，不阻塞流程
```

**spawn 失败处理**：
```
spawn 失败 → 等 5s 重试 1 次
仍失败 → 标记该 run 为 pending，先跑其他 run，最后再补
```

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
4. **MCP 认证失败**：subagent 调 MCP 返回 401/403/500 且错误信息含 auth/token/permission 关键词——说明 subagent 没有继承主会话的 MCP 认证上下文，降级到主会话直跑（主会话有 mcporter 认证）

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
7. **按 SKILL.md 输出模板格式化 response.md**：不能直接记录 MCP 原始 JSON，必须按被测 SKILL.md 的输出规范转换为用户可读格式（包含中文字段名、审批状态等）。否则 semantic 断言会因为找不到中文关键词而误判为失败。
8. transcript 开头标注：「⚠️ 降级执行：主会话直跑（非 subagent）」
9. timing_with.json 标记 "mode": "direct_fallback"
10. 继续下一个 eval
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

---

## session.json 更新

executor 完成后更新 `{session_dir}/session.json` 的 `executor` 字段：

```json
"executor": {
  "total_runs": 90,
  "success": 90,
  "failed": 0,
  "timeout": 0,
  "spawn_count": 3,
  "architecture": "run-stratified",
  "time_minutes": 11,
  "routing_correct": 30,
  "routing_total": 30
}
```

---

## 读取证明（主编排器校验用）

输出的最后一行必须包含以下格式的校验标记：

```
[sentry-proof] skill=<本工具名> steps=<本次执行的步骤数> ts=<ISO时间>
```

主编排器通过检查此标记确认子工具确实读取并执行了 SKILL.md，而非凭记忆发挥。
缺少此标记 → 主编排器判定为「未按 SKILL.md 执行」，要求重跑。
