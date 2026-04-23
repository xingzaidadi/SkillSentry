---
name: sentry-executor
description: >
  执行 AI Skill 测试用例，输出带 transcript 的执行结果。需要先有 evals.json（可用 sentry-cases 生成）。
  触发场景：说"跑测试用例"、"执行eval"、"运行这些用例"、"帮我跑一下"、
  "测试结果出来了吗"、"执行用例然后评分"。
  不触发场景：只设计用例（用 sentry-cases）、只看报告（用 sentry-report）、要做完整流程（用 SkillSentry）。
---

# sentry-executor · Skill 测试用例执行层（Layer 1）

读取 evals.json，并行执行所有测试用例（with_skill，视模式决定是否含 without_skill），输出带 transcript 的执行结果。

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

---

## 每批启动前必须输出的声明（不声明禁止发出 subagent 调用）

```
【批次启动声明 · Batch-N】
用例：eval-[X], eval-[Y]（共 [N] 个）
并行方式：[全部 with_skill only（skip_without_skill=true）/ with_skill + without_skill 双侧并行] ✓
without_skill steps 上限：[8/6/5]（skill_type=[类型]）/ N/A（全部跳过）✓
without_skill 早退指令：[已注入 / N/A（全部跳过）] ✓
without_skill 策略：[全部跳过（mcp_based + smoke/quick 模式）/ 正常双侧执行（其他）] ✓
```

声明写出后，在**同一消息**中发出所有 Agent 工具调用。

---

## skip_without_skill 检查

读取 evals.json 中每个用例的 `skip_without_skill` 字段：
- `true`：只启动 with_skill，在声明中注明「eval-[N] without_skill 已跳过」
- `false` 或不存在：正常启动双侧

---

## 强制并行规则

每个用例的 with_skill 和 without_skill **必须在同一批次同一消息中启动**：

```
❌ 串行（时间 × 2）：eval-1 with → 等完成 → eval-1 without → ...
✅ 并行：同时发出 eval-1 with + eval-1 without（同一消息）
```

**批次大小**：
- quick 模式（mcp_based）：全部 8-10 个用例一次性启动（每 eval 仅 2 subagent，共 16-20 subagent，无需分批）
- quick 模式（其他类型）：每批 4-5 个用例（16-20 subagent 并行）
- standard/full 模式：每批 2-3 个用例（4-6 subagent）

**quick 模式 mega-batch**：2 次运行合并进同一批次，run1 和 run2 同时启动：
```
mcp_based+quick：[eval-1 run-1 with] [eval-1 run-2 with] [eval-2 run-1 with] [eval-2 run-2 with] [eval-3 ...]
其他类型+quick：[eval-1 run-1 with] [eval-1 run-1 without] [eval-1 run-2 with] [eval-1 run-2 without] [eval-2 ...]
```

---

## Executor subagent steps 上限

| Skill 类型 | with_skill | without_skill |
|-----------|-----------|--------------|
| mcp_based | 15 steps | 8 steps |
| code_execution | 10 steps | 6 steps |
| text_generation | 5 steps | 5 steps |

---

## without_skill subagent prompt 必须注入

**沙箱隔离声明（所有 skill_type 通用，必须注入）**：
```
你的工作目录是 eval-N/without_skill/workspace/（多次运行时：eval-N/run-R/without_skill/workspace/），禁止读取 eval-N/with_skill/ 下的任何文件。
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

## 执行完成后的输出

```
✅ 执行完成
📊 完成：[N] 个用例 × [R] 次运行（[N×2 - skip数] 个 subagent）
⏱️ 总耗时：约 [X] 分钟
🔄 并行率：[X]%（[N]/[N] 个用例并行）/ N/A（全部 skip_without_skill，无双侧对比）
📊 指标采集：✅ A1/A2/A3/E3 已提取 | 🔧 C1/C2/C4/C5 视 evals.json 字段 | ⏳ C3/C6/E1/E2 待 Grader/Report

下一步：
  评分 → 使用 SkillSentry 内置 Grader，或说「帮我评审这批结果」
  报告 → 先运行 Grader，再使用 sentry-report
```
