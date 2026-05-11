# feishu-templates.md — 飞书进度推送模板

> 仅 OpenClaw 模式使用。由 SKILL.md 在里程碑完成时按需引用，无需全量加载。

---

## 【1/5】准备阶段完成

```
📋 准备完成
规则提炼：识别到 [N] 条规则（[M] 条硬性规则）
Skill 类型：[mcp_based / text_generation / code_execution]
风险等级：[S/A/B/C 级]
测评模式：[quick/standard/full]（[N] 个用例）
预计耗时：[N] 分钟
```

---

## 【2/5】用例确认（非自动模式）

```
⚙️ 用例设计完成，共 [N] 个用例
覆盖规则：[N]/[N] 条（[XX]%）
断言质量：exact_match [X]% / semantic [X]% / existence [X]%
[仅当 existence 占比 > 50% 时] ⚠️ existence 断言占 [X]%，建议升级为 exact_match，否则测评区分度低
是否开始执行？
  → 回复「确认」直接开始
  → 回复「修改」进入调整模式
```

---

## 【3/5】执行进度（每批完成时）

```
⏳ 执行进度：[M]/[N] 个用例完成
当前通过率：[XX]%
预计还需：[N] 分钟
```

---

## 【4/5】评分完成

```
📊 评分完成
精确通过率：[XX]%（[M]/[N]）
增益 Δ：[+XX% / -XX%]
IFR：[XX]%
正在生成报告...
```

---

## 【5/5】测评报告摘要卡片

```
━━━━━━━━━━━━━━━━━━━━
📊 SkillSentry 测评报告
━━━━━━━━━━━━━━━━━━━━
Skill：[Skill名称]
结论：[✅ PASS / ⚠️ CONDITIONAL PASS / ❌ FAIL]

核心指标：
  精确通过率：[XX]%（准入要求 ≥[XX]%）
  增益 Δ：[+XX%]（[有价值/无增益/负向]）
  IFR：[XX]%
  触发率估算：[XX]%（置信度 [high/medium/low]）

主要发现：
  [如有 FAIL 用例] ❌ [N] 个用例未通过，需修复
  [如有负向增益]  ⚠️ [N] 个用例存在负向增益
  [如全部通过]    ✅ 所有用例通过，无负向增益
━━━━━━━━━━━━━━━━━━━━
📄 飞书报告：<文档链接>
📁 本地报告：<报告路径>
```

---

## 【前置】Skill 选择卡片（用户未指定 Skill 时）

使用飞书 V2 卡片（`form` + `select_static` + `button`）发送交互表单，通过 `message(action=send, kind=interactive)` 发送。禁止纯文本罗列。

⚠️ **V2 卡片规则**：禁止使用已废弃的 V1 `action` 容器标签。交互组件（select_static/button）必须放在 `form` element 内部，或直接作为独立 element 放在 `body.elements` 中。

**构造流程**：
1. 扫描 `~/.openclaw/skills/` + `~/.openclaw/workspace/skills/` 下含 SKILL.md 的目录
2. 排除：sentry-* / SkillSentry* / .bak 目录 / 平台工具
3. 动态生成 options 列表
4. 发送 V2 卡片：

```json
{
  "schema": "2.0",
  "config": {"update_multi": true},
  "header": {
    "title": {"tag": "plain_text", "content": "🧠 SkillSentry v8.5.1 · 测评启动"},
    "subtitle": {"tag": "plain_text", "content": "AI Skill 质量守门人 · 回复 Skill 名称开始"},
    "template": "blue"
  },
  "body": {
    "elements": [
      {"tag": "markdown", "content": "依次选择 **被测 Skill** → **测评模式** → **执行方式**，回复开始："},
      {
        "tag": "column_set",
        "columns": [
          {"tag": "column", "width": "weighted", "weight": 1, "elements": [
            {"tag": "markdown", "content": "**1️⃣ 被测 Skill**\n{skill_name_1} · {描述}\n{skill_name_2} · {描述}\n..."}
          ]}
        ]
      },
      {"tag": "hr"},
      {"tag": "markdown", "content": "**2️⃣ 测评模式**\n🔥 smoke(~5min) · ⚡ quick(~15min) · 📊 standard(~40min) · 🔬 full(~50min) · 🔄 regression(~5min) · 🤖 自动\n\n**3️⃣ 执行方式**\n🚀 自动(全程无需干预) · 👀 逐步确认"},
      {"tag": "hr"},
      {"tag": "markdown", "content": "💡 回复格式：`Skill名 [模式] [自动/逐步]`\n示例：`finance-doc-query-prod quick 自动`\n或直接说 Skill 名，其余默认自动推断"}
    ]
  }
}
```

**Skill 列表生成规则**：扫描每个 Skill 的 SKILL.md frontmatter `description`，截取精练中文描述，格式 `"{skill_name} · {描述}"`。全部用 markdown 展示，用户回复文字选择。

⚠️ **禁止使用 `form` + `button(form_action_type=submit)`**：通过 message tool 发送的卡片没有 CardKit 回调链路，submit 按钮会触发飞书 200530 错误。交互通过用户回复文字实现。

5. 等待用户选择或回复后再继续流程

---

## 启动确认推送（Step 1 解析完成后）

```
✅ 已收到测评请求
   被测 Skill：[skill名称]
   模式：[smoke/quick/standard/full]（已从消息中识别）
   预计耗时：[smoke ~3-5分钟 / quick ~15-25分钟 / standard ~35分钟 / full ~60分钟]
   开始执行，我会在关键节点主动通知你 👇
```

---

## 超时提醒

**5 分钟未收到用户确认**：
```
⏰ 等待你的确认，回复「确认」开始执行，或回复「修改」调整用例
```

**10 分钟仍无回复**：
```
已自动开始执行（默认 quick 模式）
```

---

*Last Updated: 2026-03-30*
