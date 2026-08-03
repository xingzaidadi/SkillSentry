# SkillSentry Runtime Router Guide

本文件承接 `SKILL.md` 中不适合长期堆在主入口里的执行细则。主 `SKILL.md` 只保留触发、路由、禁区和关键契约；具体运行平台、特殊命令、Step 0-3 调度循环和验收规则以本文为准。

## 运行平台

| 能力 | CLI / OpenCode | OpenClaw(飞书) | CI |
|------|----------------|----------------|----|
| 子任务 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=900)` | `claude -p` + SDK |
| 输出 | 终端文本 | `message(action=send, msg_type="text")` | stdout/stderr + 文件 |
| 校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit | 文件存在性 |
| 等待 | 60s 无响应自动继续 | 等用户说「继续」 | 全自动 |

OpenClaw 输出必须使用 `message` 工具。选择 Skill/模式必须使用飞书 V2 卡片的独立 `select_static`，禁止 V1 `action` 容器、`form` 和 `button(form_action_type=submit)`；卡片失败时才用 markdown 列表兜底。

## Auto-Exempt

auto 模式只跳过步骤间继续确认。以下场景仍必须等待用户：

| 场景 | 原因 |
|------|------|
| MCP 预检全不可用 | 无法执行 real_data，需用户配置 MCP 或降级 |
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
| `出报告` / `重新生成报告` / `通过了吗` / `看结果` | 调 `sentry-report`，前提是已有 grading |
| `继续` / `resume` / `从断点继续` | 读取 `session.json.last_step`，从 pipeline 下一步继续 |

用户发文件并说「存到 xxx 测评素材」时，保存到 `inputs/<skill名>/`，保留原始文件名，并回执路径。

## Step 0 环境预检

每次测评先执行，目标是避免旧 memory 或自由发挥污染测评。

必须做：

- 读取当前 `SKILL.md` 版本和最近 `session.json`。
- 检查 AGENTS.md 是否包含 Skill 执行纪律；缺失时追加，无写权限则告警但不阻断。
- 优先调用 `sentry_preflight.py` 做可代码化预检。
- 独立输出：`✅ Step 0 完成 | 环境已对齐 | AGENTS.md 已检查`。

## Step 1 找 Skill + 初始化

查找优先级：

1. 用户提供路径 -> 直接使用。
2. 用户只说名字 -> 按 CLI/OpenClaw 默认 skill 目录查找。
3. 「测评这个 skill」-> 使用当前目录下的 `SKILL.md`。

初始化必须写入 `session.json`：`skill`、`mode`、`skill_type`、`skill_hash`、`runtime`、`started_at`、`pipeline`、`sync`。

`mcp_based` 必须做 MCP 预检。全部不可用时属于 auto-exempt；部分不可用时展示缺失项并询问是否继续。飞书配置缺失不阻断，后续 sync 步骤由 `sentry_sync.py` 记录 `skipped_no_config`。

输出：`✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`。

## Step 2 工作流推断

用户给出特殊命令时按特殊命令执行；用户只说「测评 xxx」时按以下规则推断：

```text
计算 SKILL.md hash -> 读取 inputs_dir/rules.cache.json
不存在 -> quick
hash 不匹配 -> smoke + MARK_STALE
hash 匹配 + cases 存在 -> regression
hash 匹配 + cases 不存在 -> quick
```

合法 pipeline 只来自 `scripts/sentry_pipeline.py`；不要在主会话维护数组副本。预计时间：smoke 约 10min，quick 约 20min，regression 约 5min，standard 约 40min，full 约 50min。

如果 OpenClaw 用户只说「测评」未指定 Skill，扫描默认 skill 目录，排除 sentry-* / SkillSentry / .bak，用飞书 V2 卡片让用户选择 Skill 和模式。

Step 2 后检查 resume：

- 若最近 `session.json.last_step` 不是空也不是 `publish`，提示用户是否从断点继续。
- 用户确认或直接说 `继续` 时，从 pipeline 下一步继续，不重跑 Step 0/1/2。
- 跳过执行不等于跳过展示；必须按 pipeline 顺序展示已完成步骤摘要。

## Step 3 调度循环

主会话永远只做三件事：派活、验收、通知用户。

每轮按这个循环：

```text
1. 读 session.json，取 last_step
2. 调 sentry_pipeline.py next，确定 next_step
3. 调 sentry_pipeline.py describe <step>，取得工具、产物、跳过策略
4. 读取 next_step 对应子工具 SKILL.md 和必要 references
5. spawn subagent，task 中注入输入路径、输出路径、completion 格式和 evidence 要求
6. 长耗时步骤写 active-pipeline.json 后 yield；恢复时从 checkpoint 继续
7. subagent 完成后验收 required artifacts
8. 调 sentry_state.py transition 写状态
9. 向用户展示结果和进度
```

长耗时步骤包括 executor、comparator、analyzer、grader-report。checkpoint 路径为 `~/.openclaw/data/skill-eval/active-pipeline.json`；publish 完成或用户取消时清理。

## 验收和通知

每步完成后必须：

- 检查 `sentry_pipeline.py describe <step>` 列出的 required artifacts。
- 产物缺失率 > 20% 时降级或阻断，不能静默继续。
- 更新 `session.json.last_step` 和 evidence。
- 发一条独立消息，包含具体数据和进度条。

缓存命中也必须展示摘要：

- static 缓存：静态规则结果 + TP/TN + 来源 session。
- cases 缓存：用例清单 + 断言统计。
- 禁止只写「缓存命中，跳过」。
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\runtime-router-guide.md` |
| 学习重点 | runtime-router-guide |
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
