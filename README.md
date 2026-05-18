# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

支持平台：**Claude Code** · **OpenCode** · **OpenClaw（飞书）**

---

## 三句话速查

```
# 姿势 1：最常用，系统自动推荐工作流
测评 <Skill名>

# 姿势 2：只做某一步
check <Skill名>         →  静态检查 + 触发率（~3 分钟）
lint <Skill名>           →  30 秒静态检查
测触发率 <Skill名>       →  2 分钟验证 description
设计用例 <Skill名>       →  5-10 分钟出 evals.json，不执行
出报告                   →  1 分钟，基于已有结果

# 姿势 3：指定深度
smoke 测评 <Skill名>     →  5-7 分钟，改了规则先跑这个
quick 测评 <Skill名>     →  15-20 分钟，提测前用
full 测评 <Skill名>      →  45 分钟+，正式发布前用
```

---

## 安装（2 步）

**第一步：获取代码**

```bash
# 方式一：克隆仓库
git clone https://github.com/xingzaidadi/SkillSentry.git
cd SkillSentry

# 方式二：下载 tar.gz 并解压
tar xzf SkillSentry-v9.0.0.tar.gz
cd SkillSentry
```

**第二步：运行安装脚本**

```bash
# macOS / Linux / WSL
bash install.sh
```

```powershell
# Windows PowerShell
.\install.ps1
```

脚本自动检测平台（Claude Code / OpenCode / OpenClaw），部署到正确位置：

```
📦 安装到 OpenClaw（~/.openclaw/skills）
  ✅ SkillSentry（主编排 v9.0.0）
  ✅ sentry-static
  ✅ sentry-cases
  ✅ sentry-executor
  ✅ sentry-grader
  ✅ sentry-report
  📦 sentry-openclaw（归档 stub）
  📦 sentry-sync（归档 stub）
  ✅ workspace 运行时目录已创建

🎉 安装完成！
```

**验证安装**：

```
验证 SkillSentry 安装
```

---

## 第一次使用

确保你要测的 Skill 放在正确位置：

| 平台 | 路径 |
|------|------|
| Claude Code | `~/.claude/skills/<Skill名>/SKILL.md` |
| OpenCode | `~/.config/opencode/skills/<Skill名>/SKILL.md` |
| OpenClaw | `~/.openclaw/skills/<Skill名>/SKILL.md` |

然后直接说：

```
测评 <你的Skill名>
```

**不需要你选模式**——系统根据状态自动推荐：

| 你的情况 | 推荐工作流 | 时间 |
|---------|-----------|------|
| 第一次测这个 Skill | quick（完整流程） | ~15-20 分钟 |
| 改了规则，验证没崩 | smoke（快速冒烟） | ~5-7 分钟 |
| 规则没变，复跑基准 | regression（直接跑） | ~5-10 分钟 |

> **Token 消耗参考**：quick 约 5-10 万 token；smoke 约 1-2 万 token；regression 约 3-5 万 token。

---

## 工具组成（v9.0.0）

| 工具 | 职责 | 独立可用 |
|------|------|---------|
| **SkillSentry** | 主编排 + 平台适配 + 飞书同步 | — |
| **sentry-static** | 静态规则检查 + 触发率（TP/TN） | ✅ |
| **sentry-cases** | 测试用例设计，输出 evals.json | ✅ |
| **sentry-executor** | 用例并行执行，输出 transcript | ✅ |
| **sentry-grader** | 主流程 `grader-report`：断言评审 + 汇总 + 生成 report.html | ✅ |
| **sentry-report** | 独立重出报告：已有 grading 后重新生成 report.html | ✅ |

> v9.0.0 变更：主流程统一使用 **grader-report**；`sentry-report` 仅用于已有 grading 后独立重出报告。`sentry-lint` / `sentry-trigger` / `sentry-check` 作为兼容命令路由到 **sentry-static**。

### 确定性内核脚本

