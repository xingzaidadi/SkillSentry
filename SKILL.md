---
name: skill-eval-测评
version: "8.5.1"
description: >
  SkillSentry - AI Skill 质量测评系统。Each run is a fresh execution. Current SKILL.md and session state override memory.
  触发场景:说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  ⚠️ 强制执行规则:当用户消息匹配上述触发词时,你必须先读取本 skill 的 SKILL.md 并按其流程执行,禁止跳过 skill 直接编排 subagent 或自行执行测评流程。即使你觉得自己知道怎么做,也必须先读 SKILL.md。
  ⚠️ 旧记忆警告:如果你的 memory 中有 SkillSentry 的旧版执行记录(如用纯文本列表选择 skill、跳过交互卡片),这些是过时的行为模式。当前版本要求用飞书 V2 卡片(form + select_static)选择 Skill 和模式。必须读 SKILL.md 确认当前版本的行为,不要照搬 memory 中的旧做法。
  不触发场景:讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
metadata:
  author: 刘四星
  created_at: "2026-03-27"
---

## ⛔ 版本锁定 & 行为优先级(本节不可删除)

**本文件是 SkillSentry v8.5.1,是唯一权威的行为定义。**

**行为优先级(一行版)**:当前用户请求 > 当前 SKILL.md > 本次读取的 references/文件 > 本次工具输出 > 对话历史 > memory

执行本 Skill 时,遵守以下优先级规则:

**规则 1:SKILL.md > memory**
当 memory 中的行为模式与本文件冲突时,以本文件为准。

**规则 2:每次触发都是独立执行**
每次用户说「测评」都是一次全新的执行,不因之前测评过其他 Skill 就跳过读本文件、不因上次用了某种做法就照搬。memory 中关于其他 Skill 的测评记录(如「上次我用文本列表列了 23 个 skill」)不代表本次也该这么做。

**规则 3:交互方式以本文件为准**
- 选择 Skill/模式 → 必须用飞书 V2 卡片(`form` + `select_static` + `button`),通过 `message(action=send, kind=interactive)` 发送
- 禁止用纯文本 Markdown 表格罗列选项
- 即使 memory 中有「上次用文本列表」的记录,本次也必须用卡片
- ⚠️ 飞书卡片必须用 V2 schema 原生组件,禁止使用已废弃的 V1 `action` 容器标签

**为什么**:本 Skill 经历过多次重构(v3→v5→v7.x→v8.x),memory 中可能残留旧版行为模式。本文件 > memory。

---

# skill-eval-测评 (SkillSentry) · AI Skill 质量守门人

极简调度器:找 Skill → 选模式 → 按顺序调子工具 → 每步等确认。

---

## 平台适配层

检测方式:消息来自飞书/Telegram → `runtime="openclaw"`;其他 → `runtime="cli"`。

| 能力 | CLI / OpenCode | OpenClaw(飞书)| CI(sentry_ci.py) |
|------|---------------|----------------|-------------------|
| 子任务调用 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=900)` | `subprocess.run(["claude", "-p", ...])` + Anthropic SDK |
| 步骤输出 | 打印到终端 | `message(msg_type="text", ...)` | stdout/stderr + 文件产物 |
| 步骤校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit | 文件存在性检查 |
| 步骤等待 | 60s 无响应自动继续 | 等用户说「继续」(无超时)| 无等待,全自动 |
| 自动模式 | `--ci` 跳过步骤间等待 | `自动` 跳过步骤间等待 | 强制 auto,跳过所有确认 |

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

## 步骤输出格式

**规则:所有面向用户的步骤输出,必须通过 `message` 工具发送。禁止直接回复文本代替 message 工具调用。**

格式:使用 `msg_type="text"`,内容用 markdown 格式化(表格、粗体、emoji)。

示例:
```
message(action=send, msg_type="text", message="✅ Step 1 初始化 (Initialization)\n• 被测 Skill (Target):xxx\n• 类型 (Type):xxx")
```

---

## 子工具

所有子工具位于本 skill 的 `tools/` 目录下,通过相对路径加载:`./tools/sentry-*/SKILL.md`

| 工具 | 路径 | 职责 |
|------|------|------|
| `sentry-static` | `./tools/sentry-static/SKILL.md` | 静态检查(L1-L5)+ 触发率(TP/TN),三合一(原 check/lint/trigger),支持 --lint-only / --trigger-only |
| `sentry-cases` | `./tools/sentry-cases/SKILL.md` | 测试用例设计,输出 evals.json |
| `sentry-executor` | `./tools/sentry-executor/SKILL.md` | 用例并行执行,输出 transcript |
| `sentry-grader` | `./tools/sentry-grader/SKILL.md` | 断言评审,输出 grading.json |
| `sentry-report` | `./tools/sentry-report/SKILL.md` | 报告 + 发布决策 + HiL 确认 |
| `sentry-comparator` | `./tools/sentry-comparator/SKILL.md` | 盲测对比(with vs without),仅 standard/full |
| `sentry-analyzer` | `./tools/sentry-analyzer/SKILL.md` | 解盲分析 + 改进建议,仅 full |
| `sentry-sync` | `./tools/sentry-sync/SKILL.md` | 飞书 Bitable 同步(PULL/PUSH) |
| `sentry-openclaw` | `./tools/sentry-openclaw/SKILL.md` | OpenClaw 环境适配层 |

---

## 特殊命令

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry` / `验证测评` | 检查所有子工具是否存在,逐一列出 ✅/❌ |
| `lint xxx` / `检查结构` / `有没有HiL问题` | 只跑 sentry-static --lint-only |
| `测触发率` / `description 准不准` | 只跑 sentry-static --trigger-only |
| `设计用例 xxx` / `只出 cases` | 只跑 sentry-cases |
| `跑用例` / `用现有用例` | executor → grader → report |
| `出报告` / `通过了吗` / `看结果` | sentry-report(需已有 grading.json)|
| `继续` / `resume` / `从断点继续` | 读取 session.json.last_step + pipeline 数组,从 pipeline[indexOf(last_step)+1] 继续执行,跳过 Step 0/1/2 |

