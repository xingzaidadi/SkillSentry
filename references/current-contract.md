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
- 不重写 CI 平台集成；允许 CI 复用当前 pipeline/state/gate 口径。
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

## Tool-as-Code 确定性内核

当前稳定口径允许把机械步骤交给代码执行,但不改变测评维度、报告视觉结构和主 pipeline 语义。

已提供的确定性脚本:

| 脚本 | 当前职责 | 不做什么 |
|------|----------|----------|
| `scripts/sentry_preflight.py` | 定位 Skill、读取 frontmatter、计算 hash、识别 skill_type、检查 config、cases 缓存和 Claude/SDK 运行时可用性 | 不生成用例、不做评分 |
| `scripts/sentry_pipeline.py` | 输出当前稳定口径 pipeline、下一步、步骤类型、工具和 required artifacts | 不执行步骤、不生成产物 |
| `scripts/sentry_state.py` | 初始化/读取/写入 `session.json`,校验 pipeline transition,记录 milestone evidence | 不跳过 auto-exempt 用户确认 |
| `scripts/sentry_gate.py` | 原方案 `sentry-score` 的当前落地形态;聚合 grading,计算 `authoritative_pass_rate`、等级、Delta 状态、IFR、否决项和最终 verdict | 不改写 grading 原始证据;不把门禁判断拆回 LLM 心算 |
| `scripts/sentry_ci.py` | 编排 CI pipeline、生成/复用 cases、调用 executor/grader/gate/publish;记录 `case_warnings` 并支持 `--timeout-per-eval` | 不把不可执行用例伪装成真实质量失败,不把总超时当作单用例超时 |
| `scripts/sentry_diagnostics.py` | 聚合 CI/publish 诊断,区分 case warning、executor timeout/error、grader error、sync skipped、Delta 和 publish 状态 | 不参与评分、不改写 grading/gate 原始证据 |
| `scripts/sentry_sync.py` | 包装 `sync_cases.py`,为 sync 步骤输出稳定 JSON,无飞书配置时显式 `skipped_no_config` | 不替代飞书 API 实现、不隐式跳过 sync 步骤 |
| `scripts/sentry_publish.py` | 包装发布步骤,输出稳定 `publish-result.json` 并生成本地报告兜底 | 不替代交互式飞书上传、不改变报告视觉结构 |
| `scripts/sentry_contract_lint.py` | 扫描 SkillSentry 本体的当前口径漂移 | 不替代静态规则检查、不评价被测 Skill 质量 |
| `scripts/sentry_article_lint.py` | 扫描文章仓库的当前口径漂移 | 不改写文章、不替代人工编辑判断 |

原则:
- 状态写入和发布门禁计算优先使用脚本,不要让 LLM 手写 JSON 或临场心算评分。
- `sentry-score` 是方案名;当前代码名为 `sentry_gate.py`,同时覆盖 score 和 release gate。
- pipeline 查询和下一步判断优先使用 `sentry_pipeline.py` 或复用其定义,不要在 CI、主 `SKILL.md` 和状态脚本中各自维护一套数组。
- sync/publish 步骤优先使用 `sentry_sync.py`、`sentry_publish.py` 输出稳定 JSON;飞书配置缺失时必须留下结构化 `skipped_no_config` 或本地发布结果。
- CI 生成或复用 cases 后必须保留可执行性 warning;发现不存在的本地路径、不可访问项目或超出单用例预算的重型用例时,应记录到 `session.json.case_warnings` 并在解释结论时区分“用例不可执行”和“Skill 质量失败”。
- CI 启动前必须运行 preflight,并把结果写入 `session.json.preflight`;CI 所有结果路径都必须写 `--output-dir/report.html`,有 session 的失败路径也必须补 `session/report.html`;CI JSON、summary Markdown 和最小 HTML 报告必须带 `Execution Diagnostics`,把 `preflight_error`、`runner_unavailable`、`llm_unavailable`、`case_unusable`、`runner_timeout`、`grader_error`、`environment_skipped` 和 `quality_failure` 分开呈现。
- CI 退出码是稳定契约:`PASS=0`,`CONDITIONAL PASS=1`,`FAIL=1`,`ERROR=2`;`--github-output` 必须输出 `verdict/status/release_status/exit_code/report_html/session_report_html/diagnostic_categories/authoritative_pass_rate/grade`。
- CI orchestration 必须覆盖 `smoke / quick / regression / standard / full` 全部模式。`regression` 虽不执行 cases 步骤,但进入 executor 前必须已有 `evals.json`,可由 `--cases` 或缓存预置。
- 脚本输出是事实来源;LLM 可以解释原因和建议,但不能改写核心数值。
- `sentry-static` 仍是正式静态工具名;不要把代码版静态规则检查重新命名为正式 `sentry-lint`。
- 当前口径自检使用 `sentry_contract_lint.py` 和 `sentry_article_lint.py`;它们只检查 SkillSentry 自身与文章材料,不参与被测 Skill 的质量评分。

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
