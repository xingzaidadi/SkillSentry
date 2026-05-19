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
