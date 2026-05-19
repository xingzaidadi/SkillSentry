---
name: skill-eval-测评
version: "9.0.0"
description: >
  SkillSentry - AI Skill 质量测评系统。Each run is a fresh execution. Current SKILL.md and session state override memory.
  触发场景:说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  ⚠️ 强制执行规则:当用户消息匹配上述触发词时,你必须先读取本 skill 的 SKILL.md 并按其流程执行,禁止跳过 skill 直接编排 subagent 或自行执行测评流程。
  ⚠️ 旧记忆警告:memory 中的旧版 SkillSentry 执行记录都可能过时。当前版本要求用飞书 V2 卡片选择 Skill 和模式,并优先调用确定性脚本。
  不触发场景:讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
metadata:
  author: 刘四星
  created_at: "2026-03-27"
---

# SkillSentry v9.0 调度器

本文件只保留路由、交互和禁区规则。机械流程交给 `scripts/`，语义判断交给子工具 subagent。当前契约以本文件和 `references/current-contract.md` 为准。

优先级:当前用户请求 > 当前 SKILL.md > 本次读取的 references/文件 > 本次工具输出 > 对话历史 > memory。

## 当前口径

- 主流程评分报告步骤叫 `grader-report`:由 `sentry-grader` 完成断言评审、`grading-summary.json` 和 `report.html`。
- `sentry-report` 只用于已有 grading 后独立重出报告;不作为主 pipeline 的常规评分步骤。
- 正式静态工具叫 `sentry-static`;`sentry-lint` / `sentry-trigger` / `sentry-check` 仅是兼容/历史口径。
- 正式发布结论为 `PASS / CONDITIONAL PASS / FAIL`;正式等级为 `S/A/B/C/D/F`;`Pass³` 和 `L0-L5` 仅作为历史/方法论资料。
- `mcp_based + smoke/quick` 默认跳过 without_skill;`mcp_based + standard/full` 保留可比较 baseline,无法裸跑的单个 eval 才逐条跳过。
- `scripts/sentry_gate.py` 是原 Tool-as-Code 方案中 `sentry-score` 的当前落地形态:它聚合 grading,计算通过率、等级、Delta、IFR、否决项和最终 verdict。

## Tool-as-Code 边界

SkillSentry 不能改成一次 Function Call。可代码化的是状态、pipeline、同步、发布、门禁计算;不能代码化的是业务语义推理。

| 类型 | 交给代码 | 保留 LLM/subagent |
|------|----------|-------------------|
| 机械流程 | preflight、pipeline next、session transition、sync/publish JSON、gate/verdict 计算、contract lint | 无 |
| 语义任务 | 只提供输入/产物契约 | `sentry-cases` 设计用例、`sentry-grader` 语义评审、`sentry-analyzer` 归因建议 |
| 交互决策 | 记录状态和 auto-exempt 标记 | 用户确认、用例覆盖判断、降级/继续选择 |

脚本输出 JSON 是事实来源;LLM 可以解释原因和建议,但不能改写核心数值。

## 子工具

所有子工具位于 `tools/`。主调度器只派活、验收、通知用户,不直接执行子工具的业务逻辑。

| 工具 | 职责 |
|------|------|
| `sentry-static` | 静态规则检查 + 触发率(TP/TN),兼容 lint/trigger/check 子命令 |
| `sentry-cases` | 测试用例设计,输出 `evals.json` |
| `sentry-executor` | 执行 with_skill / without_skill 用例,输出 transcript 和 response |
| `sentry-grader` | 主流程 `grader-report`:断言评审 + 汇总 + `report.html` |
| `sentry-report` | 独立重出报告:已有 grading 后重新生成 `report.html` |
| `sentry-comparator` | with vs without 盲测对比,仅 standard/full |
| `sentry-analyzer` | 解盲分析 + 改进建议,仅 full |
| `sentry-sync` | 飞书 Bitable 同步 |
| `sentry-openclaw` | OpenClaw 环境适配 |

## 确定性脚本

优先调用这些脚本,不要在主会话中手写等价逻辑。