### 素材自动存档

用户发文件 + 说「存到 xxx 测评素材」「给 xxx 测评用的」时:
1. 提取 Skill 名称
2. 保存到 `{skill-eval-测评根目录}/inputs/<skill名>/`(保留原始文件名)
3. 回执:「✅ 已存入 inputs/<skill名>/<文件名>」

---

## Step 0: 环境预检(每次测评必须执行,全自动)

Step 0 包含两个子步骤,全部自动执行,无需用户干预。

### Step 0.1: 环境对齐检查

每次触发测评时,自动检查环境状态。不删除任何 memory 文件。

**检查内容**:
1. 读取 SKILL.md 的 `version:` 字段
2. 读取 `session.json`(如有),检查 `skill` 和 `skill_version` 字段
3. 如果 session.json 中的 `skill` 与当前要测评的 Skill 不同 → 清空 session.json(旧测评的残留数据会干扰新测评)
4. 如果 `skill_version` 与当前 SKILL.md 版本不同 → 输出版本变更提示

**执行规则**:
- session.json 为空或不存在 → 输出 `✅ 首次运行,版本 v{version}`
- skill 一致 + 版本一致 → 跳过,输出 `✅ 环境一致 (v{version})`
- skill 不一致(上次测 A,这次测 B)→ 清空 session.json,输出 `🔄 检测到测评目标变更 ({old_skill} → {new_skill}),已重置 session`
- 版本不一致 → 输出 `⚠️ 版本变更: {old} → {new}`

**为什么不删 memory**:memory 中的 session 历史、执行结果、用例数据都是有价值的资产。行为冲突的问题通过「SKILL.md > memory」的优先级规则解决,不需要删除文件。session.json 的清空只影响当前测评的临时状态,不影响历史记录。

### Step 0.2: AGENTS.md 合规检查

确保当前 OpenClaw 实例的 AGENTS.md 包含 Skill 执行纪律规则。缺少此规则会导致 Agent 跳过 Skill 直接执行,测评结果不可信。

**检查内容**:读取 AGENTS.md(优先 `/app/xiaomi/prompts/AGENTS.md`,其次 `~/.openclaw/workspace/AGENTS.md`),搜索是否包含 `Skill 执行纪律` 关键词。

**缺失时自动注入**:

```markdown
## Skill 执行纪律

当用户消息匹配到任何已安装 Skill 的触发词时:
1. 你必须先读取该 Skill 的 SKILL.md
2. 按 SKILL.md 定义的流程执行
3. 禁止跳过 Skill 直接编排 subagent 或自行执行

判断依据:系统提示词中该 Skill 的 description 包含与用户消息匹配的关键词。
即使你觉得自己知道怎么做,也必须先读 SKILL.md。

违反此规则 = 严重错误。
```

**执行规则**:
- 检测到已存在 → 跳过,输出 `✅ AGENTS.md 已含 Skill 执行纪律`
- 检测到缺失 → 追加到 AGENTS.md 末尾,输出 `⚠️ 已自动注入 Skill 执行纪律到 AGENTS.md`
- 无写权限 → 告警但不阻断,输出 `⚠️ 无法写入 AGENTS.md,请手动添加 Skill 执行纪律`

