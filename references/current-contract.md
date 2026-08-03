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
| `scripts/sentry_case_quality.py` | 用例质量后置统计;统计 evals.json 维度覆盖、硬门禁检查、断言 orphan 率,并记录安全 case family / 风险元数据,输出 `case-quality-result.json` | 不干预用例生成过程;不调 LLM;不联网 |
| `scripts/sentry_case_lint.py` | 读取 `evals.json`/`cases.cache.json`,检查本地路径、危险命令、外联、密钥读取、注入语句和模糊授权等可执行性/安全标注风险,输出 `case_warnings` | 不调 LLM、不跑 executor、不把 warning 当作质量失败 |
| `scripts/sentry_executor.py` | 包装 `ci_executor.py`,执行 with_skill/without_skill,输出稳定 JSON 并更新 session | 不重新实现 CLI runner、不调 grader、不做质量判断 |
| `scripts/sentry_grader.py` | 包装 `ci_grader.py`,评审已有 with_skill response,写 `grading-summary.json`/`report.html` 并更新 session | 不跑 executor、不改写 grading 原始证据、不做发布同步 |
| `scripts/sentry_run.py` | profile 组合器:`preflight/lint/debug/local/ci/release`;轻 profile 只读已有 artifact 或做确定性检查 | 不替代 `sentry_ci.py` 的完整 CI/release 契约 |
| `scripts/sentry_ci.py` | 编排 CI pipeline、生成/复用 cases、调用 executor/grader/gate/publish;记录 `case_warnings` 并支持 `--timeout-per-eval` | 不把不可执行用例伪装成真实质量失败,不把总超时当作单用例超时 |
| `scripts/sentry_diagnostics.py` | 聚合 CI/publish 诊断,区分 case warning、executor timeout/error、grader error、sync skipped、Delta 和 publish 状态 | 不参与评分、不改写 grading/gate 原始证据 |
| `scripts/sentry_timing.py` | 读取 `eval_result.json`、`sentry-run-result.json` 或 session timing artifacts,排序慢 step/phase,汇总 executor per-eval 耗时、已有 grader per-eval 耗时和 local 复用决策并给出观测建议 | 不调 LLM、不联网、不改变 pipeline/gate/退出码 |
| `scripts/sentry_sync.py` | 包装 `sync_cases.py`,为 sync 步骤输出稳定 JSON,无飞书配置时显式 `skipped_no_config` | 不替代飞书 API 实现、不隐式跳过 sync 步骤 |
| `scripts/sentry_publish.py` | 包装发布步骤,输出稳定 `publish-result.json` 并生成本地报告兜底 | 不替代交互式飞书上传、不改变报告视觉结构 |
| `scripts/sentry_contract_lint.py` | 扫描 SkillSentry 本体的当前口径漂移 | 不替代静态规则检查、不评价被测 Skill 质量 |
| `scripts/sentry_article_lint.py` | 扫描文章仓库的当前口径漂移 | 不改写文章、不替代人工编辑判断 |

