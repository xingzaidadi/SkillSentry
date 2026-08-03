# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

支持平台：**Claude Code** · **OpenCode** · **OpenClaw（飞书）**

> 文档总览和历史归档说明见 `references/README.md`。

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
| `scripts/sentry_gate.py` | 原方案 `sentry-score` 的当前落地形态;聚合 grading,计算 `authoritative_pass_rate`、等级、Delta 状态、IFR、否决项、V2 门禁策略和最终 verdict。 |
| `scripts/sentry_ci.py` | CI 编排入口;用 `--timeout-per-eval` 控制单用例 executor 超时,并在 `session.json.case_warnings` 记录不可执行用例风险。 |
| `scripts/sentry_case_lint.py` | 独立轻量用例可执行性检查,读取 `evals.json` 并输出 `case_warnings`,不调 LLM、不跑 executor。 |
| `scripts/sentry_executor.py` | executor 稳定 wrapper,调用 `ci_executor.py` 执行 with/without_skill,输出 JSON 并更新 session。 |
| `scripts/sentry_grader.py` | grader-report 稳定 wrapper,调用 `ci_grader.py` 评审已有 response,写 summary/report 并更新 session。 |
| `scripts/sentry_run.py` | profile 组合器;`preflight/lint/debug` 跑轻路径,`local` 跑已有 cases 的本地单边测评,`ci/release` 委托完整 CI。 |
| `scripts/sentry_static.py` | 确定性静态检查入口,支持 lint-only、trigger-only 和 JSON 输出,用于快速发现 SKILL.md 结构/安全/触发风险。 |
| `scripts/sentry_trigger_eval.py` | 触发率测评入口;默认给出确定性启发式估算,`--precise` 在本机有 Claude CLI 时尝试真实触发探测,否则显式标记 skipped。 |
| `scripts/sentry_optimize_description.py` | description 优化助手;对触发 prompts 做 60/40 train/test 分割,输出触发命中摘要和非破坏性的建议 description。 |
| `scripts/sentry_methodology_v2.py` | V2 方法论分析器;输出路由矩阵、失败归因 taxonomy、污染/采样协议、工具参数级评分、grader 校准和 benchmark adapter 映射;CLI 运行时会写出 `sampling-plan.json`/`sampling-result.json`。 |
| `scripts/sentry_reuse.py` | 复用 miss reason 到排查 hint 的共享映射,供 run/timing 输出使用。 |
| `scripts/sentry_diagnostics.py` | 聚合 CI 诊断:用例可执行性、executor 失败/超时、grader 错误、sync 降级、Delta 状态和 publish 状态。 |
| `scripts/sentry_timing.py` | 独立轻量耗时分析器,读取 `eval_result.json`、`sentry-run-result.json` 或 session,输出最慢 step/phase、executor per-eval 耗时分布、grader per-eval 耗时分布、local 复用决策和优化建议;不调 LLM、不联网。 |
| `scripts/sentry_report.py` | 独立轻量报告生成器,只读取已有 session/result artifact 并生成 HTML,不调 LLM、不联网。 |
| `scripts/report_server.py` | 本地报告浏览器/live viewer,可指向 sessions 根目录浏览最新 `report.html`。 |
| `scripts/sentry_sync.py` | 包装 `sync_cases.py`,为 `sync-pull`/`sync-push-*` 输出稳定 JSON,无配置时显式 `skipped_no_config`。 |
| `scripts/sentry_publish.py` | 包装发布步骤,生成本地 `publish-result.json`/报告兜底,保留 `publish.py` 交互发布入口。 |
| `scripts/sentry_contract_lint.py` | 扫描 SkillSentry 本体是否混入旧工具名、旧指标或旧 pipeline 口径。 |
| `scripts/sentry_article_lint.py` | 扫描文章仓库是否把历史术语误写成当前口径。 |

这些脚本是 Tool-as-Code 改造的第一阶段:把确定性状态、门禁逻辑和口径自检交给代码,把用例设计、语义评审、盲测对比和失败归因继续留给 LLM。方案里的 `sentry-score` 在当前实现中统一命名为 `sentry_gate.py`,因为它不只算分,还产出发布门禁 verdict。

`scripts/verify_ci_modes.py` 会模拟 heavy LLM 步骤,并让真实 state/sync/comparator/analyzer/gate/publish 代码跑完 `smoke / quick / regression / standard / full` 五种模式,用于确认不是只支持 smoke。