**为什么 Step 0 必须在所有其他步骤之前**:如果 Agent 没有 Skill 执行纪律,后续测评中 Agent 可能跳过被测 Skill 的流程,导致测评结果失真(测的是 Agent 自由发挥,不是 Skill 的真实效果)。两个子步骤都通过后,输出 `✅ Step 0 完成 | 环境已对齐 | AGENTS.md 已检查`,继续 Step 1。

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
  workspace_dir = ~/.claude/data/skill-eval/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
  inputs_dir    = ~/.claude/skills/skill-eval-测评/inputs/<Skill名>/
OpenClaw:
  workspace_dir = ~/.openclaw/data/skill-eval/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
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
  注:OpenClaw 环境使用 feishu_bitable_app_table_record 等 工具(内置鉴权),无需 app_id/app_secret
  CLI 环境使用 REST API 时,需在 config.json 中额外配置 feishu.app_id + feishu.app_secret
```

写 `session.json`(skill / mode / skill_type / skill_hash / runtime / started_at)。

**MCP 预检(仅 mcp_based,所有模式必须执行)**:

具体工具调用序列:
```
1. exec: grep -E "\"[a-z_]+_claw_[a-z]+\"" ~/.openclaw/skills/{skill}/SKILL.md
   → 提取 SKILL.md 中引用的所有 MCP Server 名

2. exec: HOME=/root/.openclaw mcporter config list 2>/dev/null | grep -E "^[a-z]" | head -10
   → 获取已配置的 MCP Server 列表

3. 比对:SKILL.md 中引用的 vs mcporter 已配置的 → 标注可用/不可用