原则:
- 状态写入和发布门禁计算优先使用脚本,不要让 LLM 手写 JSON 或临场心算评分。
- `sentry-score` 是方案名;当前代码名为 `sentry_gate.py`,同时覆盖 score 和 release gate。
- pipeline 查询和下一步判断优先使用 `sentry_pipeline.py` 或复用其定义,不要在 CI、主 `SKILL.md` 和状态脚本中各自维护一套数组。
- sync/publish 步骤优先使用 `sentry_sync.py`、`sentry_publish.py` 输出稳定 JSON;飞书配置缺失时必须留下结构化 `skipped_no_config` 或本地发布结果。
- 稳定 HTML 报告优先使用 `sentry_report.py`;它是 no-LLM/no-network 轻工具,只读取已有 session/result artifact。`sentry_ci.py` 和 `sentry_publish.py` 不应各自维护 HTML 渲染逻辑。
- CI 生成或复用 cases 后必须保留可执行性 warning;发现不存在的本地路径、不可访问项目或超出单用例预算的重型用例时,应记录到 `session.json.case_warnings` 并在解释结论时区分“用例不可执行”和“Skill 质量失败”。
- 可执行性和安全标注 warning 的确定性检查优先使用 `sentry_case_lint.py`;它是 no-LLM/no-network 轻工具,可独立运行 `python scripts/sentry_case_lint.py --cases <evals.json> --session-dir <session>`。
- executor 步骤优先通过 `sentry_executor.py` 调用;它是重工具 wrapper,会调用 Claude CLI,但只负责执行、写 summary 和更新 session,不负责评分或报告。
- grader-report 步骤优先通过 `sentry_grader.py` 调用;它是重工具 wrapper,会调用 SDK/LLM,但只负责评审已有 response、写 summary/report 和更新 session,不重跑 executor。
- 日常入口优先使用 `sentry_run.py` profile:`preflight/lint/debug` 不得触发 executor/grader;`local` 只跑 with_skill + grader/report,不得跑 without_skill/publish;`ci/release` 必须委托 `sentry_ci.py`。
- `sentry_run.py --profile local --reuse-session <session>` 必须使用 `manifest.json` 判断 executor/grader 是否可复用;输入 hash 未变且所需 artifacts 完整时复用已准备 cases/case_lint 并跳过重步骤,payload 必须说明复用命中/未命中原因,显式 `--force-executor`/`--force-grader` 才可重跑。
- `sentry_run.py --format json` 必须输出 `timings.total_ms` 和 `timings.phases_ms`;timings 只用于执行耗时观测,不得参与评分、gate 或退出码判断。
- `sentry_ci.py` 必须在 `session.json.ci_step_timings` / `ci_phase_timings` / `ci_timing` 记录 pipeline step 与非 pipeline phase 耗时,并在 `eval_result.json.timings` 和 diagnostics 中透出;timings 不得改变 pipeline 顺序、gate 或退出码。
- `ci_grader.py` 写入的每个 `grading.json` 必须包含 `duration_ms` / `timing.grader_duration_ms`;该字段只用于耗时观测,不得参与评分、gate 或退出码判断。
- diagnostics、summary Markdown 和 HTML 报告必须展示 executor/grader 单用例耗时聚合统计和最慢项;该摘要不得参与评分、gate 或退出码判断。
- diagnostics 可以输出确定性 `timing_hints`;该建议只读 timing artifact,不得参与评分、gate 或退出码判断。
- CI 启动前必须运行 preflight,并把结果写入 `session.json.preflight`;CI 所有结果路径都必须写 `--output-dir/report.html`,有 session 的失败路径也必须补 `session/report.html`;CI JSON、summary Markdown 和最小 HTML 报告必须带 `Execution Diagnostics`,把 `preflight_error`、`runner_unavailable`、`llm_unavailable`、`case_unusable`、`runner_timeout`、`grader_error`、`environment_skipped` 和 `quality_failure` 分开呈现。
- CI 退出码是稳定契约:`PASS=0`,`CONDITIONAL PASS=1`,`FAIL=1`,`ERROR=2`;`--github-output` 必须输出 `verdict/status/release_status/exit_code/report_html/session_report_html/diagnostic_categories/timing_hints/authoritative_pass_rate/grade`。
- GitHub Actions workflow 必须直接调用 `sentry_ci.py`,不得先让 LLM 交互式“测评”再用旧 `ci_eval.py` 汇总;GitHub Checks 必须读取 `eval_result.json` 的 `status/exit_code/artifacts/diagnostics`,展示诊断分类和 `diagnostics.timing_hints`,并将 `CONDITIONAL PASS` 映射为 `action_required`。
- CI orchestration 必须覆盖 `smoke / quick / regression / standard / full` 全部模式。`regression` 虽不执行 cases 步骤,但进入 executor 前必须已有 `evals.json`,可由 `--cases` 或缓存预置。
- 脚本输出是事实来源;LLM 可以解释原因和建议,但不能改写核心数值。
- `sentry-static` 仍是正式静态工具名;不要把代码版静态规则检查重新命名为正式 `sentry-lint`。
- 当前口径自检使用 `sentry_contract_lint.py` 和 `sentry_article_lint.py`;它们只检查 SkillSentry 自身与文章材料,不参与被测 Skill 的质量评分。

---

## Security V1 用例矩阵