`scripts/verify_deterministic.py` 是本体确定性自检聚合入口;默认 core 模式串行运行 contract lint、executor/grader/run/local dogfood、report、timing、diagnostics、exit contract、Checks、自检 workflow、workflow action 版本和 dashboard 回归,`--full` 会把 `verify_sentry_run.py` 升级为深度 local/CLI 复用矩阵,并额外运行 preflight、case feasibility、failure report 和五种 CI mode 编排。`.github/workflows/skillsentry-self-test.yml` 是本体自检 GitHub Actions,会在 SkillSentry 本体代码变更时运行 core 自检;手动 `workflow_dispatch full=true` 会运行 full 自检。`references/workflows/skillsentry-self-test.yml` 保留同内容模板,方便审阅和漂移检查。这个 workflow 不复用被测 Skill 的 `skill-eval.yml` 主流程。`scripts/verify_ci_preflight.py` 会验证 CI 启动前的环境事实被写入 session 和 diagnostics。`scripts/verify_ci_feasibility.py` 会验证 `sentry_case_lint.py` 能独立检查 `evals.json` 并写入 `session.json.case_warnings`。`scripts/verify_sentry_executor.py` 用 fake `claude` 验证 `sentry_executor.py` 的 CLI、session 更新和 mcp_based without_skill skip。`scripts/verify_sentry_grader.py` 用确定性失败响应验证 `sentry_grader.py` 的 CLI、summary/report 产物和 session 更新。`scripts/verify_sentry_run.py` 默认同进程验证 profile API、plan、local dry-run 和 delegated CI 命令构造;加 `--full` 才跑 CLI help、lint/debug 子进程、真实 local 复用边界矩阵和 delegated CI JSON。`scripts/verify_local_dogfood.py` 用 fake Claude CLI 验证 local 首跑、默认 session root、manifest 产物和 `--reuse-session auto` 复用;加 `--real` 时会使用本机真实 Claude CLI 和真实 skill 做 smoke dogfood。`scripts/verify_ci_diagnostics.py` 会验证 CI JSON、GitHub summary Markdown 和最小 HTML 报告都包含执行诊断,不再只输出 verdict/grade。`scripts/verify_ci_failure_report.py` 会验证 preflight/pipeline 失败时仍会生成稳定 `report.html` artifact。`scripts/verify_sentry_report.py` 会验证独立 report 工具可从 session 或 `eval_result.json` 重新生成 HTML,且不会覆盖真实交互报告。`scripts/verify_sentry_timing.py` 会验证独立 timing 工具可从 `eval_result.json`、`sentry-run-result.json` 或 session 读取耗时,并排序慢 step、executor 用例、已有 grader 用例耗时和 local 复用决策。`scripts/verify_ci_exit_contract.py` 会验证 `PASS=0`、`CONDITIONAL PASS=1`、`FAIL=1`、`ERROR=2` 和 GitHub output 字段。`scripts/verify_ci_checks_integration.py` 会验证 workflow/Checks 使用 `sentry_ci.py` 的新输出契约。`scripts/verify_self_test_workflow.py` 会验证本体自检 workflow 不引入真实 LLM、secrets 或完整 CI 入口,且 live workflow 与模板一致。`scripts/verify_workflow_action_versions.py` 会验证 workflow 使用 Node 24 兼容的 `actions/checkout@v6` 和 `actions/setup-python@v6`。

`scripts/verify_dashboard.py` 会验证 dashboard 扫描历史 `session.json` 时能读取 UTF-8 BOM 文件,避免 Windows 生成的 session 被统计时静默跳过。

需要真实调用 executor/grader 时,可用内置 fixture 跑一次 regression:

```bash
set SKILLSENTRY_CI_LLM_FALLBACK=claude
python scripts/sentry_ci.py --skill tests/fixtures/ci_modes/fixture-skill/SKILL.md --mode regression --cases tests/fixtures/ci_modes/evals.json --model sonnet --executor-model sonnet --timeout-per-eval 90
```

这条命令会调用 Claude CLI,所以不放进默认确定性回归。

也可以用 local dogfood 入口专门验证本地轻路径和复用:

```bash
python scripts/verify_deterministic.py --format json
python scripts/verify_deterministic.py --full --format json
python scripts/verify_local_dogfood.py --format json
python scripts/verify_local_dogfood.py --real --format json
python scripts/verify_methodology_v2.py --format json
python scripts/verify_gate_methodology_v2.py --format json
```

`verify_deterministic.py` 是推荐的本体自检入口;默认 core 模式约 15 秒,`--full` 会多跑 CLI 子进程、local 复用矩阵、CI mode 等宽回归。`verify_local_dogfood.py` 第一条使用 fake Claude CLI,不联网、不依赖账号余额;第二条使用本机真实 Claude CLI 和真实 skill,用于改动 local profile 后做一次端到端 smoke。

触发率、静态风险和 description 优化可用下面的轻量入口先跑一遍:

```bash
python scripts/sentry_static.py SKILL.md --format json
python scripts/sentry_trigger_eval.py SKILL.md --precise --format json
python scripts/sentry_optimize_description.py SKILL.md --format json
python scripts/sentry_methodology_v2.py sessions/<run> --format json
python scripts/report_server.py --base-dir sessions --port 18080
```