4. message(action=send, message="
   ✅ Step 1 初始化
   • 被测 Skill:{name}
   • 类型:{skill_type}
   • MCP 预检:
     ✅ {server1} - 可用
     ✅ {server2} - 可用
     ❌ {server3} - 不可用
   • MCP 后端:{mcporter/native/unavailable}
   • 工作目录:{workspace}
   ")
```

结果分级:
- 全部可用 → 继续
- 部分可用 → 告知用户哪些缺失,询问是否继续
- 全不可用 → ⛔ 阻断,提供降级选项

输出:`✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`

---

## Step 2:智能工作流推断

### 单工具快速调用(见「特殊命令」表,跳过推断)

### 工作流推断(用户只说「测评 xxx」)

```
计算 SKILL.md MD5 → 读取 inputs_dir/rules.cache.json

**⛔ 数据隔离规则**:Step 2 只读 `rules.cache.json`(判断 hash)。禁止读 inputs/ 下的 `history.json`、`baseline.snapshot.json`、`trigger_eval.json` 等结果文件--这些只在 report 阶段由 sentry-report subagent 使用。主调度器提前看到历史成绩会产生锚定效应,污染后续评审判断。

  不存在               → quick(首次测评)
  hash 不匹配          → smoke(Skill 有变更)+ MARK_STALE
  hash 匹配 + cases 存在    → regression
  hash 匹配 + cases 不存在  → quick
```

**工作流模式**:

| 模式 | 工具链 | 预计时间 |
|------|--------|---------|
| smoke | cases → sync-pull → sync-push-cases → executor-with(×1) → grader → sync-push-results → publish | ~10min |
| quick | static → cases → sync-pull → sync-push-cases → executor-with(×2) → grader → sync-push-results → report → publish | ~20min |
| regression | sync-pull → executor-with(golden) → grader → sync-push-results → publish | ~5min |
| standard | static → cases → sync-pull → sync-push-cases → executor-with(×3) → executor-without → grader → sync-push-results → report → comparator → gate → publish | ~40min |
| full | static → cases → sync-pull → sync-push-cases → executor-with(×3) → executor-without → grader → sync-push-results → report → comparator → analyzer → gate → publish | ~50min |

输出确认(自动模式直接开始):
```
message(action=send, message="
✅ Step 2 工作流推断 (Workflow Inference)

> **{mode} 模式 · {pipeline简写} · 预计 ~{time}**

• 推断依据:{reason}
• 被测 Skill:{name}({type})
• Pipeline:{tool_chain}
")
```

**OpenClaw 无上下文时(用户只说「测评」未指定 Skill)**:必须用飞书 V2 卡片发交互表单,禁止纯文本罗列。

构造方式:
1. 扫描 `~/.openclaw/skills/` 和 `~/.openclaw/workspace/skills/` 下所有含 SKILL.md 的目录
2. 排除 sentry-* / skill-eval-测评 自身 / SkillSentry / .bak 目录
3. 用 `message(action=send, kind=interactive)` 发送飞书 V2 卡片（form + select_static + button）:

```json
{
  "schema": "2.0",
  "config": {"update_multi": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🧠 SkillSentry · 测评配置"},
    "template": "blue"
  },
  "body": {
    "elements": [
      {"tag": "markdown", "content": "请选择要测评的 Skill、模式和执行方式："},
      {
        "tag": "form",
        "name": "sentry_eval_form",
        "elements": [
          {
            "tag": "select_static",
            "name": "skill_name",
            "placeholder": {"tag": "plain_text", "content": "选择被测 Skill"},
            "options": [
              {"text": {"tag": "plain_text", "content": "{skill_1}"}, "value": "{skill_1}"},
              {"text": {"tag": "plain_text", "content": "{skill_2}"}, "value": "{skill_2}"},
              "// ... 动态生成，每个扫描到的 Skill 一个 option"
            ]
          },
          {
            "tag": "select_static",
            "name": "eval_mode",
            "placeholder": {"tag": "plain_text", "content": "选择测评模式"},
            "options": [
              {"text": {"tag": "plain_text", "content": "🔥 smoke (~5min)"}, "value": "smoke"},
              {"text": {"tag": "plain_text", "content": "⚡ quick (~15min)"}, "value": "quick"},
              {"text": {"tag": "plain_text", "content": "📊 standard (~40min)"}, "value": "standard"},
              {"text": {"tag": "plain_text", "content": "🔬 full (~50min)"}, "value": "full"},
              {"text": {"tag": "plain_text", "content": "🔄 regression (~5min)"}, "value": "regression"},
              {"text": {"tag": "plain_text", "content": "🤖 自动推断"}, "value": "auto"}
            ]
          },
          {
            "tag": "select_static",
            "name": "exec_mode",
            "placeholder": {"tag": "plain_text", "content": "执行方式"},
            "options": [
              {"text": {"tag": "plain_text", "content": "🚀 自动（全程无需干预）"}, "value": "auto"},
              {"text": {"tag": "plain_text", "content": "👀 逐步确认"}, "value": "manual"}
            ]
          },
          {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "开始测评"},
            "type": "primary",
            "form_action_type": "submit"
          }
        ]
      },
      {"tag": "markdown", "content": "**可用 Skill 完整列表**：\n`{skill_1}` · `{skill_2}` · ..."}
    ]
  }
}
```

ℹ️ **重要：飞书 V2 卡片不支持已废弃的 `action` 容器标签**。必须用 `form` 包裹 `select_static` 和 `button`，或者将它们直接作为独立 element 放在 `body.elements` 中。

备选方案（当卡片发送失败时）：用纯 markdown 卡片展示 Skill 列表 + 纯文本引导用户回复选择。

4. 等待用户选择或回复后继续 Step 2 剩余流程

### Checkpoint Resume 检测(Step 2 工作流推断完成后执行)

在 Step 2 确定模式和 pipeline 后,检测是否存在未完成的上次测评:

```
读取最近一次 session.json
如果 last_step != null 且 last_step != "publish" 且 pipeline 存在:
  → 提示用户:
    "检测到上次未完成的测评({skill} {mode},停在 {last_step}),是否从断点继续?"
  用户确认 → 从 pipeline[indexOf(last_step)+1] 开始,跳过 Step 0/1/2 的执行
  用户拒绝 → 正常从头开始新测评
```

当用户输入 `继续` / `resume` / `从断点继续` 时,直接触发 resume 逻辑,无需重新跑 Step 0/1/2。

**⛔ Resume 展示铁律(跳过执行 ≠ 跳过展示)**:

Resume 时必须按顺序逐步输出已完成步骤的摘要,每步一条独立消息:

```
message: "⏭️ static (1/12) [Resume]:L1=4.5 L2=PASS L3=23 L4=轻微 L5=良好 | TP=95% TN=100%"
message: "⏭️ cases (2/12) [Resume]:32 用例 (HP:10 EC:6 NEG:5 ROB:3 SEC:3 E2E:3 AL:2)"
message: "⏭️ sync-pull (3/12) [Resume]:skipped_no_config"
message: "⏭️ sync-push-cases (4/12) [Resume]:skipped_no_config"
message: "✅ executor-with (5/12) [Resume]:Run-1 32/32 | Run-2 31/32 | Run-3 32/32"
message: "→ 当前步骤:grader (6/12)..."
```

禁止:
- 直接跳到当前步骤而不展示前置步骤
- 合并多个步骤为一条消息
- 用‌"5/12"这样的数字而不解释前 4 步发生了什么

原因:用户看到 "5/12" 但不知道前 4 步是什么结果 = 黑箱感 = 不信任。Resume 的目的是节省执行时间,不是节省展示时间。
5. 如果用户指定了 Skill 名但未指定模式,只发模式选择卡片(单问题)
6. 如果用户同时指定了 Skill 和模式,跳过卡片直接进入推断
7. **每个步骤必须输出一条独立消息**:
   - 执行的步骤:输出结果(含关键数据摘要,不能只写"成功")
   - 跳过的步骤:输出「⏭️ Step X {名称} (Skipped):跳过(原因)」+ 内容摘要
   - 禁止合并为一条消息,禁止静默跳过任何步骤
   - sentry-static 跳过时:输出规则数量 + 覆盖率摘要
   - sentry-cases 跳过时:输出用例清单表格(ID、类型、用例名、断言详情)
   - 示例:
     ```
     ⏭️ sentry-cases:跳过(复用上次用例,hash 匹配)

     | # | 类型 | 用例名 | 断言详情 |
     |---|------|-------|----------|
     | E001 | happy_path | 清单查询-预算申请列表 | E1: 调用list工具(exact) E2: 返回含单号(semantic) E3: 未编造(exact) |
     | E002 | happy_path | 单号详情-BR202503250232 | E1: BR路由到预算系统(exact) E2: 展示审批状态(exact) E3: 结构化输出(semantic) |
     | ... | ... | ... | ... |
     ```

---

## 架构设计模式(四大支柱)

> 详细踩坑案例见 `./references/pitfall-guide.md`
> 步骤契约定义见 `./references/step-contracts.md`

本 Skill 的架构基于四个设计模式,**每次调度循环都必须遵守**:

| 模式 | 核心规则 | 违反后果 |
|------|---------|---------|
| **管道** (Pipeline) | 每步有独立输入/输出契约,步骤间不能跳线 | 产物缺失→降级,不是静默跳过 |
| **状态机** (State Machine) | session.json.last_step 是唯一流转依据,不靠上下文记忆 | 非法转移→abort+告警 |
| **降级兜底** (Graceful Degradation) | 超时/失败有 L1→L2→L3 三级降级 | 标注 [DEGRADED] 但不终止 |
| **幂等** (Idempotent) | 同 hash+同模式+同天 → 提示复用 | 跳过重复执行 |

**合法状态转移表**(违反即 abort):
```
idle → step-0 → step-1 → step-2 → [pipeline per mode] → publish → idle
```

**各模式的合法 pipeline**(按 session.json.pipeline 数组严格执行,不可自行跳步):
- smoke: `["cases", "sync-pull", "sync-push-cases", "executor-with", "grader", "sync-push-results", "publish"]`
- quick: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "grader", "sync-push-results", "report", "publish"]`
- regression: `["sync-pull", "executor-with", "grader", "sync-push-results", "publish"]`
- standard: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "grader", "sync-push-results", "report", "comparator", "gate", "publish"]`
- full: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "grader", "sync-push-results", "report", "comparator", "analyzer", "gate", "publish"]`

