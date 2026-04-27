---
name: SkillSentry
description: >
  SkillSentry — AI Skill 质量测评系统。
  触发场景：说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  不触发场景：讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
---

# SkillSentry · AI Skill 质量守门人

极简调度器：找 Skill → 选模式 → 按顺序调子工具 → 每步等确认。

---

## 平台适配层

检测方式：消息来自飞书/Telegram → `runtime="openclaw"`；其他 → `runtime="cli"`。

| 能力 | CLI / OpenCode | OpenClaw（飞书）|
|------|---------------|----------------|
| 子任务调用 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=600)` |
| 步骤输出 | 打印到终端 | `message(msg_type="interactive", ...)` |
| 步骤校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit |
| 步骤等待 | 60s 无响应自动继续 | 等用户说「继续」（无超时）|
| 自动模式 | `--ci` 跳过所有等待 | `自动` 跳过所有等待 |

**OpenClaw 额外要求**：每步完成后将 `{msg_type, message_id, sent_at}` 写入 `session.json.milestones.step-N`。`validate_step.py` 会校验此字段。

---

## 子工具

| 工具 | 职责 | 独立可用 |
|------|------|---------|
| `sentry-check` | 静态结构检查（L1-L5）+ 触发率模拟（TP/TN）| ✅ |
| `sentry-cases` | 测试用例设计，输出 evals.json | ✅ |
| `sentry-executor` | 用例并行执行，输出 transcript | ✅ |
| `sentry-grader` | 断言评审，输出 grading.json | ✅ |
| `sentry-report` | 报告 + 发布决策 + HiL 确认 | ✅ |

---

## 特殊命令

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry` | 检查所有子工具是否存在，逐一列出 ✅/❌ |
| `lint xxx` / `检查结构` / `有没有HiL问题` | 只跑 sentry-check（lint 模式）|
| `测触发率` / `description 准不准` | 只跑 sentry-check（trigger 模式）|
| `设计用例 xxx` / `只出 cases` | 只跑 sentry-cases |
| `跑用例` / `用现有用例` | executor → grader → report |
| `出报告` / `通过了吗` / `看结果` | sentry-report（需已有 grading.json）|

---

## Step 1：找 Skill + 初始化

**查找优先级**：
1. 用户提供路径 → 直接使用
2. 用户只说名字 →
   - CLI: `~/.claude/skills/<名字>/` → `~/.config/opencode/skills/<名字>/`
   - OpenClaw: `~/.openclaw/workspace/skills/<名字>/` → `~/.openclaw/skills/<名字>/`
3. 「测评这个 skill」→ 当前目录下的 SKILL.md

找不到 → `❌ 找不到 Skill：{name}。已搜索：{paths}。请确认拼写或提供完整路径。`

**工作路径**：
```
CLI:
  workspace_dir = ~/.claude/skills/SkillSentry/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
  inputs_dir    = ~/.claude/skills/SkillSentry/inputs/<Skill名>/
OpenClaw:
  workspace_dir = ~/.openclaw/workspace/skills/SkillSentry/sessions/<Skill名>/<YYYY-MM-DD>_NNN/
  inputs_dir    = ~/.openclaw/workspace/skills/SkillSentry/inputs/<Skill名>/
```

目录不存在 → 自动创建。

**skill_type 检测**：含业务 MCP 工具名（camelCase）→ `mcp_based`；含 bash/python/exec → `code_execution`；其他 → `text_generation`。详见 `references/execution-phases.md`。

**MCP 预检（仅 mcp_based）**：列出引用工具 → 检查可用性 → 全不可用则终止。

**飞书同步配置检查**：
```
查找 config.json：workspace_dir 父目录 → inputs_dir 父目录 → SkillSentry 根目录
  → 不存在：纯本地模式，所有 PUSH/PULL 标记为 skipped_no_config
  → 存在：启用飞书同步
```

写 `session.json`（skill / mode / skill_type / skill_hash / runtime / started_at）。
输出：`✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`

---

## Step 2：智能工作流推断

### 单工具快速调用（见「特殊命令」表，跳过推断）

### 工作流推断（用户只说「测评 xxx」）

```
计算 SKILL.md MD5 → 读取 inputs_dir/rules.cache.json
  不存在               → quick（首次测评）
  hash 不匹配          → smoke（Skill 有变更）+ MARK_STALE
  hash 匹配 + cases 存在    → regression
  hash 匹配 + cases 不存在  → quick
```

**工作流模式**：

| 模式 | 工具链 | 预计时间 |
|------|--------|---------|
| smoke | cases(4-5个) → executor(1次) → grader → report | ~5-7min |
| quick | check → cases → executor(2次) → grader → report | ~10-15min |
| regression | executor(golden only) → grader → report | ~5-10min |
| standard | check → cases → executor(3次) → grader → comparator → report | ~30-45min |
| full | check → cases → executor(3次) → grader → comparator → analyzer → report | 45min+ |

