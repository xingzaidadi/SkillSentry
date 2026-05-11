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
              {"text": {"tag": "plain_text", "content": "{skill_2}"}, "value": "{skill_2}"}
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
              {"text": {"tag": "plain_text", "content": "🤖 自动推断"}, "value": "auto"}
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
      {"tag": "markdown", "content": "**可用 Skill 完整列表**：`{skill_1}` · `{skill_2}` · ..."}
    ]
  }
}
```

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