Step 2 推断完成后写入 session.json.pipeline,Step 3 调度循环严格按数组顺序执行。
不在当前模式 pipeline 数组中的步骤 = 不存在。

**降级触发条件**:
- subagent 900s 未完成 → L2(批量快速模式)
- L2 也超时 → L3(纯统计,标注 [DEGRADED-L3])
- 产物缺失率 > 20% → 触发降级而非继续

---

## Step 3:无状态调度循环

### 核心原则:主会话只调度,不执行

主会话永远只做三件事:**派活、验收、通知用户**。所有复杂步骤(含 sentry-report)全部委派给 subagent 执行。

**⛔ 主调度器铁律(每轮必须遵守)**:
1. 每轮开始必须 read session.json(不靠记忆)
2. Step 0、1、2 各自发独立消息(禁止合并)
3. 缓存命中时展示完整摘要(见下方自约束清单)
4. 发消息前过自约束清单(任何一项未过 = 不发送)
5. 每步完成后写 session.json.evidence(files_read + artifacts_created)

原因:主会话经历多轮 yield/resume 后上下文疲劳,会导致跳步、简化、凭记忆执行。委派给 subagent 可结构性避免此问题。

### 每轮调度流程(无状态,不靠上下文记忆)

```
1. 读 session.json → 取 last_step
2. 查 pipeline 定义 → 确定 next_step
3. 读取 next_step 对应子工具的 SKILL.md(必须 read,不能凭记忆)
4. spawn subagent(task = SKILL.md 内容 + session 数据 + 输入文件路径)
5. 写入 active-pipeline.json(见下方「Pipeline 持久化与自动恢复」)
6. sessions_yield 等回调(⛔ 禁止 stop,必须 yield)
7. resume 后验收产物(检查文件是否存在)
8. 向用户展示结果 + 更新 session.json last_step
9. 删除 active-pipeline.json
10. 回到 1(不靠记忆,靠文件状态)
```

### Pipeline 持久化与自动恢复

**设计目标**:即使主 session 意外终止(LLM 忘记 yield、超时、崩溃),pipeline 也能在下次心跳时自动恢复,不会静默断裂。

#### Checkpoint 文件

