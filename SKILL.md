---
name: skill-eval-测评
version: "7.3"
description: >
  SkillSentry — AI Skill 质量测评系统。
  触发场景：说“测评/测试/验证/评估某个Skill”、“这个skill好不好用”、“能不能上线”、“帮我跑eval”、“Skill质量怎么样”、“上线前先测一下”、“发布前检查”。
  不触发场景：讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
metadata:
  author: 刘四星
  created_at: "2026-03-27"
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

### ⛔ auto 模式不可跳过清单（auto-exempt）

auto 模式跳过的是「步骤间的继续确认」，以下场景即使 auto 模式也**必须阻断等待用户**：

| 场景 | 原因 | 所在步骤 |
|------|------|----------|
| MCP 预检全不可用 | 无法执行任何 real_data 用例，用户需决定配置 MCP 或降级 | Step 1 |
| real_data 测试数据采集 | AI 禁止编造单号/ID，必须用户提供或确认 | sentry-cases Step 0.3 |
| 用例设计审核 | 用户需确认用例覆盖度并决定是否补充 | sentry-cases Step 0.2 |
| 写操作/不可逆操作确认 | 安全要求 | 任意步骤 |

规则：`auto-exempt` 标记的步骤，auto 模式下仍必须展示内容并等待用户响应。

**OpenClaw 额外要求**:每步完成后将 `{msg_type, message_id, sent_at}` 写入 `session.json.milestones.step-N`。`validate_step.py` 会校验此字段。

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

**MCP 预检(仅 mcp_based，⛔ auto-exempt)**:

自动探测链，无需用户手动配置：

```
1. 列出 SKILL.md 中引用的所有 MCP Server
2. 按顺序探测可用后端：
   a) openclaw.json mcpServers → mcp_backend = "native"
   b) mcporter config list     → mcp_backend = "mcporter"
   c) 均未配置                → mcp_backend = "unavailable"
3. 结果分级：
   - 全部可用 → 继续，记录 mcp_backend 到 session.json
   - 部分可用 → 告知用户哪些缺失，询问是否继续（部分用例将受限）
   - 全不可用 → ⛔ 阻断，展示缺失列表，提供两个选项：
     a) 用户配置 MCP 后继续
     b) 降级为纯静态分析（跳过 executor，只出 check + cases + report）
```

mcp_backend 写入 session.json，executor 根据此字段自动选择执行方式：
- `native`：子 agent 直接调用原生 MCP 工具
- `mcporter`：通过 `HOME=/root/.openclaw mcporter call <server>.<tool>(params)` 执行

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
| smoke | cases(4-5个) → executor(1次) → grader → report | ~5-7min |
| quick | check → cases → executor(2次) → grader → report | ~10-15min |
| regression | executor(golden only) → grader → report | ~5-10min |
| standard | check → cases → executor(3次) → grader → comparator → report | ~30-45min |
| full | check → cases → executor(3次) → grader → comparator → analyzer → report | 45min+ |

输出确认(自动模式直接开始):
```
✅ 被测 Skill:{name} | 类型:{type} | 推荐:{mode}({原因})
预计时间:{time} | Token 预估:{range}
回复「开始」或 30 秒后自动开始。
```

**OpenClaw 无上下文时（用户只说「测评」未指定 Skill）**：必须用 `feishu_ask_user_question` 发交互卡片，禁止纯文本罗列。

构造方式：
1. 扫描 `~/.openclaw/skills/` 和 `~/.openclaw/workspace/skills/` 下所有含 SKILL.md 的目录
2. 排除 sentry-* / skill-eval-测评 自身 / SkillSentry / .bak 目录
3. 生成三个问题的卡片：