| 脚本 | 职责 |
|------|------|
| `scripts/sentry_preflight.py` | 定位被测 Skill、计算 hash、识别 skill_type、检查 config、cases 缓存和 Claude/SDK 运行时可用性。 |
| `scripts/sentry_pipeline.py` | 输出当前稳定口径 pipeline、下一步、步骤类型、工具和 required artifacts。 |
| `scripts/sentry_state.py` | 初始化/读取/写入 `session.json`,校验 pipeline transition,写入 milestone evidence。 |
| `scripts/sentry_gate.py` | 原方案 `sentry-score` 的当前落地形态;聚合 grading,计算 `authoritative_pass_rate`、等级、Delta 状态、IFR、否决项和最终 verdict。 |
| `scripts/sentry_ci.py` | CI 编排入口;用 `--timeout-per-eval` 控制单用例 executor 超时,并在 `session.json.case_warnings` 记录不可执行用例风险。 |
| `scripts/sentry_case_lint.py` | 独立轻量用例可执行性检查,读取 `evals.json` 并输出 `case_warnings`,不调 LLM、不跑 executor。 |
| `scripts/sentry_executor.py` | executor 稳定 wrapper,调用 `ci_executor.py` 执行 with/without_skill,输出 JSON 并更新 session。 |
| `scripts/sentry_grader.py` | grader-report 稳定 wrapper,调用 `ci_grader.py` 评审已有 response,写 summary/report 并更新 session。 |
| `scripts/sentry_run.py` | profile 组合器;`preflight/lint/debug` 跑轻路径,`local` 跑已有 cases 的本地单边测评,`ci/release` 委托完整 CI。 |
| `scripts/sentry_diagnostics.py` | 聚合 CI 诊断:用例可执行性、executor 失败/超时、grader 错误、sync 降级、Delta 状态和 publish 状态。 |
| `scripts/sentry_timing.py` | 独立轻量耗时分析器,读取 `eval_result.json`、`sentry-run-result.json` 或 session,输出最慢 step/phase、executor per-eval 耗时分布、grader per-eval 耗时分布、local 复用决策和优化建议;不调 LLM、不联网。 |
| `scripts/sentry_report.py` | 独立轻量报告生成器,只读取已有 session/result artifact 并生成 HTML,不调 LLM、不联网。 |
| `scripts/sentry_sync.py` | 包装 `sync_cases.py`,为 `sync-pull`/`sync-push-*` 输出稳定 JSON,无配置时显式 `skipped_no_config`。 |
| `scripts/sentry_publish.py` | 包装发布步骤,生成本地 `publish-result.json`/报告兜底,保留 `publish.py` 交互发布入口。 |
| `scripts/sentry_contract_lint.py` | 扫描 SkillSentry 本体是否混入旧工具名、旧指标或旧 pipeline 口径。 |
| `scripts/sentry_article_lint.py` | 扫描文章仓库是否把历史术语误写成当前口径。 |

这些脚本是 Tool-as-Code 改造的第一阶段:把确定性状态、门禁逻辑和口径自检交给代码,把用例设计、语义评审、盲测对比和失败归因继续留给 LLM。方案里的 `sentry-score` 在当前实现中统一命名为 `sentry_gate.py`,因为它不只算分,还产出发布门禁 verdict。

`scripts/verify_ci_modes.py` 会模拟 heavy LLM 步骤,并让真实 state/sync/comparator/analyzer/gate/publish 代码跑完 `smoke / quick / regression / standard / full` 五种模式,用于确认不是只支持 smoke。