路径:`~/.openclaw/data/skill-eval/active-pipeline.json`

```json
{
  "skill": "finance-doc-query-prod",
  "mode": "standard",
  "session_dir": "2026-05-07_003",
  "current_step": "executor-with",
  "next_step": "grader",
  "pending_subagents": ["executor-run1-all", "executor-run2-all", "executor-run3-all"],
  "started_at": "2026-05-07T15:03:00+08:00",
  "timeout_minutes": 60,
  "workspace_dir": "~/.openclaw/data/skill-eval/sessions/finance-doc-query-prod/2026-05-07_003/"
}
```

#### 写入时机(⛔ 必须在 spawn 之后、yield 之前)

每次 spawn 长时间 subagent(executor、grader、comparator、analyzer)后,**立即**写入 checkpoint:

```
spawn subagent → write active-pipeline.json → sessions_yield
```

⛔ **铁律**:spawn 后不写 checkpoint 就 yield = 违规。spawn 后不 yield 直接 stop = 严重违规(pipeline 必断)。

#### 清理时机

以下任一条件满足时删除 `active-pipeline.json`:
- subagent 完成 + 验收通过 + session.json.last_step 已更新
- pipeline 最终步骤(publish)完成
- 用户手动取消测评

#### 自动恢复(心跳触发)

系统 cron 每 10 分钟发送 `PIPELINE_CHECK` systemEvent 到主 session。收到后执行:

```
1. exec: cat ~/.openclaw/data/skill-eval/active-pipeline.json 2>/dev/null
2. 文件不存在 → HEARTBEAT_OK(无活跃 pipeline)
3. 文件存在 →
   a. sessions_list 查 pending_subagents 的状态
   b. 全部 done → 读本 SKILL.md → 从 next_step 继续执行(验收产物 → 展示结果 → 推进 pipeline)
   c. 仍在运行 + 未超时 → HEARTBEAT_OK(正常等待)
   d. 超时(started_at + timeout_minutes 已过)→ 通知用户 "⚠️ Pipeline 超时: {skill} 的 {current_step} 已运行超过 {timeout_minutes}min"
```

#### 恢复后的行为

恢复执行时,主调度器从 checkpoint 的 `next_step` 开始,按正常流程:
- 读 session.json 确认上下文
- 验收上一步产物
- 推进到 next_step
- 继续正常调度循环

**不需要重跑 Step 0/1/2**,直接从 pipeline 断点续接。

### pipeline 定义(每步的子工具 + 产物清单)

| 步骤 | 子工具 | SKILL.md 路径 | 必须产物 | 调度方式 |
|------|---------|--------------|---------|----------|
| static | sentry-static | ./tools/sentry-static/SKILL.md | session.json.lint + trigger_eval.json | subagent |
| cases | sentry-cases | ./tools/sentry-cases/SKILL.md | evals.json + cases.cache.json | subagent(↩️ auto-exempt 步骤需主会话中转) |
| executor-with | sentry-executor | ./tools/sentry-executor/SKILL.md | eval-*/run-{1..R}/with_skill/outputs/* | 批次 subagent(runs数: smoke=1, quick=2, standard/full=3) |
| executor-without | sentry-executor | ./tools/sentry-executor/SKILL.md | eval-*/run-1/without_skill/outputs/* | subagent(仅 standard/full + text_generation) |
| grader | sentry-grader | ./tools/sentry-grader/SKILL.md | eval-*/grading.json + grading-summary.json | 单 subagent |
| report | sentry-report | ./tools/sentry-report/SKILL.md | report.html + history.json 更新 | subagent(quick+) |
| comparator | sentry-comparator | ./tools/sentry-comparator/SKILL.md | comparator-results.json | subagent(standard/full) |
| analyzer | sentry-analyzer | ./tools/sentry-analyzer/SKILL.md | analyzer-recommendations.json | subagent(full only) |
| publish | 主调度器直接执行 | - | 飞书文件URL + 所有权转让 + 最终卡片 | 主会话直接执行 |

**executor-without 跳过条件**:mcp_based + smoke/quick → 跳过(N/A),Delta 标注"N/A(跳过 without_skill)"

**publish 步骤内容**(主调度器直接执行,不 spawn):

**首选方式：调用 `scripts/publish.py` 一步完成三件套**:
```bash
python3 scripts/publish.py \
  --workspace-dir {iteration_dir} \
  --skill-name "{skill_name}" \
  --user-open-id "{user_ou_id}" \
  --mode {mode} \
  --risk-level {risk_level} \
  [--avg-delta {delta}] \
  [--user-name "{user_name}"]
```
脚本输出 JSON 到 stdout，包含 html_path + feishu_upload_instructions + message。
主调度器根据输出：
1. 执行 `feishu_drive_file(action=upload, file_path=html_path)` → 获取 file_token
2. 执行 `feishu_drive_permission(action=transfer_owner, token=file_token, member_id=user_ou_id)` → 转让
3. 执行 Completion Gate 检查(见 references/output-format.md)→ 确定状态为 COMPLETE/PARTIAL/BLOCKED
4. 发送最终结果卡片(含 HTML 链接 + 五部分完整格式 + completion_status)
5. 更新 session.json.last_step = "publish"

