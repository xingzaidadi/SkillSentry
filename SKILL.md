---
name: skill-eval-测评
version: "7.8.0"
description: >
  SkillSentry — AI Skill 质量测评系统。
  触发场景：说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  ⚠️ 强制执行规则：当用户消息匹配上述触发词时，你必须先读取本 skill 的 SKILL.md 并按其流程执行，禁止跳过 skill 直接编排 subagent 或自行执行测评流程。即使你觉得自己知道怎么做，也必须先读 SKILL.md。
  ⚠️ 旧记忆警告：如果你的 memory 中有 SkillSentry 的旧版执行记录（如用纯文本列表选择 skill、跳过交互卡片），这些是过时的行为模式。当前版本要求用 feishu_ask_user_question 交互卡片选择 Skill 和模式。必须读 SKILL.md 确认当前版本的行为，不要照搬 memory 中的旧做法。
  不触发场景：讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
metadata:
  author: 刘四星
  created_at: "2026-03-27"
---

## ⛔ 版本锁定 & 行为优先级（本节不可删除）

**本文件是 SkillSentry v7.7.4，是唯一权威的行为定义。**

执行本 Skill 时，遵守以下优先级规则：

**规则 1：SKILL.md > memory**
当 memory 中的行为模式与本文件冲突时，以本文件为准。

**规则 2：每次触发都是独立执行**
每次用户说「测评」都是一次全新的执行，不因之前测评过其他 Skill 就跳过读本文件、不因上次用了某种做法就照搬。memory 中关于其他 Skill 的测评记录（如「上次我用文本列表列了 23 个 skill」）不代表本次也该这么做。

**规则 3：交互方式以本文件为准**
- 选择 Skill/模式 → 必须用 `feishu_ask_user_question` 交互卡片
- 禁止用纯文本 Markdown 表格罗列选项
- 即使 memory 中有「上次用文本列表」的记录，本次也必须用卡片

典型冲突场景：
| memory 中可能有的旧行为 | 本文件要求的新行为 | 正确做法 |
|------------------------|-------------------|----------|
| 上次测评 Skill A 时用文本列表 | `feishu_ask_user_question` 交互卡片 | 用卡片 |
| 上次直接执行没读 SKILL.md | 每次都先读本文件 | 读文件 |
| 上次跳过了 Step 0 | 每次都执行 Step 0 | 不跳 |
| 上次测评的结果影响本次判断 | 每次独立评估 | 不受干扰 |

**为什么**：本 Skill 经历过多次重构（v3→v5→v7.x），且每次测评的 Skill 不同。memory 中可能残留旧版行为模式或其他 Skill 的测评经验。本文件的指令代表当前版本的正确行为，优先级高于任何 memory 记录。

---

# skill-eval-测评 (SkillSentry) · AI Skill 质量守门人

极简调度器:找 Skill → 选模式 → 按顺序调子工具 → 每步等确认。

---

## 平台适配层

检测方式:消息来自飞书/Telegram → `runtime="openclaw"`;其他 → `runtime="cli"`。