`scripts/verify_ci_preflight.py` 会验证 CI 启动前的环境事实被写入 session 和 diagnostics。`scripts/verify_ci_feasibility.py` 会验证 `sentry_case_lint.py` 能独立检查 `evals.json` 并写入 `session.json.case_warnings`。`scripts/verify_sentry_executor.py` 用 fake `claude` 验证 `sentry_executor.py` 的 CLI、session 更新和 mcp_based without_skill skip。`scripts/verify_sentry_grader.py` 用确定性失败响应验证 `sentry_grader.py` 的 CLI、summary/report 产物和 session 更新。`scripts/verify_sentry_run.py` 用 fake `claude` 验证 `sentry_run.py` 的 `lint/debug/local` profiles。`scripts/verify_ci_diagnostics.py` 会验证 CI JSON、GitHub summary Markdown 和最小 HTML 报告都包含执行诊断,不再只输出 verdict/grade。`scripts/verify_ci_failure_report.py` 会验证 preflight/pipeline 失败时仍会生成稳定 `report.html` artifact。`scripts/verify_sentry_report.py` 会验证独立 report 工具可从 session 或 `eval_result.json` 重新生成 HTML,且不会覆盖真实交互报告。`scripts/verify_sentry_timing.py` 会验证独立 timing 工具可从 `eval_result.json`、`sentry-run-result.json` 或 session 读取耗时,并排序慢 step、executor 用例、已有 grader 用例耗时和 local 复用决策。`scripts/verify_ci_exit_contract.py` 会验证 `PASS=0`、`CONDITIONAL PASS=1`、`FAIL=1`、`ERROR=2` 和 GitHub output 字段。`scripts/verify_ci_checks_integration.py` 会验证 workflow/Checks 使用 `sentry_ci.py` 的新输出契约。

`scripts/verify_dashboard.py` 会验证 dashboard 扫描历史 `session.json` 时能读取 UTF-8 BOM 文件,避免 Windows 生成的 session 被统计时静默跳过。

需要真实调用 executor/grader 时,可用内置 fixture 跑一次 regression:

```bash
set SKILLSENTRY_CI_LLM_FALLBACK=claude
python scripts/sentry_ci.py --skill tests/fixtures/ci_modes/fixture-skill/SKILL.md --mode regression --cases tests/fixtures/ci_modes/evals.json --model sonnet --executor-model sonnet --timeout-per-eval 90
```

这条命令会调用 Claude CLI,所以不放进默认确定性回归。

---

## 轻量 Profile

日常使用优先从 `sentry_run.py` 进入,避免默认跑完整 CI:

```bash
python scripts/sentry_run.py --skill my-skill --profile preflight
python scripts/sentry_run.py --skill my-skill --profile lint --cases evals.json
python scripts/sentry_run.py --session-dir sessions/<skill>/<run> --profile debug
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json --reuse-session sessions/<skill>/<run>
```

| profile | 行为 | 是否重步骤 |
|---------|------|------------|
| preflight | 只定位 Skill、hash、runtime/config/cache | 否 |
| lint | preflight + `sentry_case_lint.py`;不生成 cases | 否 |
| debug | 对已有 session 重算 gate/diagnostics/report | 否 |
| local | 复用已有 cases,只跑 with_skill executor + grader/report | 是 |
| ci | 委托 `sentry_ci.py` 当前模式 | 是 |
| release | 委托 `sentry_ci.py`;默认把 smoke 升为 standard | 是 |

`local` 会写 `manifest.json`,记录 executor/grader 的输入 hash 和产物路径。再次传入 `--reuse-session` 且输入未变时,会复用已准备的 `evals.json`/case lint 摘要以及已有 `executor_results.json`、`grading-summary.json`、`report.html` 和 `eval-*/grading.json`,跳过重复准备、executor、grader;payload 会在 `cases.reuse.reason`、`executor.reuse.reason`、`grader.reuse.reason` 说明复用命中或未命中原因,并在 `reuse_summary` 汇总 reused/rerun steps 和 miss reasons。需要强制重跑重步骤时使用 `--force-executor` 或 `--force-grader`。

所有 `sentry_run.py --format json` profile 都会输出 `timings.total_ms` 与 `timings.phases_ms`,用于比较 preflight、prepare_cases、executor、grader、diagnostics 等阶段耗时;这些字段只做观测,不参与评分或退出码判断。`ci/release --format json` 会把委托 CI 的 stdout/stderr 放入 payload,保持顶层 stdout 是可解析 JSON。

---

## 工作流一览

