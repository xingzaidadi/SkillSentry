---
name: sentry-sync
description: >
  SkillSentry 飞书用例同步工具，负责用例库与飞书多维表格之间的双向同步。
  通常由 sentry-executor（执行前 PULL）和 sentry-report（完成后 PUSH）自动调用，不需要用户显式触发。
  触发场景：说"同步飞书用例"、"把用例推到飞书"、"从飞书拉取用例"。
  不触发场景：要执行测试用例、要生成报告、要做完整流程——那些工具会自动调用此工具。
---

# sentry-sync · 用例飞书同步层

SkillSentry 与飞书多维表格之间的双向同步桥接。负责执行前拉取用例、执行后推送结果、新用例推送待 Review、规则变更时标记失效用例。

**关键前提**：config.json 必须存在且包含有效配置。查找顺序：`~/.openclaw/workspace/skills/SkillSentry/config.json` → `~/.openclaw/skills/SkillSentry/config.json` → `~/.claude/skills/SkillSentry/config.json`。否则所有操作静默跳过，SkillSentry 退化为纯本地模式。

---

## 配置检查（所有操作的前置步骤）

```
按查找顺序读取 config.json（~/.openclaw/workspace/skills/SkillSentry/ → ~/.openclaw/skills/SkillSentry/ → ~/.claude/skills/SkillSentry/）
  → 不存在：输出「ℹ️ 飞书同步未配置（config.json 不存在），跳过」，立即返回
  → 存在但字段缺失：输出「⚠️ config.json 缺少必要字段：[字段名]，跳过同步」，立即返回
  → 配置完整：继续执行
```

**config.json 必要字段**：
```json
{
  "feishu": {
    "app_id": "cli_xxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxx",
    "app_token": "BascXXXXXXXXXXXX",
    "cases_table_id": "tblXXXXXXXXXXXX",
    "version_labels_table_id": "tblXXXXXXXXXXXX",
    "run_history_table_id": "tblXXXXXXXXXXXX"
  }
}
```

---

## 操作一：PULL（执行前拉取用例）

**调用时机**：sentry-executor 执行前，自动调用。

### Step 1：获取 tenant_access_token

```bash
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Body: {"app_id": "<app_id>", "app_secret": "<app_secret>"}
→ 提取 tenant_access_token，有效期 2 小时
```

### Step 2：查询飞书用例库

```bash
GET https://open.feishu.cn/open-apis/bitable/v1/apps/<app_token>/tables/<cases_table_id>/records
Params:
  filter: AND(CurrentValue.[skill_name]="<skill_name>", CurrentValue.[status]="active")
  page_size: 500
```

返回空（该 Skill 无 active 用例）→ 输出「ℹ️ 飞书中无 <skill_name> 的 active 用例，使用本地用例集」，跳过后续步骤。

### Step 3：转换并写入本地

将飞书记录转换为 SkillSentry 用例格式，写入 `inputs_dir/cases.feishu.json`：

```json
{
  "pulled_at": "<ISO时间>",
  "skill_name": "<skill_name>",
  "source": "feishu",
  "cases": [
    {
      "id": "<case_id>",
      "display_name": "<display_name>",
      "type": "<type>",
      "rule_ref": "<rule_ref>",
      "prompt": "<prompt>",
      "expectations": [...],
      "source": "human",
      "priority": "<P0/P1/P2>",
      "feishu_record_id": "<record_id>"
    }
  ]
}
```

### Step 4：MARK_STALE 检查（PULL 附带执行）

对比飞书中该 Skill 的所有用例（含 active/needs_review）的 `created_skill_hash` 与当前 SKILL.md hash：

```
hash 一致 → 跳过
hash 不一致 → 检查用例的 rule_ref 是否仍存在于当前 SKILL.md 中
  rule_ref 已删除 → 更新飞书记录 status = "stale"，写 notes = "规则 <rule_ref> 已从 SKILL.md 删除（检测时间：<日期>）"
  rule_ref 仍存在 → 更新飞书记录 status = "needs_review"，提示人工确认断言是否仍有效
```

