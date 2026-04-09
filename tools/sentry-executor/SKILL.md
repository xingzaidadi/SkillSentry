---
name: sentry-executor
description: >
  执行 AI Skill 测试用例，输出带 transcript 的执行结果。需要先有 evals.json（可用 sentry-cases 生成）。
  触发场景：说"跑测试用例"、"执行eval"、"运行这些用例"、"帮我跑一下"、
  "测试结果出来了吗"、"执行用例然后评分"。
  不触发场景：只设计用例（用 sentry-cases）、只看报告（用 sentry-report）、要做完整流程（用 SkillSentry）。
---

# sentry-executor · Skill 测试用例执行层（Layer 1）

读取 evals.json，并行执行所有测试用例（with_skill + without_skill），输出带 transcript 的执行结果。

**前置条件**：workspace_dir 下必须存在 `evals.json`（可由 sentry-cases 生成）。

---

## 输入

- `workspace_dir`：本次测评工作目录（由调用方传入）
- `skill_path`：被测 SKILL.md 路径
- `mode`：执行模式（smoke/quick/standard/full），决定运行次数和并发策略

单独调用时，从用户提供的路径或最近一次 session 目录读取。

---

## 断点续跑检查（执行前必须先做）

启动前扫描 `workspace_dir/eval-*/` 目录，检测已有产物：

```
对每个 eval-N：
  with_skill/outputs/transcript.md 存在 AND 文件非空 → 标记为"已完成"
  否则 → 标记为"待执行"
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

---

## 工作目录约定

```
workspace_dir/
├── evals.json                      ← 输入
├── eval_environment.json           ← 记录并行审计结果（追加写入）
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
    └── [grading.json]              ← 由 grader 填写
```

---

## 每批启动前必须输出的声明（不声明禁止发出 subagent 调用）

```
【批次启动声明 · Batch-N】
用例：eval-[X], eval-[Y]（共 [N] 个）
并行方式：在本消息中同时发出 with_skill + without_skill 的 Agent 调用 ✓
without_skill steps 上限：[8/6/5]（skill_type=[类型]）✓
without_skill 早退指令：已注入 ✓
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
- quick 模式：每批 4-5 个用例（16-20 subagent 并行）
- standard/full 模式：每批 2-3 个用例（4-6 subagent）

**quick 模式 mega-batch**：2 次运行合并进同一批次，run1 和 run2 同时启动：
```
批次A：[eval-1 run1 with] [eval-1 run1 without] [eval-1 run2 with] [eval-1 run2 without] [eval-2 ...]
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

```
你的工作目录是 eval-N/without_skill/workspace/，禁止读取 eval-N/with_skill/ 下的任何文件。
所有操作必须独立完成，不能复用 with_skill 的任何结果。
你的目标是展示没有 Skill 指导时的自然行为。遇到以下任一关键失败点时，立即停止：
- 路由选择错误 / 必填字段缺失 / 权限校验失败 / 流程中断无法继续

【工具调用自计数】每次调用工具前累加次数（从0开始），达到上限（mcp_based:6次 / code_execution:5次）立即停止：
「[STOPPED: tool_call_limit_reached, calls=[N]]」

【沙箱隔离自检 - 执行完成后写入 response.md 末尾】：
1. 我是否读取了 eval-N/with_skill/ 目录下的任何文件？（是/否）
2. 我使用的所有结果，是否全部由本次独立执行产生？（是/否）
如果任何一项答案为「是」：标注「⚠️ 沙箱隔离违规：本次结果无效」
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

每个 subagent 完成后立即写入 `timing_with.json` / `timing_without.json`：

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

**必须立即保存**，task notification 是一次性事件，不可事后补填。

---

## 批次完成后并行度审计（自动执行）

每批所有 subagent 完成后，计算并行度：

```python
start_gap = abs(eval.with_skill.start_ms - eval.without_skill.start_ms)
parallel = start_gap <= 30_000  # 30秒内视为并行
batch_parallel_rate = parallel_count / total_count
```

写入 `workspace_dir/eval_environment.json` 的 `parallelism_audit` 字段。

触发规则：
- ≥ 80%：正常继续 ✓
- 50-80%：下批次额外输出并行率警告
- < 50%：暂停，列出所有串行用例 start_gap，询问用户是否继续

---

## 执行完成后的输出

```
✅ 执行完成
📊 完成：[N] 个用例 × [R] 次运行（[N×2 - skip数] 个 subagent）
⏱️ 总耗时：约 [X] 分钟
🔄 并行率：[X]%（[N]/[N] 个用例并行）

下一步：
  评分 → 使用 SkillSentry 内置 Grader，或说「帮我评审这批结果」
  报告 → 先运行 Grader，再使用 sentry-report
```
