# CHANGELOG - SkillSentry 版本历史

> 主 SKILL.md 仅保留最近 3 个版本，旧版本记录于此。

## v9.1.0 · 2026-05-18
- **轻量可组合工具链**：将 `sentry_ci.py` 内的报告、用例可执行性检查、executor、grader 能力拆成独立脚本,完整 CI 契约保持不变。
- 新增 `scripts/sentry_report.py`: 从已有 session 或 `eval_result.json` 重出稳定 HTML 报告;`no-llm, no-network`;默认不覆盖真实交互式 grader 报告。
- 新增 `scripts/sentry_case_lint.py`: 独立检查 `evals.json` / `cases.cache.json` 的可执行性风险,写入 `case_warnings` / `case_lint`;不调 LLM、不跑 executor。
- 新增 `scripts/sentry_executor.py`: 包装 `ci_executor.py`,提供 with_skill / without_skill 独立入口,输出稳定 JSON 并更新 session。
- 新增 `scripts/sentry_grader.py`: 包装 `ci_grader.py`,对已有 executor response 单独执行 grader-report,写 `grading-summary.json`、`report.html` 和 session 状态。
- 新增 `scripts/sentry_run.py`: profile 组合器,支持 `preflight / lint / debug / local / ci / release`;轻 profile 不触发 executor/grader,`ci/release` 委托完整 `sentry_ci.py`。
- `sentry_run.py --profile local --reuse-session <session>` 新增 `manifest.json` 复用机制;输入 hash 未变时跳过 executor/grader,可用 `--force-executor` / `--force-grader` 显式重跑。
- `--reuse-session` 复用已有 session 时刷新 `session.json` 技能 hash/profile 元数据,并补充 cases/SKILL/force executor/force grader 复用失效回归覆盖。
- `--reuse-session` 在用例输入 hash 未变时复用已准备的 `evals.json` 与 case lint 摘要,减少本地重复运行的 I/O 和确定性检查成本。
- executor 复用会同时校验每个用例的 `response.md` 产物,避免残缺 session 误跳过 executor。
- `sentry_run.py --format json` 新增 `timings.total_ms` / `timings.phases_ms` 阶段耗时观测,用于比较轻量 profile 与复用路径成本。
- `evals.json` / `cases.cache.json` 读取兼容 UTF-8 BOM,避免 Windows/PowerShell 生成的用例文件解析失败。
- `sentry_ci.py` 现在复用 `sentry_report.py`、`sentry_case_lint.py`、`sentry_executor.py`、`sentry_grader.py`,保留原有 pipeline、artifact、exit code、GitHub output 和 Checks 契约。
- 新增确定性回归脚本:`verify_sentry_report.py`、`verify_sentry_executor.py`、`verify_sentry_grader.py`、`verify_sentry_run.py`;`verify_ci_feasibility.py` 改为覆盖 `sentry_case_lint.py` CLI。
- 文档同步: README、`references/current-contract.md`、`references/ci-guide.md`、`references/step-contracts.md` 明确轻 profile、wrapper 边界和 manifest 复用规则。

## v9.0.0 · 2026-05-14
- **契约收敛版**：不新增测评维度，专注统一执行契约和文档口径。
- 主 pipeline 将 `grader` + `report` 收敛为 `grader-report`，由 `sentry-grader` 同一 subagent 完成评分和 HTML 报告。
- `sentry-report` 保留为独立重出报告工具，仅在已有 grading 后调用。
- 统一 `skip_without_skill` 规则：`mcp_based + smoke/quick` 默认跳过；`mcp_based + standard/full` 默认保留可比较 without_skill 侧，逐 eval 可跳过。
- 新增 `references/current-contract.md` 作为当前术语和执行契约的冲突消解入口。
- 新增 `VERSION` 文件；`.gitignore` 忽略 `config.json`、本地配置和备份文件。
- 当前正式术语：`PASS/CONDITIONAL PASS/FAIL`、`S/A/B/C/D/F`、`authoritative_pass_rate`；`Pass³`、`L0-L5` 仅作为历史/方法论资料。
- 新增当前口径自检脚本：`scripts/sentry_contract_lint.py` 用于检查 SkillSentry 本体，`scripts/sentry_article_lint.py` 用于检查文章仓库，防止旧工具名和旧指标重新污染当前入口。