| 能力 | CLI / OpenCode | OpenClaw(飞书)|
|------|---------------|----------------|
| 子任务调用 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=600)` |
| 步骤输出 | 打印到终端 | `message(msg_type="interactive", ...)` |
| 步骤校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit |
| 步骤等待 | 60s 无响应自动继续 | 等用户说「继续」(无超时)|
| 自动模式 | `--ci` 跳过步骤间等待 | `自动` 跳过步骤间等待 |

### ⛔ auto 模式不可跳过清单(auto-exempt)

auto 模式跳过的是「步骤间的继续确认」,以下场景即使 auto 模式也**必须阻断等待用户**:

| 场景 | 原因 | 所在步骤 |
|------|------|----------|
| MCP 预检全不可用 | 无法执行任何 real_data 用例,用户需决定配置 MCP 或降级 | Step 1 |
| real_data 测试数据采集 | AI 禁止编造单号/ID,必须用户提供或确认 | sentry-cases Step 0.3 |
| 用例设计审核 | 用户需确认用例覆盖度并决定是否补充 | sentry-cases Step 0.2 |
| 写操作/不可逆操作确认 | 安全要求 | 任意步骤 |

规则:`auto-exempt` 标记的步骤,auto 模式下仍必须展示内容并等待用户响应。

**OpenClaw 额外要求**:每步完成后将 `{msg_type, message_id, sent_at}` 写入 `session.json.milestones.step-N`。`validate_step.py` 会校验此字段。

---

## ⛔ 飞书卡片格式（OpenClaw 主会话必读）

**规则：所有面向用户的步骤输出，必须通过 `message` 工具发送 interactive 类型卡片。禁止用纯文本回复代替。**

详细模板和 Python 代码片段见：`./references/card-templates.md`

强制执行：
1. 调用 `message` 工具时必须传 `msg_type="interactive"`
2. 禁止用无 msg_type 的 message 调用
3. 禁止直接回复文本代替 message 工具调用

---

## 子工具

所有子工具位于本 skill 的 `tools/` 目录下,通过相对路径加载:`./tools/sentry-*/SKILL.md`

| 工具 | 路径 | 职责 |
|------|------|------|
| `sentry-check` | `./tools/sentry-check/SKILL.md` | 静态结构检查(L1-L5)+ 触发率模拟(TP/TN) |
| `sentry-cases` | `./tools/sentry-cases/SKILL.md` | 测试用例设计,输出 evals.json |
| `sentry-executor` | `./tools/sentry-executor/SKILL.md` | 用例并行执行,输出 transcript |
| `sentry-grader` | `./tools/sentry-grader/SKILL.md` | 断言评审,输出 grading.json |
| `sentry-report` | `./tools/sentry-report/SKILL.md` | 报告 + 发布决策 + HiL 确认 |

---

## 特殊命令

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry` / `验证测评` | 检查所有子工具是否存在,逐一列出 ✅/❌ |
| `lint xxx` / `检查结构` / `有没有HiL问题` | 只跑 sentry-check(lint 模式)|
| `测触发率` / `description 准不准` | 只跑 sentry-check(trigger 模式)|
| `设计用例 xxx` / `只出 cases` | 只跑 sentry-cases |
| `跑用例` / `用现有用例` | executor → grader → report |
| `出报告` / `通过了吗` / `看结果` | sentry-report(需已有 grading.json)|

### 素材自动存档

用户发文件 + 说「存到 xxx 测评素材」「给 xxx 测评用的」时:
1. 提取 Skill 名称
2. 保存到 `{skill-eval-测评根目录}/inputs/<skill名>/`(保留原始文件名)
3. 回执:「✅ 已存入 inputs/<skill名>/<文件名>」

---

## Step 0: 环境预检（每次测评必须执行，全自动）

Step 0 包含两个子步骤，全部自动执行，无需用户干预。

### Step 0.1: 环境对齐检查

每次触发测评时，自动检查环境状态。不删除任何 memory 文件。

**检查内容**：
1. 读取 SKILL.md 的 `version:` 字段
2. 读取 `session.json`（如有），检查 `skill` 和 `skill_version` 字段
3. 如果 session.json 中的 `skill` 与当前要测评的 Skill 不同 → 清空 session.json（旧测评的残留数据会干扰新测评）
4. 如果 `skill_version` 与当前 SKILL.md 版本不同 → 输出版本变更提示

**执行规则**：
- session.json 为空或不存在 → 输出 `✅ 首次运行，版本 v{version}`
- skill 一致 + 版本一致 → 跳过，输出 `✅ 环境一致 (v{version})`
- skill 不一致（上次测 A，这次测 B）→ 清空 session.json，输出 `🔄 检测到测评目标变更 ({old_skill} → {new_skill})，已重置 session`
- 版本不一致 → 输出 `⚠️ 版本变更: {old} → {new}`

**为什么不删 memory**：memory 中的 session 历史、执行结果、用例数据都是有价值的资产。行为冲突的问题通过「SKILL.md > memory」的优先级规则解决，不需要删除文件。session.json 的清空只影响当前测评的临时状态，不影响历史记录。

### Step 0.2: AGENTS.md 合规检查

确保当前 OpenClaw 实例的 AGENTS.md 包含 Skill 执行纪律规则。缺少此规则会导致 Agent 跳过 Skill 直接执行，测评结果不可信。

**检查内容**：读取 AGENTS.md（优先 `/app/xiaomi/prompts/AGENTS.md`，其次 `~/.openclaw/workspace/AGENTS.md`），搜索是否包含 `Skill 执行纪律` 关键词。

**缺失时自动注入**：

```markdown
## Skill 执行纪律

当用户消息匹配到任何已安装 Skill 的触发词时：
1. 你必须先读取该 Skill 的 SKILL.md
2. 按 SKILL.md 定义的流程执行
3. 禁止跳过 Skill 直接编排 subagent 或自行执行

判断依据：系统提示词中该 Skill 的 description 包含与用户消息匹配的关键词。
即使你觉得自己知道怎么做，也必须先读 SKILL.md。

违反此规则 = 严重错误。
```

