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
| 0 | PASS（或 DEGRADED，不阻断 CI） |
| 1 | FAIL（通过率低于阈值） |
| 2 | ERROR（pipeline 步骤失败、找不到 Skill 等） |

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

`skill_type=mcp_based` 的 Skill 在 CI 环境中无法执行（无 MCP Server），自动降级：
- 只运行 `cases` 步骤（验证用例设计覆盖度）
- 跳过 executor 和 grader
- 返回 `DEGRADED` verdict（exit 0，不阻断 CI）

## 成本估算

| 模式 | API Token 消耗 | 估算费用 |
|------|---------------|---------|
| smoke（4-5 用例） | ~50K tokens | $0.5-1.5 |
| quick（含 check+cases+执行） | ~150K tokens | $2-4 |
| regression（复用 cases） | ~30K tokens | $0.3-0.8 |

## GitHub Actions 配置

workflow 文件 `.github/workflows/skill-eval.yml` 已配置：
- 变更检测：只对修改了 SKILL.md 的 Skill 触发测评
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
| `eval_result.json` | 结构化结果（verdict + summary + reasons） |
| `summary.md` | GitHub Step Summary 格式的结果摘要 |

Session 目录下额外产物：
- `evals.json` — 生成的测试用例
- `eval-N/with_skill/outputs/response.md` — 每个用例的执行响应
- `eval-N/with_skill/outputs/transcript.md` — 完整交互记录
- `eval-N/grading.json` — 断言评审结果
- `executor_results.json` — 执行器汇总