输出摘要：`🔄 PULL 完成：拉取 [N] 条 active 用例，标记 stale [N] 条，标记 needs_review [N] 条`

---

## 操作二：PUSH 结果（报告完成后推送）

**调用时机**：sentry-report 生成报告后，自动调用。

### Step 1：写入运行记录表

```bash
POST https://open.feishu.cn/open-apis/bitable/v1/apps/<app_token>/tables/<run_history_table_id>/records
Body:
{
  "fields": {
    "run_id": "<YYYY-MM-DD_NNN>",
    "skill_name": "<skill_name>",
    "skill_hash": "<skill_hash>",
    "skill_label": "<version_labels 表中对应的 label，无则留空>",
    "mode": "<smoke/quick/standard/full>",
    "grade": "<S/A/B/C/D/F>",
    "verdict": "<PASS/CONDITIONAL PASS/FAIL>",
    "pass_rate_overall": <综合通过率>,
    "pass_rate_exact": <精确断言通过率>,
    "pass_rate_golden": <P0用例通过率，无P0用例则留空>,
    "delta": <Δ值，mcp_based则填 "N/A">,
    "case_set_snapshot": "<JSON字符串：{case_id: content_hash}>",
    "comparable_to": "<与上一次相同case_set_snapshot的run_id，无则留空>",
    "workspace_path": "<本次 session 目录绝对路径>",
    "ran_at": "<ISO时间>"
  }
}
```

### Step 2：更新用例库 last_run

对参与本次运行的每条用例（有 feishu_record_id 的），批量更新：

```bash
POST https://open.feishu.cn/open-apis/bitable/v1/apps/<app_token>/tables/<cases_table_id>/records/batch_update
Body: 每条记录更新 last_run_result（pass/fail/inconclusive）和 last_run_date
```

**注意**：只更新飞书中已有的用例（有 feishu_record_id）。本次 AI 生成的新用例通过操作三推送。

输出：`✅ PUSH 完成：运行记录已写入飞书，更新 [N] 条用例的最新运行结果`

---

## 操作三：PUSH 新用例（用例生成后推送）

**调用时机**：sentry-cases 生成 evals.json 后，将 `source="ai-generated"` 且无 `feishu_record_id` 的用例推送至飞书。

### Step 1：计算 case_id 去重

```
case_id = MD5(skill_name + rule_ref + prompt前50字)
```

查询飞书：`filter: CurrentValue.[case_id]="<case_id>"` → 已存在则跳过，不重复推送。

### Step 2：批量创建新用例

```bash
POST https://open.feishu.cn/open-apis/bitable/v1/apps/<app_token>/tables/<cases_table_id>/records/batch_create
Body: 每条用例字段
  case_id, skill_name, display_name, type, rule_ref, prompt, expectations(JSON字符串),
  source="ai-generated", priority="P1"（默认）, status="pending_review",
  content_hash=MD5(prompt+expectations), created_skill_hash=<当前skill_hash>
```

输出：`📤 PUSH 完成：[N] 条新用例已推送至飞书（status=pending_review），请人工 review 后激活`

---

## 错误处理

| 错误类型 | 处理方式 |
|---------|---------|
| token 获取失败 | 输出错误信息，跳过本次同步，不中断测评流程 |
| 飞书 API 超时（>10s）| 重试 1 次，仍失败则跳过，记录到 `sync_error.log` |
| 记录创建冲突（重复 case_id）| 跳过该条，继续其他记录 |
| 网络不可达 | 跳过全部同步，输出「⚠️ 飞书 API 不可达，本次跳过同步」 |

**核心原则**：sentry-sync 的任何失败都不允许中断 SkillSentry 主流程。同步是增强，不是依赖。
