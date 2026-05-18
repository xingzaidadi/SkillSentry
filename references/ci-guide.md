# SkillSentry CI 使用指南

## 前置条件

| 依赖 | 说明 |
|------|------|
| Python 3.11+ | 运行 CI 脚本 |
| `anthropic` SDK | `pip install anthropic`（cases/grader 用） |
| `claude` CLI | `npm i -g @anthropic-ai/claude-code`（executor 用） |
| `ANTHROPIC_API_KEY` | 环境变量，Anthropic API 密钥 |

## 快速开始

```bash
cd ~/.claude/skills/SkillSentry

# Smoke 测评（最快，CI 默认）
python scripts/sentry_ci.py --skill em-reimbursement-v3 --mode smoke

# Quick 测评（PR 合并前）
python scripts/sentry_ci.py --skill my-skill --mode quick --threshold 0.85

# Regression（复用已有 cases）
python scripts/sentry_ci.py --skill my-skill --mode regression --cases ./inputs/my-skill/cases.cache.json

# 指定输出目录和 model
python scripts/sentry_ci.py --skill my-skill --mode smoke \
  --output-dir ./ci-results \
  --model claude-sonnet-4-6 \
  --verbose
```

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | PASS |
| 1 | CONDITIONAL PASS 或 FAIL（需要人工确认或不允许发布） |
| 2 | ERROR（pipeline 步骤失败、找不到 Skill 等） |

`--github-output` 会写入 `verdict/status/release_status/exit_code/report_html/session_report_html/diagnostic_categories/authoritative_pass_rate/grade`。其中 `status`/`release_status` 取值为 `pass`、`conditional`、`fail` 或 `error`。

GitHub Checks 结论映射:

| release_status | Checks conclusion |
|----------------|-------------------|
| `pass` | `success` |
| `conditional` | `action_required` |
| `fail` | `failure` |
| `error` | `failure` |

## 架构

```
sentry_ci.py (编排入口)
  ├── cases/check 步骤 → ci_grader.call_llm() → Anthropic SDK 直调
  ├── executor 步骤   → ci_executor.py → claude CLI subprocess
  ├── grader 步骤     → ci_grader.grade_all_evals() → Anthropic SDK 直调
  └── 结果汇总        → ci_eval.py 逻辑（collect + compute + verdict）
```

**为什么两层调用**：
- cases/grader 是纯文本推理（不需要 tool use），用 SDK 直调更可控（超时、重试、token 控制）
- executor 需要执行被测 Skill（可能调用文件读写等工具），必须用 claude CLI

## Pipeline 模式

| 模式 | 步骤 | 适用场景 | 预计耗时 |
|------|------|---------|---------|
| smoke | cases → executor → grader | CI 默认、日常检查 | 3-8 min |
| quick | check → cases → executor → grader | PR 合并前 | 10-20 min |
| regression | executor → grader | 代码无变更，验证环境 | 2-5 min |

## MCP Skill 降级策略

`skill_type=mcp_based` 的 Skill 在 CI 环境中如果缺少 MCP Server 或 without-skill baseline 条件,必须通过 preflight/diagnostics 记录环境事实。当前正式发布结论只使用 `PASS` / `CONDITIONAL PASS` / `FAIL` / `ERROR`;不再输出历史 `DEGRADED` verdict。

## 成本估算

| 模式 | API Token 消耗 | 估算费用 |
|------|---------------|---------|
| smoke（4-5 用例） | ~50K tokens | $0.5-1.5 |
| quick（含 check+cases+执行） | ~150K tokens | $2-4 |
| regression（复用 cases） | ~30K tokens | $0.3-0.8 |

## GitHub Actions 配置

workflow 文件 `.github/workflows/skill-eval.yml` 已配置：
- 变更检测：只对修改了 SKILL.md 的 Skill 触发测评
- 直接调用 `scripts/sentry_ci.py`,不再通过交互式 LLM prompt + 旧 `ci_eval.py` 汇总
- Matrix 并行：多个 Skill 变更时并行测评
- Artifact 上传：测评产物保留 30 天
- GitHub Checks：结果推送到 PR 的 Checks 面板

### 手动触发

在 GitHub Actions 页面选择 "Run workflow"，输入 Skill 名称和模式即可。

## 自定义阈值

