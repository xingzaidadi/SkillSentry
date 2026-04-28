# execution-phases.md — 跨工具通用规范与数据接口

> 工具箱架构下，各工具独立执行细节见各 `sentry-*/SKILL.md`。
> 本文件只保留**跨工具共享的规范**和**工具间数据接口定义**。

---

## 零、skill_type 自动检测规范

`skill_type` 由 SkillSentry 在 Step 1 读取被测 SKILL.md 后立即检测，结果写入 session 上下文并传递给 sentry-executor 和 agents/grader。

**检测规则（按优先级）**：

```
mcp_based（最高优先级）：
  满足以下任一条件 →
  • SKILL.md 中出现业务 MCP 工具名（以动词开头的 camelCase，如 saveExpenseDoc、queryItems、uploadFile）
  • 出现 "MCP"、"mcp_server"、"tool_calls"（仅在 MCP 上下文中）关键词
  • SKILL.md 的 description 中提到「MCP 工具」「调用业务接口」

  ⚠️ 排除以下 Claude Code 内置工具（出现这些不算 mcp_based）：
  Read、Write、Edit、Bash、Glob、Grep、Agent、NotebookEdit、WebFetch、WebSearch
  以及泛化表述「使用工具」「调用工具」（未指定具体工具名）

code_execution：
  mcp_based 条件不满足，且满足以下任一 →
  • 出现 "Bash"、"python3"、"shell"、"脚本"、"执行命令"、"生成文件"、"运行脚本" 关键词
  • 有 ## 脚本 / ## 工具脚本 章节
  • SKILL.md 中有具体 Bash 命令示例（如 `pip install`、`python3 xxx.py`）

text_generation（默认兜底）：
  以上均不满足 → text_generation
```

> **不确定时**：输出「❓ Skill 类型无法自动判断（mcp_based / text_generation 均有特征）」，询问用户确认。

**检测后输出**：
```
✅ Skill 类型检测：mcp_based（依据：发现工具名 saveExpenseDoc、queryExpenseApplier）
```

检测结果不确定时，询问用户确认后继续。

---

## 一、工具间数据接口（JSON 文件约定）

所有工具通过 session 目录中的 JSON 文件传递状态：

| 文件 | 写入方 | 读取方 | 关键字段 |
|------|-------|-------|---------|
| `rules.cache.json` | SkillSentry | sentry-cases | `skill_hash`, `extracted_at`, `rules[]` |
| `cases.cache.json` | sentry-cases | sentry-executor | `rules_hash`, `mode`, `evals[]` |
| `evals.json` | sentry-cases | sentry-executor | `id`, `type`, `source`, `prompt`, `skip_without_skill`, `skip_reason`, `expectations[]{text, precision, rule_ref}` |
| `timing_with.json` / `timing_without.json` | sentry-executor | sentry-report | `executor_start_ms`, `executor_end_ms`, `duration_ms`, `total_tokens`, `input_tokens`, `output_tokens` |
| `grading.json` | agents/grader | sentry-report | `runs: {run-1: {pass, assertions[], summary{pass,fail,total,precision_breakdown,authoritative_pass_rate}}, run-2: {...}, run-3: {...}}, feishu_record_id` |
| `eval_environment.json` | sentry-executor | 审计用 | `parallelism_audit[]{batch,parallel_rate,violations[]}`, `overall_parallel_rate` |

---

## 二、skip_without_skill 判断规则（sentry-cases 执行，sentry-executor 读取）

| 条件 | skip_without_skill | skip_reason |
|------|-------------------|-------------|
| `skill_type = "mcp_based"` AND `mode ∈ {smoke, quick}` | true（全部用例） | 无 Skill 指导时模型几乎必然调错 MCP 工具，Δ 总为正，without_skill 无增量价值；standard/full 保留双侧 |
| `type = "negative"` | true | 负向测试，without_skill 无对比价值 |
| 所有断言 `precision = "existence"` | true | existence 断言对有无 Skill 不敏感 |
| `type = "robustness"` 且核心断言为负向存在性 | true | 鲁棒性用例，without_skill 行为已知（混乱） |