## v8.4.0 · 2026-05-07
- **结构性修复**：sync 步骤纳入 pipeline 状态机
  - sync-pull、sync-push-cases、sync-push-results、gate 成为正式 pipeline 步骤
  - 不再依赖主调度器"记得"执行，状态机强制顺序执行
- **根因**：⛔ 标记是描述性约束，不是结构性保障；主调度器自身执行的步骤无外部校验机制
- **设计原则**：凡是 ⛔ 标记的步骤必须入 pipeline；sync 步骤可降级(skipped_no_config)但不可跳过
- 新增：pitfall-guide 坑29（⛔标记≠执行保障）
- 保留：CI 完整能力（sentry_ci.py + ci_executor.py + ci_grader.py + workflow）

## v8.3.0 · 2026-05-03
- 合入数据污染四层模型（坑23-28）
- CI 能力对齐
- 保留：CI 完整能力

## v8.2.0 · 2026-05-03
- **融合 OpenClaw 生产线改进 + 保留 CI 能力**
- 新增：数据隔离规则（Step 2 禁止读 history.json 防锚定效应）
- 新增：进度条可视化 `[██████░░░░] 3/5 steps`
- 新增：缓存跳过展示规则详化（check/cases 缓存必须展示全量表格）
- 新增：workspace 路径分离 `~/.claude/data/skill-eval/sessions/`（数据/代码分离）
- 新增：`references/admission-criteria.md`（S/A/B/C 发布准入指标表）
- 新增：`references/faq.md`（常见问题手册）
- 新增：`references/card-templates.md`、`case-matrix-templates.md`、`custom-cases-template.md`
- 新增：`references/eval-dimensions.md`、`report-template.md`、`feishu-templates.md`
- 新增：`agents/` 目录（analyzer.md, comparator.md, grader.md subagent 角色定义）
- 新增：`DEPLOY-CHECKLIST.md`、`README.md`、`install.ps1`、`config.example.json`
- 新增：`scripts/` 报告生成系列（generate_eval_report/html_report/report + report_server）
- 新增：`scripts/analyze_requirements.py`、`sync_cases.py`、`verify_assertions.py`
- 更新：sentry-cases/executor/grader/comparator/report 各工具增量改进
- 更新：sessions_spawn timeout 600→900、降级超时 600s→900s
- 保留：CI 完整能力（sentry_ci.py + ci_executor.py + ci_grader.py + workflow）

## v8.1.0 · 2026-05-03
- **融合 v8.0.0 架构改进 + 保留 CI 能力**
- 新增：四大支柱架构（管道+状态机+降级兜底+幂等）
- 新增：pipeline 数组驱动步骤执行（session.json.pipeline）
- 新增：Checkpoint Resume（`继续`/`resume` 从断点恢复）
- 新增：Token 计量（每步 cost 字段）
- 新增：主调度器自约束检查清单
- 新增：subagent task prompt 标准注入清单
- 新增：sentry-static 三合一工具（替代 check/lint/trigger）
- 新增：sentry-comparator（standard/full 盲测对比）
- 新增：sentry-analyzer（full 根因分析）
- 新增：references/step-contracts.md、pitfall-guide.md、output-format.md、mode-levels.md
- 新增：scripts/dashboard.py（sessions 统计）
- 新增：install.sh（部署验证）
- 新增：session.json 字段 — pipeline, cost, evidence, verdict.completion_status
- 保留：CI 完整能力（sentry_ci.py + ci_executor.py + ci_grader.py + workflow）
- 保留：行为优先级一行版
- 废弃：sentry-check/sentry-lint/sentry-trigger（功能合入 sentry-static）

## v7.8.2 · 2026-04-30
- CI 完整 pipeline 实现（sentry_ci.py/ci_executor.py/ci_grader.py）
- GitHub Actions workflow 替换为确定性 sentry_ci.py 调用
- 跳过步骤必须通知用户
- references/ci-guide.md 新增

## v7.8.1 · 2026-04-30
- 修复卡片格式(text替代interactive)+稳定性改进

## v7.8.0 · 2026-04-30
- 卡片格式强制+references外移+SKILL.md瘦身

## v7.7.4 · 2026-04-29
- 模式分级+断言分级+multi_turn+空字段+多编号分隔
