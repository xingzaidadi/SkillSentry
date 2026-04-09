---
name: sentry-cases
description: >
  为 AI Skill 设计测试用例，输出可直接执行的 evals.json。不执行测试，只做用例设计。
  触发场景：说"帮我设计测试用例"、"生成eval用例"、"我要测这个skill"、"帮我列出测试场景"、
  "cases设计"、"我想知道要测哪些场景"。
  不触发场景：要运行测试用例（需要 sentry-executor）、要做完整测评流程（需要 SkillSentry）。
---

# sentry-cases · Skill 测试用例设计

根据被测 Skill 的规则，设计覆盖多维度的测试用例，输出结构化 evals.json。5-10 分钟完成（有缓存则更快）。

**一句话价值**：把「应该测什么」从大脑搬到文件，供后续反复执行，不必每次重新设计。

---

## 输入

- 被测 Skill 路径（用户提供 或 按名字查找）
- 测评模式（用户指定，默认 quick）：smoke / quick / standard / full
- inputs/<Skill名> 目录中的外部用例文件（`*.cases.md`）

---

## 工作目录约定

```
inputs_dir   = ~/.claude/skills/SkillSentry/inputs/<被测Skill名>/
workspace 中的产物：
  inputs_dir/rules.cache.json    ← 规则缓存（此工具读取）
  inputs_dir/cases.cache.json    ← 用例缓存（此工具写入）
  <workspace_dir>/evals.json     ← 本次用例设计结果
```

`workspace_dir` 由调用方（SkillSentry 或用户）通过 prompt 上下文传入；单独调用时，
自动创建 `~/.claude/skills/SkillSentry/sessions/<Skill名>/<YYYY-MM-DD>_<NNN>/`。

---

## Step 0：用例缓存检查（最优先）

检查 `inputs_dir/cases.cache.json` 是否存在，且 `rules_hash` 与 `inputs_dir/rules.cache.json` 中的 `skill_hash` 一致：

```
缓存命中 →
  smoke/quick 模式：自动复用，直接输出缓存中的 evals 列表，跳过后续设计
  standard/full 模式：展示摘要，询问「复用上次设计 / 重新设计？」
  告知用户：「⚡ 用例缓存命中（规则未变更），已加载上次设计的 [N] 个用例」

缓存未命中 → 执行 Step 1-5，设计完成后写入 cases.cache.json
```

---

## Step 1：提炼被测 Skill 的规则

若 `inputs_dir/rules.cache.json` 存在：直接加载规则列表，跳过提炼。
否则：读取被测 SKILL.md，提炼所有 P1/P2 规则，写入 `rules.cache.json`：
```json
{ "skill_hash": "<md5>", "extracted_at": "<ISO>", "rules": ["规则1", "规则2", ...] }
```

---

## Step 2：加载外部用例（Golden Set）

扫描 `inputs_dir/` 下的 `*.cases.md` 和 `cases.json`：

**Markdown 解析协议**：
- `#` 一级标题 = 用例名称（`display_name`）
- `> ` 引用块 = 核心指令（`prompt`）
- `- [ ] ` 勾选列表 = 预期断言（`expectations`）

标记为 `source: "external"` 和 `tag: "golden"`，优先级高于 AI 生成。

---

## Step 3：AI 补齐用例（双源合流）

根据模式覆盖率目标，针对外部用例未覆盖的路径，AI 补齐：

| 模式 | 用例数上限 | 覆盖目标 | 每用例运行次数 |
|------|-----------|---------|--------------|
| smoke | 4-5 | ≥20%，核心路径不崩 | 1 |
| quick | 8-10 | ≥40% | 2 |
| standard | 20-25 | ≥70% | 3 |
| full | 30-35 | ≥90% | 3 |

**用例类型分布**（8 类）：
```
happy_path      正常路径（最高优先）
edge_case       边界条件
negative        负向测试（不应触发/执行）
robustness      鲁棒性（异常输入）
atomic          单步原子操作
e2e             端到端完整流程
variant         同类场景不同表述
regression      已知缺陷回归
```

**断言强度分级**（每条断言必须标注 `precision`）：

| 强度 | `precision` 值 | 定义 |
|------|--------------|------|
| 精确断言 | `exact_match` | 有具体可验证的字段值/计数/格式 |
| 语义断言 | `semantic` | 需要语义理解，存在主观空间 |
| 存在性断言 | `existence` | 只验证存在/不存在 |

**断言设计自检**（每条断言写完后过一遍）：
```
□ 没有 Skill 也会通过？→ 是 → precision = existence
□ PASS/FAIL 标准唯一确定？→ 否 → 改写为更具体描述
□ 对应 SKILL.md 的哪条规则？→ 填写 rule_ref 字段
□ 涉及不可逆操作？→ 是 → 检查是否有用户确认步骤断言
```

**⚠️ existence 占比告警**：如果所有断言中 existence 占比 > 50%，告警：
「⚠️ existence 断言占比过高（[X]%），测评有效性存疑，建议升级为 exact_match」

---

## Step 4：HiL 检查（被测 Skill 含不可逆操作时必须执行）

```
HiL-1：不可逆操作前是否有用户确认步骤？→ 无：标注 ⚠️
HiL-2：确认失败/超时时是否有中止逻辑？→ 无：标注 ⚠️
```

---

## Step 5：skip_without_skill 标记

用例设计完成后，对每个用例标记是否跳过 without_skill 执行：

| 条件 | 标记 |
|------|------|
| `type = "negative"` | `skip_without_skill: true` |
| 所有断言 `precision = "existence"` | `skip_without_skill: true` |
| `type = "robustness"` 且核心断言为负向存在性 | `skip_without_skill: true` |

---

## Step 6：写出 evals.json + cases.cache.json

**evals.json 格式**：
```json
[
  {
    "id": 1,
    "display_name": "正常报销流程",
    "type": "happy_path",
    "source": "ai_generated",
    "prompt": "帮我报销一张 168 元的餐饮发票",
    "skip_without_skill": false,
    "expectations": [
      {
        "text": "saveExpenseDoc 调用参数 docStatus=10",
        "precision": "exact_match",
        "rule_ref": "规则3：提交时docStatus必须为10"
      }
    ]
  }
]
```

**cases.cache.json**：
```json
{
  "rules_hash": "<与 rules.cache.json 相同的 hash>",
  "designed_at": "<ISO时间>",
  "mode": "quick",
  "evals": [/* 同 evals.json */]
}
```

---

## 输出

完成后告知用户：
```
✅ 用例设计完成
📋 共设计 [N] 个用例：[类型分布]
🎯 断言构成：exact_match [N] / semantic [N] / existence [N]
⏭️ skip_without_skill: [N] 个用例（节省 ~[X]% 执行时间）
📁 已保存到：<workspace_dir>/evals.json

下一步：
  运行用例 → 使用 sentry-executor 或说「执行这些用例」
  完整流程 → 使用 SkillSentry
```