**执行规则**：
- 检测到已存在 → 跳过，输出 `✅ AGENTS.md 已含 Skill 执行纪律`
- 检测到缺失 → 追加到 AGENTS.md 末尾，输出 `⚠️ 已自动注入 Skill 执行纪律到 AGENTS.md`
- 无写权限 → 告警但不阻断，输出 `⚠️ 无法写入 AGENTS.md，请手动添加 Skill 执行纪律`

**为什么 Step 0 必须在所有其他步骤之前**：如果 Agent 没有 Skill 执行纪律，后续测评中 Agent 可能跳过被测 Skill 的流程，导致测评结果失真（测的是 Agent 自由发挥，不是 Skill 的真实效果）。两个子步骤都通过后，输出 `✅ Step 0 完成 | 旧记忆已清理 | AGENTS.md 已检查`，继续 Step 1。

---

## Step 1:找 Skill + 初始化

**查找优先级**:
1. 用户提供路径 → 直接使用
2. 用户只说名字 →
   - CLI: `~/.claude/skills/<名字>/` → `~/.config/opencode/skills/<名字>/`
   - OpenClaw: `~/.openclaw/workspace/skills/<名字>/` → `~/.openclaw/skills/<名字>/`
3. 「测评这个 skill」→ 当前目录下的 SKILL.md

找不到 → `❌ 找不到 Skill:{name}。已搜索:{paths}。请确认拼写或提供完整路径。`

**工作路径**:
```
CLI:
  workspace_dir = ~/.claude/skills/skill-eval-测评/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
  inputs_dir    = ~/.claude/skills/skill-eval-测评/inputs/<Skill名>/
OpenClaw:
  workspace_dir = ~/.openclaw/skills/skill-eval-测评/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
  inputs_dir    = ~/.openclaw/skills/skill-eval-测评/inputs/<Skill名>/
```

目录不存在 → 自动创建。

**skill_type 检测**:含业务 MCP 工具名(camelCase)→ `mcp_based`;含 bash/python/exec → `code_execution`;其他 → `text_generation`。详见 `references/execution-phases.md`。

**MCP 预检(仅 mcp_based,⛔ auto-exempt)**:

自动探测链,无需用户手动配置:

```
1. 列出 SKILL.md 中引用的所有 MCP Server
2. 按顺序探测可用后端:
   a) openclaw.json mcpServers → mcp_backend = "native"
   b) mcporter config list     → mcp_backend = "mcporter"
   c) 均未配置                → mcp_backend = "unavailable"
3. 结果分级:
   - 全部可用 → 继续,记录 mcp_backend 到 session.json
   - 部分可用 → 告知用户哪些缺失,询问是否继续(部分用例将受限)
   - 全不可用 → ⛔ 阻断,展示缺失列表,提供两个选项:
     a) 用户配置 MCP 后继续
     b) 降级为纯静态分析(跳过 executor,只出 check + cases + report)
```

mcp_backend 写入 session.json,executor 根据此字段自动选择执行方式:
- `native`:子 agent 直接调用原生 MCP 工具
- `mcporter`:通过 `HOME=/root/.openclaw mcporter call <server>.<tool>(params)` 执行

此检查全自动完成。仅当全不可用时才阻断等待用户决策。

**飞书同步配置检查**:
```
查找 config.json:workspace_dir 父目录 → inputs_dir 父目录 → skill-eval-测评 根目录
  → 不存在:询问「是否启用飞书同步?启用可在飞书多维表格中管理用例和查看报告」
    - 用户说是 → 自动创建 Bitable(用例表 + 运行记录表 + 版本标签表)+ 写入 config.json
    - 用户说否 → 纯本地模式,所有 PUSH/PULL 标记为 skipped_no_config
  → 已存在:启用飞书同步

config.json 字段映射(OpenClaw 环境):
  app_token         = config.bitable.app_token
  cases_table_id    = config.bitable.tables.cases
  run_history_table_id = config.bitable.tables.runs
  versions_table_id = config.bitable.tables.versions
  注:OpenClaw 环境使用 feishu_app_bitable_* 工具(内置鉴权),无需 app_id/app_secret
  CLI 环境使用 REST API 时,需在 config.json 中额外配置 feishu.app_id + feishu.app_secret
```