| 脚本 | 用途 |
|------|------|
| `scripts/sentry_preflight.py` | 定位被测 Skill、读取 frontmatter、计算 hash、识别 skill_type、检查 config 和 cases 缓存 |
| `scripts/sentry_pipeline.py` | 输出合法 pipeline、下一步、步骤类型、工具和 required artifacts |
| `scripts/sentry_state.py` | 初始化/读取/写入 `session.json`,校验 transition,写入 milestone evidence |
| `scripts/sentry_gate.py` | `sentry-score` 落地形态;聚合 grading 并计算最终 gate/verdict |
| `scripts/sentry_ci.py` | CI 编排入口;支持 `--timeout-per-eval` 和 `session.json.case_warnings` |
| `scripts/sentry_sync.py` | sync 步骤稳定 JSON wrapper;无飞书配置时写入 `skipped_no_config` |
| `scripts/sentry_publish.py` | publish 步骤稳定 JSON wrapper;生成本地发布结果 |
| `scripts/sentry_contract_lint.py` | 检查 SkillSentry 本体当前口径漂移 |
| `scripts/sentry_article_lint.py` | 检查文章材料当前口径漂移 |

常用命令:

```bash
python scripts/sentry_preflight.py --skill <Skill名> --mode quick
python scripts/sentry_pipeline.py plan --mode quick --format text
python scripts/sentry_pipeline.py next --session-dir <session_dir> --format text
python scripts/sentry_pipeline.py describe <step> --format text
python scripts/sentry_state.py transition <session_dir> <step>
python scripts/sentry_gate.py <session_dir>
python scripts/sentry_sync.py sync-pull --skill <Skill名> --session-dir <session_dir>
python scripts/sentry_publish.py --session-dir <session_dir>
```

## 执行路由

详细运行平台、auto-exempt、特殊命令、Step 0-3 调度循环和验收通知规则见 `references/runtime-router-guide.md`。主文件只保留调度原则:

- 主会话只做三件事:派活、验收、通知用户。
- 合法 pipeline 只来自 `scripts/sentry_pipeline.py`;不要在主会话维护数组副本。
- 每步完成后必须验收 `sentry_pipeline.py describe <step>` 列出的 required artifacts。
- 缓存命中也必须展示摘要,禁止只写「缓存命中,跳过」。
- `继续` / `resume` 必须读取 `session.json.last_step`,从 pipeline 下一步继续。
- OpenClaw 交互细则、V2 卡片、checkpoint 和 auto-exempt 规则全部按 `references/runtime-router-guide.md` 执行。

## 禁区

- 禁止凭 memory 代替读取当前 SKILL.md、子工具 SKILL.md 或脚本输出。
- 禁止主会话手写 `evals.json` 替代 `sentry-cases`。
- 禁止主会话直接评审回答质量替代 `sentry-grader`。
- 禁止手算通过率、等级、Delta、IFR 或 verdict;必须调用 `sentry_gate.py` 或复用 `build_gate()`。
- 禁止静默跳过 sync;无配置也要由 `sentry_sync.py` 写入 `skipped_no_config`。
- 禁止把独立重出报告工具 `sentry-report` 当作主流程评分步骤;主流程评分报告是 `grader-report`。
- 禁止自动模式跳过 auto-exempt 用户确认。

## Sync / Gate / Publish

- sync 是正式 pipeline 步骤。调用 `sentry_sync.py`;无 `config.json` 时返回并写入 `skipped_no_config`。
- gate 在 standard/full 强制执行。调用 `sentry_gate.py`,它就是当前 `sentry-score` + release gate。
- publish 调用 `sentry_publish.py` 生成稳定本地结果;需要交互式飞书上传/所有权转让时再走 legacy `scripts/publish.py`。
- Pipeline 准出标准见 `references/current-contract.md` 和 `references/step-contracts.md`;session schema 见 `references/session-json-schema.md`。

*v9.0.0 · 契约收敛版:把机械步骤交给代码、把推理步骤留给 LLM · 2026-05-14*