| 工作流 | 工具链 | 时间 | 适用场景 |
|--------|--------|------|---------|
| smoke | cases → sync-pull → sync-push-cases → executor-with → grader-report → sync-push-results → publish | 5-10 分钟 | 改了规则，快速确认没崩 |
| quick | static → cases → sync-pull → sync-push-cases → executor-with → grader-report → sync-push-results → publish | 15-20 分钟 | 迭代完成，准备提测 |
| regression | sync-pull → executor-with → grader-report → sync-push-results → publish | 5-10 分钟 | 规则没变，复跑基准 |
| standard | static → cases → sync-pull → sync-push-cases → executor-with → executor-without → comparator → grader-report → sync-push-results → gate → publish | 30-45 分钟 | 重要迭代正式提测 |
| full | static → cases → sync-pull → sync-push-cases → executor-with → executor-without → comparator → analyzer → grader-report → sync-push-results → gate → publish | 45 分钟+ | 正式发布前全量验证 |

---

## 飞书同步（OpenClaw 专属）

配置 `config.json`（参考 `config.example.json`）后自动启用：

- **PULL**：执行前从飞书拉取 active 用例
- **PUSH-CASES**：新用例推送到飞书（pending_review）
- **PUSH-RESULTS**：评审结果回写到用例记录
- **PUSH-RUN**：运行记录写入飞书

不配置 = 纯本地模式，不影响核心测评流程。

---

## 报告怎么看

CI 每次运行都会在 `--output-dir/report.html` 生成稳定 HTML artifact;如果已经创建 session,中途失败时也会补 `session/report.html`。报告包含 `Execution Diagnostics` 区块,用于区分 preflight 环境问题、用例不可执行、runner 超时/错误、grader 错误、`skipped_no_config` 这类环境降级,以及真正的 Skill 质量失败。`eval_result.json` 同时输出 `timings`,来自 `session.json.ci_step_timings` / `ci_phase_timings` / `ci_timing`,用于观察每个 CI step 和非 pipeline phase 的耗时,不参与评分或退出码判断。每个实际写入的 `grading.json` 会追加 `duration_ms` / `timing.grader_duration_ms`,只做 grader 单用例耗时观测。diagnostics、summary Markdown 和 HTML 报告会展示 executor/grader 的 avg/p50/p95/max、最慢用例和确定性 timing hints;`scripts/sentry_timing.py` 也可从 `eval_result.json`、`sentry-run-result.json` 或 session 单独重算这些耗时摘要。
稳定 HTML 报告由 `scripts/sentry_report.py` 统一生成;它是 `no-llm, no-network` 的轻工具,可单独重出报告:

```bash
python scripts/sentry_report.py --session-dir sessions/<skill>/<run>
python scripts/sentry_report.py --result ci-eval-results/<skill>/eval_result.json --output report.html
```

CI 退出码固定为: `PASS=0`, `CONDITIONAL PASS=1`, `FAIL=1`, `ERROR=2`。开启 `--github-output` 时会输出 `verdict/status/release_status/exit_code/report_html/session_report_html/diagnostic_categories/timing_hints/authoritative_pass_rate/grade`。
GitHub Checks 使用同一份 `eval_result.json`: `PASS` 映射为 `success`, `CONDITIONAL PASS` 映射为 `action_required`, `FAIL/ERROR` 映射为 `failure`,并在 Check summary 里展示 report 路径、诊断分类和 `diagnostics.timing_hints`。

| 等级 | 精确通过率 | 含义 |
|------|----------|------|
| S | ≥ 95% | 可直接发布 |
| A | ≥ 90% | 可发布 |
| B | ≥ 80% | 建议修复后发布 |
| C | ≥ 70% | 需修复 |
| FAIL | < 70% | 不可发布 |

---

## 目录结构（打包格式）