其中 `sentry_trigger_eval.py --precise` 会优先尝试 Claude CLI;本机不可用时不会失败,而是输出明确的 skipped precise 状态并保留确定性估算结果。`sentry_optimize_description.py` 默认只给建议,不直接改写 `SKILL.md`,避免把 train 集合过拟合到正式 description。

---

## 入口怎么选

日常本地排查先用 `sentry_run.py` 的轻量 profile；需要完整发布门禁或 GitHub 集成时直接用 `sentry_ci.py`。

| 目标 | 推荐入口 | 说明 |
|------|----------|------|
| 只看 Skill 是否可定位、hash/cache/runtime 是否正常 | `python scripts/sentry_run.py --skill <skill> --profile preflight` | 不生成用例、不跑 executor/grader |
| 日常静态检查和 evals 可执行性检查 | `python scripts/sentry_run.py --skill <skill> --profile lint --cases evals.json` | 只跑确定性轻检查 |
| 先看本次会跑什么、不实际执行 | `python scripts/sentry_run.py --skill <skill> --profile plan --mode smoke` | 用于估算步骤和重步骤 |
| 本地复跑已有 cases,优先复用上次结果 | `python scripts/sentry_run.py --skill <skill> --profile local --cases evals.json --reuse-session auto` | 只跑 with_skill + grader/report,可跳过命中的重步骤 |
| CI、发布门禁、GitHub Checks | `python scripts/sentry_ci.py --skill <skill> --mode quick` | 保持完整 CI/release 契约 |

---

## 轻量 Profile

日常使用优先从 `sentry_run.py` 进入,避免默认跑完整 CI:

```bash
python scripts/sentry_run.py --skill my-skill --profile preflight
python scripts/sentry_run.py --skill my-skill --profile plan --mode smoke
python scripts/sentry_run.py --skill my-skill --profile lint --cases evals.json
python scripts/sentry_run.py --session-dir sessions/<skill>/<run> --profile debug
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json --dry-run
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json --reuse-session auto
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

`local` 会写 `manifest.json`,记录 executor/grader 的输入 hash 和产物路径。再次传入 `--reuse-session` 且输入未变时,会复用已准备的 `evals.json`/case lint 摘要以及已有 `executor_results.json`、`grading-summary.json`、`report.html` 和 `eval-*/grading.json`,跳过重复准备、executor、grader;payload 会在 `cases.reuse.reason`、`executor.reuse.reason`、`grader.reuse.reason` 说明复用命中或未命中原因,并在 `reuse_summary` 汇总 reused/rerun steps、miss reasons 和排查 hints。需要强制重跑重步骤时使用 `--force-executor` 或 `--force-grader`。

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
│   ├── sentry_static.py        # 静态 lint + 触发启发式估算
│   ├── sentry_trigger_eval.py  # 触发率估算/可选 Claude CLI 精确探测
│   ├── sentry_optimize_description.py # 60/40 description 优化助手
│   ├── sentry_methodology_v2.py # 路由/归因/污染/calibration/benchmark 分析
│   ├── sentry_diagnostics.py   # CI/publish 执行诊断聚合
│   ├── sentry_reuse.py         # local 复用诊断 hint 共享模块
│   ├── sentry_report.py        # no-LLM/no-network HTML 报告生成器
│   ├── report_server.py        # sessions/report.html 本地浏览器
│   ├── sentry_sync.py          # sync 步骤稳定 JSON wrapper
│   ├── sentry_publish.py       # publish 步骤稳定 JSON wrapper
│   ├── sentry_contract_lint.py # SkillSentry 当前口径自检
│   ├── sentry_article_lint.py  # 文章当前口径自检
│   ├── verify_deterministic.py # 本体确定性自检聚合入口
│   ├── verify_ci_preflight.py  # CI 预检证据回归
│   ├── verify_ci_feasibility.py # CI 用例可执行性 warning 回归
│   ├── verify_sentry_executor.py # executor wrapper 回归
│   ├── verify_sentry_grader.py # grader wrapper 回归
│   ├── verify_sentry_run.py    # profile 组合器回归
│   ├── verify_local_dogfood.py # local 首跑/复用 dogfood 回归
│   ├── verify_methodology_v2.py # V2 方法论分析回归
│   ├── verify_gate_methodology_v2.py # V2 门禁策略回归
│   ├── verify_ci_modes.py      # 五种 CI 模式编排回归
│   ├── verify_ci_diagnostics.py # CI 诊断输出回归
│   ├── verify_ci_failure_report.py # CI 失败报告 artifact 回归
│   ├── verify_sentry_report.py # 独立 report 工具回归
│   ├── verify_ci_exit_contract.py # CI 退出码/GitHub output 回归
│   ├── verify_ci_checks_integration.py # Actions/Checks 集成回归
│   ├── verify_self_test_workflow.py # 本体自检 workflow 漂移检查
│   ├── verify_workflow_action_versions.py # Actions runtime 版本回归
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
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\README.md` |
| 学习重点 | README |
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