写 `session.json`(skill / mode / skill_type / skill_hash / runtime / started_at)。

**MCP 预检(仅 mcp_based,所有模式必须执行)**:

具体工具调用序列：
```
1. exec: grep -E "\"[a-z_]+_claw_[a-z]+\"" ~/.openclaw/skills/{skill}/SKILL.md
   → 提取 SKILL.md 中引用的所有 MCP Server 名

2. exec: HOME=/root/.openclaw mcporter config list 2>/dev/null | grep -E "^[a-z]" | head -10
   → 获取已配置的 MCP Server 列表

3. 比对：SKILL.md 中引用的 vs mcporter 已配置的 → 标注可用/不可用

4. message(action=send, message="
   ✅ Step 1 初始化
   • 被测 Skill：{name}
   • 类型：{skill_type}
   • MCP 预检：
     ✅ {server1} — 可用
     ✅ {server2} — 可用
     ❌ {server3} — 不可用
   • MCP 后端：{mcporter/native/unavailable}
   • 工作目录：{workspace}
   ")
```

结果分级：
- 全部可用 → 继续
- 部分可用 → 告知用户哪些缺失，询问是否继续
- 全不可用 → ⛔ 阻断，提供降级选项

输出:`✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`

---

## Step 2:智能工作流推断

### 单工具快速调用(见「特殊命令」表,跳过推断)

### 工作流推断(用户只说「测评 xxx」)

```
计算 SKILL.md MD5 → 读取 inputs_dir/rules.cache.json
  不存在               → quick(首次测评)
  hash 不匹配          → smoke(Skill 有变更)+ MARK_STALE
  hash 匹配 + cases 存在    → regression
  hash 匹配 + cases 不存在  → quick
```

**工作流模式**:

| 模式 | 工具链 | 预计时间 |
|------|--------|---------|
| smoke | cases(4-5个) → executor(1次) → grader-report | ~12-15min |
| quick | check → cases → executor(2次) → grader-report | ~25-30min |
| regression | executor(golden only) → grader-report | ~5-10min |
| standard | check → cases → executor(3次) → grader-report → comparator | ~40-50min |
| full | check → cases → executor(3次) → grader-report → comparator → analyzer | ~35-45min |

输出确认(自动模式直接开始):
```
message(action=send, message="
✅ Step 2 工作流推断
• 被测 Skill：{name}
• 类型：{type}
• 推荐模式：{mode}（{reason}）
• Pipeline：{tool_chain}
• 预计时间：{time}
• Token 预估：{range}
")
```

**OpenClaw 无上下文时(用户只说「测评」未指定 Skill)**:必须用 `feishu_ask_user_question` 发交互卡片,禁止纯文本罗列。

构造方式:
1. 扫描 `~/.openclaw/skills/` 和 `~/.openclaw/workspace/skills/` 下所有含 SKILL.md 的目录
2. 排除 sentry-* / skill-eval-测评 自身 / SkillSentry / .bak 目录
3. 生成三个问题的卡片:

```
feishu_ask_user_question(questions=[
  {
    "question": "选择要测评的 Skill",
    "header": "被测 Skill",
    "options": [
      // 动态生成,每个 option:
      {"label": "<skill-name>", "description": "<从 SKILL.md frontmatter description 截取前 30 字>"}
    ],
    "multiSelect": false
  },
  {
    "question": "选择测评模式(不选默认自动推断)",
    "header": "测评模式",
    "options": [
      {"label": "smoke", "description": "冒烟测试,4-5 个用例,~5 分钟"},
      {"label": "quick", "description": "快速测评,2 轮执行,~10-15 分钟"},
      {"label": "standard", "description": "标准测评,3 轮+对比,~30-45 分钟"},
      {"label": "full", "description": "完整测评,全流程+根因分析,45 分钟+"},
      {"label": "自动推断", "description": "根据缓存状态自动选择最合适的模式"}
    ],
    "multiSelect": false
  },
  {
    "question": "每个步骤完成后是否需要你确认才继续?选「自动」则全程无需干预",
    "header": "执行方式",
    "options": [
      {"label": "自动", "description": "全程自动执行,每步展示结果但不等确认"},
      {"label": "逐步确认", "description": "每步完成后等你说「继续」再跑下一步"}
    ],
    "multiSelect": false
  }
])
```