```bash
# 宽松（探索阶段）
python scripts/sentry_ci.py --skill my-skill --threshold 0.6

# 严格（上线前）
python scripts/sentry_ci.py --skill my-skill --threshold 0.9 --mode quick
```

## 产物说明

CI 运行后在 `--output-dir` 下生成：

| 文件 | 说明 |
|------|------|
| `eval_result.json` | 结构化结果（verdict + summary + reasons + diagnostics,含 preflight 事实） |
| `summary.md` | GitHub Step Summary 格式的结果摘要,包含 `Execution Diagnostics` |
| `report.html` | 每次 CI 都生成的稳定 HTML artifact;preflight 失败也会生成 |

`report.html` 由 `scripts/sentry_report.py` 统一生成。该工具是 `no-llm, no-network`,可单独从已有结果重出报告:

```bash
python scripts/sentry_report.py --result ci-eval-results/<skill>/eval_result.json --output report.html
python scripts/sentry_report.py --session-dir sessions/<skill>/<run>
```

`evals.json` 可执行性 warning 由 `scripts/sentry_case_lint.py` 统一检查。该工具同样是 `no-llm, no-network`,可在不跑 executor/grader 的情况下提前检查用例:

```bash
python scripts/sentry_case_lint.py --cases evals.json --format json
python scripts/sentry_case_lint.py --cases evals.json --session-dir sessions/<skill>/<run>
```

Session 目录下额外产物：
- `evals.json` — 生成的测试用例
- `eval-N/with_skill/outputs/response.md` — 每个用例的执行响应
- `eval-N/with_skill/outputs/transcript.md` — 完整交互记录
- `eval-N/grading.json` — 断言评审结果,包含 `duration_ms` / `timing.grader_duration_ms` 单用例 grader 耗时观测
- `executor_results.json` — 执行器汇总
- `report.html` — session 已创建时的 HTML 报告;pipeline 中途失败也会补最小兜底报告

executor 可通过稳定 wrapper 单独运行。该入口会调用 Claude CLI,属于重步骤,但会输出稳定 JSON 并更新 session:

```bash
python scripts/sentry_executor.py --evals evals.json --skill SKILL.md --session-dir sessions/<skill>/<run> --variant with_skill
python scripts/sentry_executor.py --evals evals.json --skill SKILL.md --session-dir sessions/<skill>/<run> --variant without_skill
```

grader-report 也可单独运行。该入口会调用 SDK/LLM,属于重步骤,但只读取已有 executor 输出,不会重跑 executor:

```bash
python scripts/sentry_grader.py --evals evals.json --session-dir sessions/<skill>/<run>
```

轻量 profile 由 `sentry_run.py` 统一组合:

```bash
python scripts/sentry_run.py --skill my-skill --profile preflight
python scripts/sentry_run.py --skill my-skill --profile lint --cases evals.json
python scripts/sentry_run.py --session-dir sessions/<skill>/<run> --profile debug
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json
python scripts/sentry_run.py --skill my-skill --profile local --cases evals.json --reuse-session sessions/<skill>/<run>
```

`preflight/lint/debug` 不触发 executor/grader;`local` 只跑 with_skill + grader/report;`ci/release` 委托 `sentry_ci.py`。
`local` 会写 `manifest.json`;复用同一 session 且输入 hash 未变时,会复用已准备的 `evals.json`/case lint 摘要并跳过 executor/grader。需要重跑重步骤时使用 `--force-executor` 或 `--force-grader`。
`--format json` 输出包含 `timings.total_ms` 和 `timings.phases_ms`;这些耗时字段用于定位慢阶段,不参与评分或退出码判断。
完整 CI 运行会在 `session.json.ci_step_timings` / `ci_phase_timings` 记录每个 pipeline step 和非 pipeline phase 的耗时,并在 `eval_result.json.timings`、`diagnostics.timings` 和 `summary.md` 中展示;diagnostics/summary/HTML 也会展示 executor/grader 单用例 avg/p50/p95/max、最慢项和确定性 timing hints。这些字段只做观测,不改变 pipeline 步骤、gate 或退出码。
可用 `python scripts/sentry_timing.py --input <eval_result.json|session_dir>` 单独分析最慢 step/phase;当能定位到 session 时,还会读取 `executor_results.json` 汇总 executor per-eval avg/p50/p95/max 和最慢用例,并读取 `grading.json` 的 `duration_ms` 汇总 grader per-eval 耗时。该工具只读 artifact,不调 LLM、不联网。
