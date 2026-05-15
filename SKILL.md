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

## 运行平台

| 能力 | CLI / OpenCode | OpenClaw(飞书) | CI |
|------|----------------|----------------|----|
| 子任务 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=900)` | `claude -p` + SDK |
| 输出 | 终端文本 | `message(action=send, msg_type="text")` | stdout/stderr + 文件 |
| 校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit | 文件存在性 |
| 等待 | 60s 无响应自动继续 | 等用户说「继续」 | 全自动 |

OpenClaw 输出必须使用 `message` 工具。选择 Skill/模式必须使用飞书 V2 卡片的独立 `select_static`,禁止 V1 `action` 容器、`form` 和 `button(form_action_type=submit)`;卡片失败时才用 markdown 列表兜底。

## auto-exempt

auto 模式只跳过步骤间继续确认。以下场景仍必须等待用户:

| 场景 | 原因 |
|------|------|
| MCP 预检全不可用 | 无法执行 real_data,需用户配置 MCP 或降级 |
| real_data 数据采集 | AI 禁止编造单号/ID |
| 用例设计审核 | 用户需确认覆盖度和是否补充 |
| 写操作/不可逆操作 | 安全要求 |

OpenClaw 每步完成后写入 `session.json.milestones.step-N = {msg_type, message_id, sent_at}`。

## 特殊命令

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry` / `验证测评` | 检查子工具和核心脚本是否存在 |
| `lint xxx` / `检查结构` / `有没有HiL问题` | 只跑 `sentry-static --lint-only` |
| `测触发率` / `description 准不准` | 只跑 `sentry-static --trigger-only` |
| `设计用例 xxx` / `只出 cases` | 只跑 `sentry-cases` |
| `跑用例` / `用现有用例` | `executor-with` -> `grader-report` |
| `出报告` / `重新生成报告` / `通过了吗` / `看结果` | 调 `sentry-report`,前提是已有 grading |
| `继续` / `resume` / `从断点继续` | 读取 `session.json.last_step`,从 pipeline 下一步继续 |

用户发文件并说「存到 xxx 测评素材」时,保存到 `inputs/<skill名>/`,保留原始文件名,并回执路径。

## Step 0 环境预检

每次测评先执行。目标是避免旧 memory 或自由发挥污染测评。

必须做:
- 读取当前 `SKILL.md` 版本和最近 `session.json`。
- 检查 AGENTS.md 是否包含 Skill 执行纪律;缺失时追加,无写权限则告警但不阻断。
- 优先调用 `sentry_preflight.py` 做可代码化预检。
- 独立输出: `✅ Step 0 完成 | 环境已对齐 | AGENTS.md 已检查`。

## Step 1 找 Skill + 初始化

查找优先级:
1. 用户提供路径 -> 直接使用。
2. 用户只说名字 -> 按 CLI/OpenClaw 默认 skill 目录查找。
3. 「测评这个 skill」-> 使用当前目录下的 `SKILL.md`。

初始化必须写入 `session.json`: `skill`、`mode`、`skill_type`、`skill_hash`、`runtime`、`started_at`、`pipeline`、`sync`。

`mcp_based` 必须做 MCP 预检。全部不可用时属于 auto-exempt;部分不可用时展示缺失项并询问是否继续。飞书配置缺失不阻断,后续 sync 步骤由 `sentry_sync.py` 记录 `skipped_no_config`。

输出: `✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`。

## Step 2 工作流推断

用户给出特殊命令时按特殊命令执行;用户只说「测评 xxx」时按以下规则推断:

```text
计算 SKILL.md hash -> 读取 inputs_dir/rules.cache.json
不存在 -> quick
hash 不匹配 -> smoke + MARK_STALE
hash 匹配 + cases 存在 -> regression
hash 匹配 + cases 不存在 -> quick
```

合法 pipeline 只来自 `scripts/sentry_pipeline.py`;不要在主会话维护数组副本。预计时间: smoke 约 10min, quick 约 20min, regression 约 5min, standard 约 40min, full 约 50min。

如果 OpenClaw 用户只说「测评」未指定 Skill,扫描默认 skill 目录,排除 sentry-* / SkillSentry / .bak,用飞书 V2 卡片让用户选择 Skill 和模式。

Step 2 后检查 resume:
- 若最近 `session.json.last_step` 不是空也不是 `publish`,提示用户是否从断点继续。
- 用户确认或直接说 `继续` 时,从 pipeline 下一步继续,不重跑 Step 0/1/2。
- 跳过执行不等于跳过展示;必须按 pipeline 顺序展示已完成步骤摘要。

## Step 3 调度循环

主会话永远只做三件事:派活、验收、通知用户。

每轮按这个循环:

```text
1. 读 session.json,取 last_step
2. 调 sentry_pipeline.py next,确定 next_step
3. 调 sentry_pipeline.py describe <step>,取得工具、产物、跳过策略
4. 读取 next_step 对应子工具 SKILL.md 和必要 references
5. spawn subagent,task 中注入输入路径、输出路径、completion 格式和 evidence 要求
6. 长耗时步骤写 active-pipeline.json 后 yield;恢复时从 checkpoint 继续
7. subagent 完成后验收 required artifacts
8. 调 sentry_state.py transition 写状态
9. 向用户展示结果和进度
```

长耗时步骤包括 executor、comparator、analyzer、grader-report。checkpoint 路径为 `~/.openclaw/data/skill-eval/active-pipeline.json`;publish 完成或用户取消时清理。

## 验收和通知

每步完成后必须:
- 检查 `sentry_pipeline.py describe <step>` 列出的 required artifacts。
- 产物缺失率 > 20% 时降级或阻断,不能静默继续。
- 更新 `session.json.last_step` 和 evidence。
- 发一条独立消息,包含具体数据和进度条。

缓存命中也必须展示摘要:
- static 缓存:静态规则结果 + TP/TN + 来源 session。
- cases 缓存:用例清单 + 断言统计。
- 禁止只写「缓存命中,跳过」。

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