4. 等待用户选择后继续 Step 2 剩余流程
5. 如果用户指定了 Skill 名但未指定模式,只发模式选择卡片(单问题)
6. 如果用户同时指定了 Skill 和模式,跳过卡片直接进入推断
7. **卡片提交后必须按顺序输出 Step 1 和 Step 2 两条独立消息**：
   - Step 1（初始化）：含被测 Skill 名称 + skill_type + MCP 预检结果 + 工作目录
   - Step 2（工作流推断）：含 pipeline + 预计时间 + 模式理由
   - 禁止合并为一条消息，禁止跳过任一步

---

## Step 3:无状态调度循环

### 核心原则:主会话只调度,不执行

主会话永远只做三件事:**派活、验收、通知用户**。所有复杂步骤(含 sentry-report)全部委派给 subagent 执行。

原因:主会话经历多轮 yield/resume 后上下文疲劳,会导致跳步、简化、凭记忆执行。委派给 subagent 可结构性避免此问题。

### 每轮调度流程(无状态,不靠上下文记忆)

```
1. 读 session.json → 取 last_step
2. 查 pipeline 定义 → 确定 next_step
3. 读取 next_step 对应子工具的 SKILL.md(必须 read,不能凭记忆)
4. spawn subagent(task = SKILL.md 内容 + session 数据 + 输入文件路径)
5. yield 等回调
6. resume 后验收产物(检查文件是否存在)
7. 向用户展示结果 + 更新 session.json last_step
8. 回到 1(不靠记忆,靠文件状态)
```

### pipeline 定义(每步的子工具 + 产物清单)

| 步骤 | 子工具 | SKILL.md 路径 | 必须产物 | 调度方式 |
|------|---------|--------------|---------|----------|
| check | sentry-check | ./tools/sentry-check/SKILL.md | session.json.lint + trigger_eval.json | subagent |
| cases | sentry-cases | ./tools/sentry-cases/SKILL.md | evals.json + cases.cache.json | subagent(↩️ auto-exempt 步骤需主会话中转) |
| executor | sentry-executor | ./tools/sentry-executor/SKILL.md | eval-*/run-*/transcript.md | 批次 subagent |
| grader-report | sentry-grader | ./tools/sentry-grader/SKILL.md | eval-*/grading.json + report.html + history.json | **单 subagent**(评审全部 runs + 合并 grading + 生成报告) |

### 产物验收(每步 subagent 完成后,主会话执行)

```
subagent 完成 → 主会话按顺序执行以下 4 个工具调用（不可跳过、不可简化、不可用纯文本替代）：

动作 1：读 progress.json
exec: cat {workspace}/progress-run-{R}.json 2>/dev/null || echo "NO_PROGRESS"

动作 2：检查产物文件
exec:
  SESSION_DIR={workspace}
  for i in 1 2 3 ..N; do
    t="$SESSION_DIR/eval-$i/with_skill/outputs/transcript.md"
    r="$SESSION_DIR/eval-$i/with_skill/outputs/response.md"
    [ -s "$t" ] && [ -s "$r" ] && echo "✅ eval-$i: transcript=$(wc -c < $t)B response=$(wc -c < $r)B" || echo "❌ eval-$i: 文件缺失"
  done

动作 3：向用户发送结果卡片（必须用 message(action=send)，禁止纯文本回复）
message(action=send, message="
🦞 SkillSentry · Step {N} {step_name} 完成

✅ {passed}/{total} 用例成功

| Eval | 用例 | MCP Server | 结果 |
|------|------|-----------|------|
| eval-1 | {摘要} | {server} | {结果} |
| eval-2 | ... | ... | ... |
| eval-3 | ... | ... | ... |
| eval-4 | ... | ... | ... |

关键发现：
• {发现 1}
• {发现 2}

🔧 Step {N+1} {next_step_name} 执行中...
")

动作 4：写 session.json
exec: python3 -c "
import json
path = '{workspace}/session.json'
d = json.load(open(path))
d['last_step'] = '{step_name}'
d['milestones']['step-{step_name}'] = {'msg_type': 'text', 'message_id': '{msg_id}', 'sent_at': '{ISO时间}'}
d['{step_name}'] = {total_runs: N, success: X, failed: Y, time_minutes: T}
json.dump(d, open(path, 'w'), indent=2, ensure_ascii=False)
"

⚠️ 以上 4 个动作适用于所有模式（smoke/quick/standard/full/regression）。
⚠️ 动作 3 必须用 message(action=send) 发送，禁止用纯文本回复代替。
⚠️ 如果我（agent）跳过任何一个动作，用户有权要求重跑。
```

### auto-exempt 步骤的特殊处理