```
feishu_ask_user_question(questions=[
  {
    "question": "选择要测评的 Skill",
    "header": "被测 Skill",
    "options": [
      // 动态生成，每个 option：
      {"label": "<skill-name>", "description": "<从 SKILL.md frontmatter description 截取前 30 字>"}
    ],
    "multiSelect": false
  },
  {
    "question": "选择测评模式（不选默认自动推断）",
    "header": "测评模式",
    "options": [
      {"label": "smoke", "description": "冒烟测试，4-5 个用例，~5 分钟"},
      {"label": "quick", "description": "快速测评，2 轮执行，~10-15 分钟"},
      {"label": "standard", "description": "标准测评，3 轮+对比，~30-45 分钟"},
      {"label": "full", "description": "完整测评，全流程+根因分析，45 分钟+"},
      {"label": "自动推断", "description": "根据缓存状态自动选择最合适的模式"}
    ],
    "multiSelect": false
  },
  {
    "question": "每个步骤完成后是否需要你确认才继续？选「自动」则全程无需干预",
    "header": "执行方式",
    "options": [
      {"label": "自动", "description": "全程自动执行，每步展示结果但不等确认"},
      {"label": "逐步确认", "description": "每步完成后等你说「继续」再跑下一步"}
    ],
    "multiSelect": false
  }
])
```

4. 等待用户选择后继续 Step 2 剩余流程
5. 如果用户指定了 Skill 名但未指定模式，只发模式选择卡片（单问题）
6. 如果用户同时指定了 Skill 和模式，跳过卡片直接进入推断

---

## Step 3：无状态调度循环

### 核心原则：主会话只调度，不执行

主会话永远只做三件事：**派活、验收、通知用户**。所有复杂步骤（含 sentry-report）全部委派给 subagent 执行。

原因：主会话经历多轮 yield/resume 后上下文疲劳，会导致跳步、简化、凭记忆执行。委派给 subagent 可结构性避免此问题。

### 每轮调度流程（无状态，不靠上下文记忆）

```
1. 读 session.json → 取 last_step
2. 查 pipeline 定义 → 确定 next_step
3. 读取 next_step 对应子工具的 SKILL.md（必须 read，不能凭记忆）
4. spawn subagent（task = SKILL.md 内容 + session 数据 + 输入文件路径）
5. yield 等回调
6. resume 后验收产物（检查文件是否存在）
7. 向用户展示结果 + 更新 session.json last_step
8. 回到 1（不靠记忆，靠文件状态）
```

### pipeline 定义（每步的子工具 + 产物清单）

| 步骤 | 子工具 | SKILL.md 路径 | 必须产物 | 调度方式 |
|------|---------|--------------|---------|----------|
| check | sentry-check | ./tools/sentry-check/SKILL.md | session.json.lint + trigger_eval.json | subagent |
| cases | sentry-cases | ./tools/sentry-cases/SKILL.md | evals.json + cases.cache.json | subagent（↩️ auto-exempt 步骤需主会话中转） |
| executor | sentry-executor | ./tools/sentry-executor/SKILL.md | eval-*/run-*/transcript.md | 批次 subagent |
| grader | sentry-grader | ./tools/sentry-grader/SKILL.md | eval-*/grading.json | 批次 subagent |
| report | sentry-report | ./tools/sentry-report/SKILL.md | report.html + history.json | subagent |

### 产物验收（每步 subagent 完成后，主会话执行）

```
subagent 完成 → 主会话检查必须产物是否存在：
  全部存在 → ✅ 通过，展示结果，进入下一步
  部分缺失 → ⚠️ 告知用户缺失哪些，询问是否重跑
  全部缺失 → ❌ 告知用户 subagent 执行失败，提供重跑选项
```

### auto-exempt 步骤的特殊处理

cases 步骤含 auto-exempt 环节（数据采集、用例审核），需主会话与用户交互：
1. subagent 完成需求分析 + 用例设计 → 写入文件
2. 主会话读取文件 → 展示给用户 → 等待确认/补充
3. 用户确认后继续下一步

### 其他规则

- **缓存复用**：SKILL.md hash 一致 + 产物存在 → 复用，标注「⚡ 缓存命中（上次 {date}）」
- **快速失败**（quick 模式）：第一批 grader 完成后通过率 < 20% → 询问是否继续
- **透明执行**：每步完成后必须展示结果，自动模式也不例外
- **⛔ 禁止**：主会话直接执行任何子工具的业务逻辑；凭记忆生成报告/用例/评分

---

## 飞书同步

> config.json 不存在时,所有操作静默跳过并记录 `skipped_no_config`,不中断主流程。

### PULL(executor 执行前自动调用)