> **优先级**：首行（mcp_based + smoke/quick）最高，命中后直接标记，不再逐条判断。

---

## 三、Grader 上下文压缩规范

**触发时机**（流水线模式下）：每个后台 Grader 完成时（收到 task notification）立即压缩该批结果，不等待其他批次。若通知在下一批 Executor 执行期间到达，完成当前批次启动声明后再处理压缩。smoke 模式（同步 Grader）保持原有「完成后立即压缩」逻辑。

每个 Grader 后台任务完成后，主 agent 将详细评审结果**压缩为紧凑摘要**，只在上下文保留摘要：

**压缩格式**（每 eval ≤ 1 行）：
```
批次1 结果摘要（全量数据在 grading.json）：
  eval-1 [happy_path]  通过率 8/12 (67%)  script:5/6  grader:3/6  失败: saveExpenseDoc入参错误
  eval-2 [travel]      通过率 6/7  (86%)  script:3/3  grader:3/4  失败: fdMonthOfOccurrence字段
  并行率: 100% ✓  /  N/A（全部 skip_without_skill，无双侧对比）
```

**禁止在上下文中保留**：完整 grading.json、完整 transcript、Grader 逐条 evidence 原文。

---

## 四、并行度审计规范（sentry-executor 每批完成后执行）

```python
# 跳过条件：该批所有用例均 skip_without_skill=true
if all(eval.skip_without_skill for eval in batch):
    parallelism_audit = "N/A (all evals skip_without_skill)"
    # 不触发任何告警规则，直接跳过
else:
    start_gap = abs(eval.with_skill.start_ms - eval.without_skill.start_ms)
    parallel = start_gap <= 30_000  # 30秒内视为并行
    batch_parallel_rate = parallel_count / total_count
```

触发规则（仅当存在双侧用例时）：

| 并行率 | 动作 |
|--------|------|
| N/A（全部 skip） | 记录 N/A，不触发告警 |
| ≥ 80% | 正常继续 ✓ |
| 50-80% | 下批声明前额外输出警告 |
| < 50% | 暂停，列出所有串行用例的 start_gap，询问用户是否继续 |

---

## 五、Grader 使用规范（SkillSentry 内部，适用所有工作流）

- 每次 Grader 调用必须传入 **≥ 2 个用例** transcript（唯一例外：整批只剩最后 1 个）
- **推荐批次大小**：smoke = 1 次调用（全部 4-5 eval）；quick = 每批 ≤ 4 eval（共 2 次调用）；standard/full = 每批 2-3 eval
- 使用 `explore` subagent 类型（只读，无需写权限）
- transcript 精简传输：只传 `[tool_calls]` 区块 + response.md 全文，截断超 500 字的 JSON 返回体
- 启动前输出：`【Grader 启动声明】本次传入：eval-[X], eval-[Y]（共 [N] 个用例）`

**调度行为**：
- smoke：同步启动，等待完成后再执行后续步骤
- quick：第一批同步（用于快速失败检测），其余批次后台非阻塞启动；mcp_based+quick 为单批次，整个 Grader 同步等待
- regression / standard / full：后台非阻塞启动，每批 Executor 完成后立即触发，无需等待上一批 Grader 结束
- 所有 Grader 的最终完成检查在 sentry-report 启动前统一执行（由 SKILL.md 强制等待点保障）

---

## 六、Comparator/Analyzer 适用范围（standard/full 模式）

- **仅对** `happy_path` + `e2e` 类型用例运行，其他类型跳过
- 非阻塞启动，主流程不等待其完成，直接继续下一批
- smoke 模式完全跳过 Comparator/Analyzer
- 进入 sentry-report 前，确认所有 Comparator/Analyzer 已完成

---

## 七、报告模板预加载时机

`references/report-template.md` 在第一批 Executor 完成后后台预加载（不阻塞主流程），
sentry-report 启动时直接使用缓存，无需等待文件读取。
