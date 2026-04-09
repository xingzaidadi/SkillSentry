# execution-phases.md — 跨工具通用规范与数据接口

> 工具箱架构下，各工具独立执行细节见各 `sentry-*/SKILL.md`。
> 本文件只保留**跨工具共享的规范**和**工具间数据接口定义**。

---

## 一、工具间数据接口（JSON 文件约定）

所有工具通过 session 目录中的 JSON 文件传递状态，格式如下：

### rules.cache.json（sentry-cases 读取 / SkillSentry 写入）
```json
{
  "skill_hash": "<SKILL.md 的 MD5>",
  "extracted_at": "<ISO时间>",
  "rules": ["规则1", "规则2", "..."]
}
```

### cases.cache.json（sentry-cases 写入 / sentry-executor 读取）
```json
{
  "rules_hash": "<与 rules.cache.json 相同的 skill_hash>",
  "designed_at": "<ISO时间>",
  "mode": "smoke | quick | standard | full",
  "evals": [ /* 同 evals.json 格式 */ ]
}
```

### evals.json（sentry-cases 输出 / sentry-executor 输入）
```json
[
  {
    "id": 1,
    "display_name": "正常报销流程",
    "type": "happy_path",
    "source": "ai_generated | external",
    "prompt": "<用例 prompt>",
    "skip_without_skill": false,
    "skip_reason": "",
    "expectations": [
      {
        "text": "<断言描述>",
        "precision": "exact_match | semantic | existence",
        "rule_ref": "<对应 SKILL.md 规则>"
      }
    ]
  }
]
```

### timing_with.json / timing_without.json（sentry-executor 写入 / sentry-report 读取）
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

### grading.json（agents/grader 写入 / sentry-report 读取）
```json
{
  "skill_type": "mcp_based | text_generation | code_execution",
  "expectations": [ /* 逐条断言结果 */ ],
  "summary": {
    "passed": 6, "failed": 2, "total": 8,
    "precision_breakdown": { "exact_match": {}, "semantic": {}, "existence": {} },
    "authoritative_pass_rate": 0.80
  },
  "execution_metrics": {},
  "timing": {},
  "eval_feedback": {}
}
```

### eval_environment.json（sentry-executor 追加写入）
```json
{
  "parallelism_audit": [
    { "batch": 1, "parallel_rate": 0.75, "violations": ["eval-4 串行（gap=84s）"] }
  ],
  "overall_parallel_rate": 0.88
}
```

---

## 二、skip_without_skill 判断规则（sentry-cases 执行，sentry-executor 读取）

| 条件 | skip_without_skill | skip_reason |
|------|-------------------|-------------|
| `type = "negative"` | true | 负向测试，without_skill 无对比价值 |
| 所有断言 `precision = "existence"` | true | existence 断言对有无 Skill 不敏感 |
| `type = "robustness"` 且核心断言为负向存在性 | true | 鲁棒性用例，without_skill 行为已知（混乱） |

---

## 三、Grader 上下文压缩规范

**触发时机**（流水线模式下）：每个后台 Grader 完成时（收到 task notification）立即压缩该批结果，不等待其他批次。若通知在下一批 Executor 执行期间到达，完成当前批次启动声明后再处理压缩。smoke 模式（同步 Grader）保持原有「完成后立即压缩」逻辑。

每个 Grader 后台任务完成后，主 agent 将详细评审结果**压缩为紧凑摘要**，只在上下文保留摘要：

**压缩格式**（每 eval ≤ 1 行）：
```
批次1 结果摘要（全量数据在 grading.json）：
  eval-1 [happy_path]  通过率 8/12 (67%)  script:5/6  grader:3/6  失败: saveExpenseDoc入参错误
  eval-2 [travel]      通过率 6/7  (86%)  script:3/3  grader:3/4  失败: fdMonthOfOccurrence字段
  并行率: 100% ✓
```

**禁止在上下文中保留**：完整 grading.json、完整 transcript、Grader 逐条 evidence 原文。

---

## 四、并行度审计规范（sentry-executor 每批完成后执行）

```python
# 判定逻辑（伪代码）
start_gap = abs(eval.with_skill.start_ms - eval.without_skill.start_ms)
parallel = start_gap <= 30_000  # 30秒内视为并行
batch_parallel_rate = parallel_count / total_count
```

触发规则：

| 并行率 | 动作 |
|--------|------|
| ≥ 80% | 正常继续 ✓ |
| 50-80% | 下批声明前额外输出警告 |
| < 50% | 暂停，列出所有串行用例的 start_gap，询问用户是否继续 |

---

## 五、Grader 使用规范（SkillSentry 内部，适用所有工作流）

- 每次 Grader 调用必须传入 **≥ 2 个用例** transcript（唯一例外：整批只剩最后 1 个）
- 使用 `explore` subagent 类型（只读，无需写权限）
- transcript 精简传输：只传 `[tool_calls]` 区块 + response.md 全文，截断超 500 字的 JSON 返回体
- 启动前输出：`【Grader 启动声明】本次传入：eval-[X], eval-[Y]（共 [N] 个用例）`

**调度行为**：
- smoke：同步启动，等待完成后再执行后续步骤
- quick / regression / standard / full：后台非阻塞启动，每批 Executor 完成后立即触发，无需等待上一批 Grader 结束
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