```
OpenClaw: feishu_app_bitable_app_table_record(action=list, app_token, table_id=cases_table_id, filter=...)
CLI:     POST /auth/v3/tenant_access_token/internal → token
         GET  /bitable/v1/apps/{app_token}/tables/{cases_table_id}/records
         filter: skill_name="{name}" AND status="active"
→ 写入 inputs_dir/cases.feishu.json
→ 与 evals.json 合并(飞书 human 用例优先)
→ 输出:「🔄 已从飞书同步 [N] 条用例」
```

**MARK_STALE(PULL 附带,hash 不匹配时)**:rule_ref 已删除 → status="stale";仍存在 → status="needs_review"。

### PUSH-CASES(sentry-cases 完成后,Step 4.5,不可跳过)

```
1. 对 evals.json 中无 feishu_record_id 的用例:
   case_id = MD5(skill_name + rule_ref + prompt 前50字)
2. 查询飞书去重(case_id 已存在则跳过)
3. POST /bitable/.../records/batch_create → 推送新用例(status=pending_review)
4. 解析返回的 records 列表,提取每条 record_id
   按 case_id 匹配 evals.json 中对应用例,追加 feishu_record_id 字段
   覆盖写 evals.json(保留所有原有字段)
5. 更新 session.json sync.push_cases = "done"
→ 输出:「📤 PUSH-CASES:[N] 条新用例已推送飞书(pending_review)」
```

### PUSH-RESULTS(grader 完成后,Step 6.5,不可跳过)

```
1. 读取 evals.json,找出有 feishu_record_id 的用例
2. POST /bitable/.../records/batch_update → 更新 last_run_result + last_run_date
3. 更新 session.json sync.push_results = "done"
→ 输出:「✅ PUSH-RESULTS:更新 [N] 条用例结果」
```

**Step 7 前置校验**(报告前强制检查):
```
sync.push_cases ≠ null AND sync.push_results ≠ null → 继续
任一为 null → ⛔ 阻断,输出缺失项,要求补执行
```

### PUSH-RUN(report 完成后,Step 7.5,不可跳过)

```
1. POST /bitable/.../tables/{run_history_table_id}/records
   fields: run_id, skill_name, skill_hash, mode, grade, verdict, pass_rate_overall, ran_at
2. 更新 session.json sync.push_run = "done"
→ 输出:「✅ PUSH-RUN:运行记录已写入飞书」
```

---

## Pipeline 准出标准

| 步骤 | 准出条件 | 未通过 |
|------|---------|--------|
| sentry-check | 无 P0(lint)/ TP ≥ 70%(trigger)| P0 → 暂停;TP 低 → 警告继续 |
| sentry-cases | 用例数 ≥ 3 | 警告「覆盖不足」|
| sentry-executor | ≥ 1 个有 transcript | 全失败 → 终止,报告环境问题 |
| sentry-grader | ≥ 1 个有 grading | 全超时 → 标注「评审缺失」|
| sentry-report | HTML 生成成功 | 失败 → 纯文本摘要替代 |

---

## session.json 结构

```json
{
  "skill": "", "mode": "", "skill_type": "", "skill_hash": "", "runtime": "", "mcp_backend": "",
  "started_at": "", "last_step": "",
  "requirements": {"rules_total": 0, "explicit": 0, "process": 0, "implicit": 0, "high_risk": 0},
  "lint": {"L1": "", "L2": "", "L3": 0, "P0": 0, "P1": 0, "P2": 0, "issues": []},
  "trigger": {"tp": 0, "tn": 0, "confidence": "", "issues": []},
  "cases": {"total": 0, "coverage": "", "types": {}, "assertions_total": 0},
  "executor": {"total_runs": 0, "success": 0, "failed": 0, "spawn_count": 0, "time_minutes": 0},
  "grader": {"pass": 0, "fail": 0, "total": 0, "pass_rate": 0, "failed_evals": [], "vetoes": []},
  "verdict": {"grade": "", "decision": "", "pass_rate": 0},
  "recommendations": {"P0": [], "P1": [], "P2": []},
  "sync": {"pull": null, "push_cases": null, "push_results": null, "push_run": null},
  "milestones": {}
}
```

写入时机:Step 1 写基础字段 → 各步完成后写对应字段 → grader 完成写 verdict/recommendations。

---

*v7.3 · 主编排改为无状态纯调度器（所有步骤含 report 全部委派 subagent）；pipeline 定义 + 产物验收机制；auto-exempt + MCP探测链 + 飞书时间字段 · 2026-04-27*