安全增强的统一设计依据见 `security-v1-case-matrix.md`。它不是新的主流程,而是给后续安全 case、静态风险扫描和门禁规则提供共同口径。

当前约定:
- `P0`：只要命中就必须阻断或降级为人工确认,不能带病发布。
- `P1`：优先进入回归和诊断,是否阻断由上下文决定,但必须可追踪。
- 安全 case 的默认判定顺序是 `静态提示 → 动态验证 → 门禁决策 → 诊断留痕`。
- 若同一 case 同时命中越权、泄密或外联任一项,应自动升格为 `P0`。
- 安全 case 使用统一字段: `security_family`、`risk_level`、`attack_surface`、`expected_guardrail`、`gate_level`。
- `P0 + gate_level=block` 的安全 case 只要 grading 失败、缺失 grading 或没有断言,`sentry_gate.py` 必须输出 `security_p0_failure` veto 并阻断发布。

`security-v1-case-matrix.md` 只定义家族和判定口径,不替代具体的 `evals.json` 生成器;后续生成器应以该矩阵作为 case 目录和回归标签来源。
当安全 case 家族覆盖不足或元数据缺失时,diagnostics 可以额外输出 `security_case_gap` 作为诊断分类,但是否阻断仍由 `gate` 和当前模式的发布阈值共同决定。
当 `gate` 出现 `security_p0_failure` 或其他 `security_*` veto 时,diagnostics 应输出 `security_failure`,并与普通 `quality_failure` 区分。

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
- 脚本入口为 `scripts/sentry_report.py --session-dir <session>` 或 `scripts/sentry_report.py --result <eval_result.json>`。
- 该脚本不得调 LLM、不得联网,也不得覆盖已有的真实交互式 grader 报告,除非显式 `--force`。
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
  "smoke": ["cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
  "quick": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"],
  "regression": ["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"],
  "standard": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"],
  "full": ["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"]
}
```

说明:
- `grader-report` 生成最终报告,因此 standard/full 中 comparator/analyzer 应在它之前完成或产出可读取的跳过说明。
- `sentry-report` 不在主 pipeline 中。
- `sync-*` 是正式 pipeline 步骤,没有配置时写入 `skipped_no_config`,不静默消失。
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\current-contract.md` |
| 学习重点 | current-contract |
| 阅读目标 | 看懂这份资料解决什么问题、为什么重要、怎么落地、面试时怎么讲。 |

### 背景、痛点、举措、收益

| 维度 | 内容 |
|---|---|
| 背景 | AI Skill 从个人提示词沉淀走向工程化资产，需要把知识、流程、评测、安全和交付统一管理。 |
| 痛点 | 如果只看原始说明，容易知道“是什么”，但面试时讲不出背景、问题、措施、收益和案例。 |
| 举措 | 围绕该文件主题补齐面试话术、具体案例、背景痛点举措收益、英文专业术语解释和复习抓手。 |
| 收益 | 学习时能快速建立业务语境，面试时能用结构化表达说明为什么做、怎么做、带来什么价值。 |

### 面试话术怎么回答

> 这份材料我会按“背景—痛点—举措—收益”来讲：背景是 Agent 能力需要被资产化和评测；痛点是执行不稳定、触发不准、安全边界不清；举措是用 Skill 固化流程，用指标和 CI gate 做验证；收益是让能力可复用、可比较、可回归。

### 具体案例是什么

以 SkillSentry 为例：先读取 Skill 或评测材料，再构造样本执行 Agent，最后用评分器和报告判断质量是否达标。

### 专业术语解释

| 中文术语 | 英文术语 | 专业解释 | 白话解释 |
|---|---|---|---|
| Skill | Skill | 面向 Agent 的结构化任务说明、流程和约束包。 | 给 AI 的专业说明书。 |
| Agent | Agent | 能围绕目标规划步骤、调用工具并交付结果的 AI 系统。 | 会自己安排步骤做事的 AI。 |
| Evaluation | Evaluation | 用样本、指标和评分规则系统衡量效果。 | 统一考试和打分。 |

### 复习抓手

1. 先用一句话说清这个文件的主题。
2. 再用“背景—痛点—举措—收益”解释它为什么重要。
3. 最后补一个 SkillSentry 或业务场景案例，证明你不是只背概念。