输出确认（自动模式直接开始）：
```
✅ 被测 Skill：{name} | 类型：{type} | 推荐：{mode}（{原因}）
预计时间：{time} | Token 预估：{range}
回复「开始」或 30 秒后自动开始。
```

OpenClaw 无上下文时：用 `feishu_ask_user_question` 发卡片选择 Skill + 模式。

---

## Step 3：执行循环

对当前模式的每个步骤，依次执行：

```
1. 强制读取该子工具的 SKILL.md（必须 read，不能凭记忆）
2. 按子工具 SKILL.md 指令执行
3. 步骤校验：
     CLI      → 检查 [sentry-proof] 标记，缺失则重跑
     OpenClaw → 执行 validate_step.py，FAIL 则停下修复
4. 输出进度回执：
     ✅ {子工具名} 完成 | ⏱ {耗时} | {1-2 行关键数据}
     全局进度：sentry-check ✅ | sentry-cases ✅ | sentry-executor 🔄 | ...
5. 等待确认（CLI 60s 自动，OpenClaw 等用户，自动模式跳过）
6. 更新 session.json 的 last_step
```

**缓存复用**：SKILL.md hash 一致 + 产物存在 → 复用，标注「⚡ 缓存命中（上次 {date}）」。

**快速失败检测**（quick 模式，第一批 grader 完成后）：通过率 < 20% → 询问是否继续。

**⛔ 禁止**：凭记忆执行子工具；一条消息跑多个步骤（自动模式下每步仍独立展示）。

---

## 飞书同步

> config.json 不存在时，所有操作静默跳过并记录 `skipped_no_config`，不中断主流程。

### PULL（executor 执行前自动调用）

```
POST /auth/v3/tenant_access_token/internal → tenant_access_token
GET  /bitable/v1/apps/{app_token}/tables/{cases_table_id}/records
     filter: skill_name="{name}" AND status="active"
→ 写入 inputs_dir/cases.feishu.json
→ 与 evals.json 合并（飞书 human 用例优先）
→ 输出：「🔄 已从飞书同步 [N] 条用例」
```

**MARK_STALE（PULL 附带，hash 不匹配时）**：rule_ref 已删除 → status="stale"；仍存在 → status="needs_review"。

### PUSH-CASES（sentry-cases 完成后，Step 4.5，不可跳过）

```
1. 对 evals.json 中无 feishu_record_id 的用例：
   case_id = MD5(skill_name + rule_ref + prompt 前50字)
2. 查询飞书去重（case_id 已存在则跳过）
3. POST /bitable/.../records/batch_create → 推送新用例（status=pending_review）
4. 解析返回的 records 列表，提取每条 record_id
   按 case_id 匹配 evals.json 中对应用例，追加 feishu_record_id 字段
   覆盖写 evals.json（保留所有原有字段）
5. 更新 session.json sync.push_cases = "done"
→ 输出：「📤 PUSH-CASES：[N] 条新用例已推送飞书（pending_review）」
```

### PUSH-RESULTS（grader 完成后，Step 6.5，不可跳过）

```
1. 读取 evals.json，找出有 feishu_record_id 的用例
2. POST /bitable/.../records/batch_update → 更新 last_run_result + last_run_date
3. 更新 session.json sync.push_results = "done"
→ 输出：「✅ PUSH-RESULTS：更新 [N] 条用例结果」
```

**Step 7 前置校验**（报告前强制检查）：
```
sync.push_cases ≠ null AND sync.push_results ≠ null → 继续
任一为 null → ⛔ 阻断，输出缺失项，要求补执行
```

### PUSH-RUN（report 完成后，Step 7.5，不可跳过）

```
1. POST /bitable/.../tables/{run_history_table_id}/records
   fields: run_id, skill_name, skill_hash, mode, grade, verdict, pass_rate_overall, ran_at
2. 更新 session.json sync.push_run = "done"
→ 输出：「✅ PUSH-RUN：运行记录已写入飞书」
```

---

## Pipeline 准出标准

| 步骤 | 准出条件 | 未通过 |
|------|---------|--------|
| sentry-check | 无 P0（lint）/ TP ≥ 70%（trigger）| P0 → 暂停；TP 低 → 警告继续 |
| sentry-cases | 用例数 ≥ 3 | 警告「覆盖不足」|
| sentry-executor | ≥ 1 个有 transcript | 全失败 → 终止，报告环境问题 |
| sentry-grader | ≥ 1 个有 grading | 全超时 → 标注「评审缺失」|
| sentry-report | HTML 生成成功 | 失败 → 纯文本摘要替代 |

---

## session.json 结构

```json
{
  "skill": "", "mode": "", "skill_type": "", "skill_hash": "", "runtime": "",
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

写入时机：Step 1 写基础字段 → 各步完成后写对应字段 → grader 完成写 verdict/recommendations。

---

*v7.0 · 单一调度器，平台适配层隔离差异 · 2026-04-27*