### 主调度器自约束检查清单(每次发消息前必须过)

主调度器(即我自己)在每次向用户发送消息前,必须检查:

```
☐ 本次是否 read 了 SKILL.md 或相关 references?(凭记忆 = 违规)
☐ 缓存命中时,是否展示了完整摘要(不是一行带过)?
☐ Step 0/1/2 是否各自独立发送(不合并)?
☐ 消息内容是否含具体数据(不是“完成”两字)?
☐ session.json 是否记录了 evidence(files_read + artifacts_created)?
☐ Resume 时是否逐步展示了已完成步骤的摘要?(跳过执行 ≠ 跳过展示)
☐ 进度条(N/M)出现前,前面每一步是否都有对应消息?
```

**任何一项未通过 = 不发送,先补做。**

**缓存命中时的最低展示要求**:
- check 缓存: 必须展示 L1-L5 每项结果 + TP/TN 具体数值 + 来源 session
- cases 缓存: 必须展示完整用例表格(17 行,每行含 ID/类型/用例名/断言详情)
- 禁止用 "hp:5 edge:3" 这种一行摘要代替

---

### 产物验收(每步 subagent 完成后,主会话执行)

> 完整输出格式见 `./references/output-format.md`

subagent 完成 → 主会话按顺序执行 4 个动作(不可跳过、不可简化):

| 动作 | 内容 | 工具 |
|------|------|------|
| 1 | 读 progress.json | `exec: cat {workspace}/progress-run-{R}.json` |
| 2 | 检查产物完整性(缺失率>20% → 触发降级) | `exec: 遍历 eval-*/outputs/` |
| 3 | 向用户发送 per-eval 结果表(格式见 output-format.md) | `message(action=send, msg_type="text")` |
| 4 | 更新 session.json.last_step + milestones | `exec: python3 更新 JSON` |

**⛔ 关键约束**:
- 动作 3 **必须用 message(action=send)**,禁止纯文本回复
- 输出格式要求**必须注入 subagent task prompt**(不能只写在此处"期望被记住")
- 跳过任何动作 = 用户有权要求重跑
- 所有模式(smoke/quick/standard/full/regression)适用

### auto-exempt 步骤的特殊处理

cases 步骤含 auto-exempt 环节(数据采集、用例审核),需主会话与用户交互:
1. subagent 完成需求分析 + 用例设计 → 写入文件
2. 主会话读取文件 → 展示给用户 → 等待确认/补充
3. 用户确认后继续下一步

### 其他规则

- **缓存复用**:SKILL.md hash 一致 + 产物存在 → 复用,标注「⚡ 缓存命中(上次 {date})」

**缓存跳过展示规则**(跳过不等于静默,必须展示复用内容摘要):
- check 缓存命中:展示 L1-L5 各项结果 + 触发率 TP/TN + 来源 session
- cases 缓存命中:展示按类型分组的用例清单表格 + 断言统计(exact/semantic/existence)
- 禁止只输出"缓存命中,跳过"
- **快速失败**(quick 模式):grader 评审前几个 eval 后通过率 < 20% → 询问是否继续
- **透明执行**:每步完成后必须展示结果,自动模式也不例外
- **⛔ 禁止**:主会话直接执行任何子工具的业务逻辑;凭记忆生成报告/用例/评分;手写用例替代 sentry-cases
- **⛔ 所有模式必须 spawn sentry-cases subagent**:禁止主会话自己编写 evals.json。但流程深度按模式分级(见下方「模式分级控制」)
- **⛔ 报告产出按模式分级**:详见 `./references/step-contracts.md` 的 publish 分级表

### 模式分级控制

> 详见 `./references/mode-levels.md`

sentry-cases subagent 的 task 中必须注入 `mode` 参数,子工具根据 mode 自动调整流程深度。

### 进度可见性规范

**原则**:用户不应在任何时刻感到「黑盒」。

- 每个 step 完成后发一条独立 message,不是最后一起发
- Step 0、Step 1、Step 2 必须各自独立发送,禁止合并
- grader 结果卡片必须包含 per-assertion 详情(smoke/quick 全量,standard/full 只展示 failed)
- 缓存命中时必须展示内容摘要,禁止只写"缓存命中,跳过"
- **进度摘要**:每完成一个 pipeline 步骤后,在消息末尾附加进度条:`[██████░░░░] 3/5 steps`(用 █ 和 ░ 字符模拟)