cases 步骤含 auto-exempt 环节(数据采集、用例审核),需主会话与用户交互:
1. subagent 完成需求分析 + 用例设计 → 写入文件
2. 主会话读取文件 → 展示给用户 → 等待确认/补充
3. 用户确认后继续下一步

### 其他规则

- **缓存复用**:SKILL.md hash 一致 + 产物存在 → 复用,标注「⚡ 缓存命中(上次 {date})」
- **快速失败**(quick 模式):grader 评审前几个 eval 后通过率 < 20% → 询问是否继续
- **透明执行**:每步完成后必须展示结果,自动模式也不例外
- **⛔ 禁止**:主会话直接执行任何子工具的业务逻辑;凭记忆生成报告/用例/评分;手写用例替代 sentry-cases
- **⛔ 所有模式必须 spawn sentry-cases subagent**：禁止主会话自己编写 evals.json。但流程深度按模式分级（见下方「模式分级控制」）
- **⛔ 报告产出按模式分级**：
  - smoke：grading-summary.json（本地）
  - quick：grading-summary.json + 飞书卡片推送
  - standard/full：三件套（HTML + summary + history）+ HTML 上传飞书

### 模式分级控制（sentry-cases 流程深度）

| 能力 | smoke | quick | standard | full |
|------|:---:|:---:|:---:|:---:|
| 三步扫描 | ❌ 跳过 | ⚡ 用缓存 | ✅ 完整 | ✅ 完整 |
| 测试数据采集 | ⚡ mcp_based查+确认/其他no_data | ⚡ 尝试查 | ✅ 必须查 | ✅ 必须查+用户确认 |
| 用例确认 | ❌ 跳过 | ❌ 跳过 | ✅ 需确认 | ✅ 需确认 |
| security 用例 | ❌ 不含 | ✅ ≥1 | ✅ ≥2 | ✅ ≥3 |
| 飞书 PULL | ❌ 跳过 | ⚡ 有就拉 | ✅ 必须 | ✅ 必须 |
| 飞书 PUSH | ❌ 跳过 | ❌ 跳过 | ✅ 必须 | ✅ 必须 |
| history.json | ❌ 不更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 |

sentry-cases subagent 的 task 中必须注入 `mode` 参数，子工具根据 mode 自动跳过/精简对应步骤。

### 进度可见性规范（所有模式通用，smoke/quick/standard/full 均适用）

**原则**：用户不应在任何时刻感到「黑盒」。每个关键动作都必须有可见反馈。

**规则已写入上方「产物验收」的 4 个工具调用中**，此处不再重复。关键点：

- 动作 3（结果卡片）**必须用 `message(action=send)`**，禁止纯文本回复
- 卡片内容必须包含 per-eval 结果表格，不可用汇总替代
- **grader 结果卡片必须包含 per-assertion 详情**（断言名 + 类型 + pass/fail + evidence 摘要），smoke/quick 全量展示，standard/full 只展示 failed
- 每个 step 完成后都要发一张卡片，不是最后一起发

---

## 飞书同步

> config.json 不存在时，所有操作静默跳过并记录 `skipped_no_config`，不中断主流程。
> 详细执行流程见：`./references/feishu-sync.md`

关键规则（不可简化）：
- ⛔ PUSH-CASES / PUSH-RESULTS / PUSH-RUN 三步不可跳过（standard/full 模式）
- ⛔ Step 7 前置校验：sync.push_cases 和 sync.push_results 必须非 null 才能出报告

## Pipeline 准出标准

| 步骤 | 准出条件 | 未通过 |
|------|---------|--------|
| sentry-check | 无 P0(lint)/ TP ≥ 70%(trigger)| P0 → 暂停;TP 低 → 警告继续 |
| sentry-cases | 用例数 ≥ 3 | 警告「覆盖不足」|
| sentry-executor | ≥ 1 个有 transcript | 全失败 → 终止,报告环境问题 |
| sentry-grader | ≥ 1 个有 grading + report.html 存在 | 全超时 → 标注「评审缺失」;报告失败 → 纯文本摘要替代 |

---

## session.json

完整 schema 见：`./references/session-json-schema.md`

写入时机：Step 1 写基础字段 → 各步完成后写对应字段 → grader 完成写 verdict/recommendations。

---

*v7.8.0 · 卡片格式强制+references外移+SKILL.md瘦身 · 2026-04-30*
*v7.7.4 · 模式分级+断言分级+multi_turn+空字段+多编号分隔 · 2026-04-29*