```
SkillSentry/
├── SKILL.md                   # 主编排（v9.0.0）
├── VERSION
├── README.md
├── config.example.json        # 飞书同步配置模板
├── install.sh / install.ps1   # 安装脚本
├── tools/                     # 子工具（install.sh 展开到 skills/ 并列目录）
│   ├── sentry-static/SKILL.md      ← 静态检查三合一（lint + trigger + summary）
│   ├── sentry-cases/SKILL.md
│   ├── sentry-executor/SKILL.md
│   ├── sentry-grader/SKILL.md
│   ├── sentry-report/SKILL.md
│   ├── sentry-openclaw/SKILL.md   ← 归档 stub
│   ├── sentry-sync/SKILL.md       ← 归档 stub
│   ├── （已删除，合并到 sentry-static）
│   └── （已删除，合并到 sentry-static）
├── agents/
│   ├── grader.md
│   ├── comparator.md
│   └── analyzer.md
├── scripts/                   # Python 脚本
│   ├── sentry_preflight.py     # 确定性环境预检
│   ├── sentry_pipeline.py      # 当前 pipeline 单一事实来源
│   ├── sentry_state.py         # session.json 状态管理
│   ├── sentry_gate.py          # sentry-score + 发布门禁计算
│   ├── sentry_case_lint.py     # no-LLM/no-network evals 可执行性检查
│   ├── sentry_executor.py      # Claude CLI executor 稳定 wrapper
│   ├── sentry_grader.py        # Anthropic SDK/LLM grader-report wrapper
│   ├── sentry_run.py           # profile 组合器
│   ├── sentry_diagnostics.py   # CI/publish 执行诊断聚合
│   ├── sentry_report.py        # no-LLM/no-network HTML 报告生成器
│   ├── sentry_sync.py          # sync 步骤稳定 JSON wrapper
│   ├── sentry_publish.py       # publish 步骤稳定 JSON wrapper
│   ├── sentry_contract_lint.py # SkillSentry 当前口径自检
│   ├── sentry_article_lint.py  # 文章当前口径自检
│   ├── verify_ci_preflight.py  # CI 预检证据回归
│   ├── verify_ci_feasibility.py # CI 用例可执行性 warning 回归
│   ├── verify_sentry_executor.py # executor wrapper 回归
│   ├── verify_sentry_grader.py # grader wrapper 回归
│   ├── verify_sentry_run.py    # profile 组合器回归
│   ├── verify_ci_modes.py      # 五种 CI 模式编排回归
│   ├── verify_ci_diagnostics.py # CI 诊断输出回归
│   ├── verify_ci_failure_report.py # CI 失败报告 artifact 回归
│   ├── verify_sentry_report.py # 独立 report 工具回归
│   ├── verify_ci_exit_contract.py # CI 退出码/GitHub output 回归
│   ├── verify_ci_checks_integration.py # Actions/Checks 集成回归
│   ├── verify_dashboard.py  # dashboard session 扫描回归
│   ├── validate_step.py       # OpenClaw 步骤校验
│   ├── verify_proof.py        # CLI 读取证明校验
│   ├── generate_html_report.py
│   └── ...
├── references/                # 参考文档
│   ├── feishu-templates.md
│   ├── report-template.md
│   ├── execution-phases.md
│   └── ...
└── inputs/                    # 测评素材（按 Skill 名隔离）
```

---

## 常见问题

**Q：测评的 Skill 必须有 MCP 工具吗？**
A：不是。`sentry-static` 纯静态分析，不需要工具连接。执行测试时，如果被测 Skill 依赖 MCP 工具，系统会在执行前检查可用性。

**Q：第一次跑要多久？**
A：quick 模式约 15-20 分钟。之后有缓存，regression 只需 5-10 分钟。

**Q：能测自己写的任何 Skill 吗？**
A：能，只要有 `SKILL.md`。自动识别类型（mcp_based / text_generation / code_execution）。

**Q：测评中断了怎么办？**
A：已完成的 transcript 保存在 sessions/。重新说「测评 xxx」，系统检测已有结果，提示跳过。

**Q：sentry-lint / sentry-trigger / sentry-check 去哪了？**
A：当前正式工具名是 `sentry-static`。说 `lint xxx`、`测触发率 xxx` 或 `check xxx` 会自动路由到 `sentry-static` 的对应子模式。旧名称只作为兼容入口。

---

*v9.0.0 · 2026-05-14*