---

## 飞书同步(已纳入 pipeline 状态机)

> config.json 不存在时,所有操作静默跳过并记录 `skipped_no_config`,不中断主流程。
> 详细执行流程见:`./references/feishu-sync.md`

**❗ v8.4.0 重要变更**:sync 步骤已从"步骤间隙的附加动作"升级为 pipeline 正式步骤。
状态机强制执行,不再依赖主调度器"记得"执行。

| pipeline 步骤 | 执行内容 | 准出条件 |
|--------------|----------|----------|
| sync-pull | 从飞书 Bitable 拉取 human 用例合并到 evals.json | session.json.sync.pull != null |
| sync-push-cases | 将 evals.json 推送到飞书 Bitable 用例表 | session.json.sync.push_cases != null |
| sync-push-results | 将 grading.json 推送到飞书 Bitable 运行记录表 | session.json.sync.push_results != null |
| gate | Completion Gate 校验(7项),确定 COMPLETE/PARTIAL/BLOCKED | session.json.verdict.completion_status != null |

**降级规则**:
- config.json 不存在 → sync 步骤执行结果为 `skipped_no_config`,不阻断流程
- config.json 存在但同步失败 → 记录 error,不阻断,但 report 中标注"同步异常"

**PUSH-RUN 保留在 publish 内部**(依赖 gate 结果,拆出来反而需要两步)

关键规则(所有模式):
- ⛔ sync 步骤在 pipeline 中不可跳过(可降级为 skipped_no_config,但必须被状态机走过)
- ⛔ 报告前置校验:sync.push_cases 和 sync.push_results 必须非 null
- gate 步骤仅 standard/full 模式启用(smoke/quick 的简单校验内嵌在 publish 中)

## Pipeline 准出标准

> 详见 `./references/step-contracts.md`

---

## session.json

完整 schema 见:`./references/session-json-schema.md`

写入时机:Step 1 写基础字段 → 各步完成后写对应字段 → grader 完成写 verdict/recommendations。

### Token 计量(v8.0 新增)

每步 spawn subagent 前后通过 `session_status` 获取 usage 差值,记录该步骤消耗的 token 数。

写入 session.json 的 `cost` 字段:
```json
{
  "cost": {
    "static": 12500,
    "cases": 18000,
    "executor": 45000,
    "grader": 32000,
    "report": 8000,
    "total": 115500
  }
}
```

**采集方法**:
1. spawn 前:`before_usage = session_status().usage.total_tokens`
2. subagent 完成后:`after_usage = session_status().usage.total_tokens`
3. 差值写入:`cost[step_name] = after_usage - before_usage`
4. 最后 publish 时汇总 `cost.total = sum(cost.values())`

*v8.5.1 · 飞书卡片从 V1 action 语法迁移到 V2 form+select_static原生组件 + publish.py 三件套脚本 · 2026-05-11*
*v8.5.0 · Pipeline持久化+自动恢复(active-pipeline.json + 10min watchdog cron) + spawn后必须yield铁律 · 2026-05-08*
*v8.4.0 · sync步骤纳入pipeline状态机(结构性修复⛔标记≠执行保障) + 坂26 · 2026-05-07*
*v8.3.0 · 合入数据污染四层模型(坂23-28) + CI能力对齐 · 2026-05-03*
*v8.2.0 · 融合 OpenClaw 生产改进(数据隔离/进度条/缓存展示详化/timeout调整/workspace路径分离/admission-criteria/faq) + 保留CI能力 · 2026-05-03*
*v8.1.0 · 融合 v8.0.0 四大支柱+pipeline数组+checkpoint resume+token计量+sentry-static三合一 + 保留CI能力(sentry_ci.py) · 2026-05-03*
*v8.0.0 · sentry-static 三合一 + checkpoint resume + grader分批 + token计量 + dashboard + 结果卡片折叠优化 · 2026-05-03*

<!-- 旧版本历史已移至 CHANGELOG.md -->

---

### subagent task prompt 标准注入清单

spawn 每个 subagent 时,task prompt **必须**包含以下内容(不可省略):

```
## must_read(不读不得执行)
1. [文件路径1]
2. [文件路径2]
(从 step-contracts.md 的 must_read 字段复制)

## 输出路径
{workspace_dir}/[具体路径]

## completion message 格式
[从 output-format.md 复制对应步骤的格式要求]

## Evidence 要求
完成后你的最终输出必须包含:
- 你实际 read 了哪些文件(路径列表)
- 你创建了哪些产物(路径列表)
- 验证结果摘要
```

⛔ 不含上述内容的 task prompt = 违规。主调度器自约束清单第 1 项检查此项。
