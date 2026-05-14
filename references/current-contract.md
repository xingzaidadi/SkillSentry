# SkillSentry v9.0 Current Contract

本文件是 v9.0 的口径收敛页。主 `SKILL.md`、子工具和文章材料出现冲突时,以本文件为当前版本的解释基准。

---

## v9.0 目标

v9.0 是契约收敛版,不是功能扩展版。

目标:
- 统一执行契约,避免主编排、子工具和 references 说法不一致。
- 降低主 `SKILL.md` 的职责负担,让它回到调度器角色。
- 清理旧工具名、旧等级和旧指标口径,让文档和工具使用同一套语言。

非目标:
- 不新增测评维度。
- 不新增平台适配。
- 不重写 CI。
- 不改变报告视觉结构。

---

## 当前正式术语

| 类型 | 当前正式口径 | 历史/兼容口径 |
|------|-------------|--------------|
| 发布结论 | `PASS` / `CONDITIONAL PASS` / `FAIL` | L0-L5 只作为历史资料 |
| 质量等级 | `S` / `A` / `B` / `C` / `D` / `F` | L0-L5 不再作为当前执行口径 |
| 核心通过率 | `authoritative_pass_rate` 或 exact_match pass rate | `Pass³` 仅作为历史/方法论补充 |
| 静态工具 | `sentry-static` | `sentry-lint` / `sentry-trigger` / `sentry-check` 为兼容命令 |
| 主流程评分报告步骤 | `grader-report` | `grader` + `report` 分离为历史口径 |
| 独立重出报告 | `sentry-report` | 仅在已有 grading 时使用 |

---

## Grader/Report 契约

主流程使用 `grader-report` 步骤,由 `sentry-grader` 在同一个 subagent 内完成:
1. 断言评审。
2. 合并 `grading.json` / `grading-summary.json`。
3. 生成 `report.html`。
4. 写入 `session.json.last_step = "grader-report"`。

`sentry-report` 保留,但只用于独立场景:
- 用户说「出报告」「重新生成报告」「已有 grading 帮我重出 HTML」。
- 已有 `grading-summary.json` 或各 eval 的 `grading.json`。
- 不作为主 pipeline 的常规步骤。

---

## without_skill / Delta 契约

`skip_without_skill` 的当前规则:

| skill_type / mode | without_skill 默认行为 | Delta |
|-------------------|------------------------|-------|
| `mcp_based` + `smoke` / `quick` | 默认跳过 | `N/A` |
| `mcp_based` + `standard` / `full` | 默认执行可比较的 without_skill 侧；无法裸跑的单个 eval 可标记跳过 | 可计算则计算,不可计算标 `N/A(partial)` |
| `text_generation` | 默认执行 | 必须计算 |
| `code_execution` | 默认执行,除非安全或环境原因跳过 | 必须计算或说明跳过原因 |
| `negative` / 纯 existence / 特定 robustness 用例 | 可逐用例跳过 | 不参与 Delta |

注意:
- `mcp_based + standard/full` 不再全局跳过 without_skill。
- 如果某些 eval 没有可执行 baseline,只跳过这些 eval,报告必须区分 `Delta computed`、`Delta skipped` 和 `Delta partial`。

---

## v9.0 Pipeline

合法 pipeline:

```json
{
  "smoke": ["cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
  "quick": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
  "regression": ["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"],
  "standard": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"],
  "full": ["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"]
}
```

说明:
- `grader-report` 生成最终报告,因此 standard/full 中 comparator/analyzer 应在它之前完成或产出可读取的跳过说明。
- `sentry-report` 不在主 pipeline 中。
- `sync-*` 是正式 pipeline 步骤,没有配置时写入 `skipped_no_config`,不静默消失。
