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

## Step 0：需求分析（用户确认测什么）

> **跳过条件**：prompt 中含 `--skip-analysis` 时，直接进入 Step 1。

### 0.1 加载或生成需求分析

检查 `inputs_dir/requirements.cache.json` 是否存在且 `skill_hash` 匹配：

```
命中 → 直接加载，跳过三步扫描（规则没变，分析结果有效）
未命中 → 读取被测 SKILL.md，执行三步扫描，写入 requirements.cache.json
```

**三步扫描**：

| 步骤 | 扫描方式 | 找什么 |
|------|---------|--------|
| 语义扫描 | 找「如果…则…」「必须」「禁止」「固定为」 | 显性规则 |
| 角色流扫描 | 梳理完整执行序列，每步问「这里可能失败吗？」 | 流程规则 |
| 负向空间推演 | 找「没明说但显然不该有」的行为 | 隐性规则 ⚠️ |

**requirements.cache.json 结构**：
```json
{
  "skill_hash": "<md5>",
  "analyzed_at": "<ISO>",
  "rules": {
    "explicit":  [{"ref": "R-01", "description": "...", "risk": "high/medium/low"}],
    "process":   [{"ref": "F-01", "description": "..."}],
    "implicit":  [{"ref": "I-01", "description": "...", "risk": "high"}]
  },
  "extra_rules": [],
  "test_plan": {
    "mode": "<当前模式>",
    "coverage_target": "≥70%",
    "estimated_cases": 22,
    "focus_areas": ["R-07", "I-01"]
  }
}
```

### 0.2 展示需求分析结果（必须等用户确认）

```
📋 需求分析 · <Skill名>

发现规则 [N] 条：

显性规则（[N]条）—— 规范里明确写出来的
  R-01  saveExpenseDoc 入参 docStatus 必须为 '10'（草稿）         [高风险]
  R-05  金额 ≥ 5000 触发大额警告                                  [中风险]
  R-07  saveExpenseDoc 成功后禁止再次调用                         [高风险]
  ...

流程规则（[N]条）—— 从执行路径推导出来的
  F-01  发票识别失败时必须降级追问用户                             [中风险]
  ...

隐性规则（[N]条）—— 规范没写，但显然不该有的行为 ⚠️ 最易漏测
  I-01  未经用户确认不得直接提交审批                              [高风险]
  ...

测试计划：<mode> 模式，目标覆盖 ≥[X]%，预计 [N] 个用例
重点关注：[高风险规则列表]

有遗漏的业务场景，或需要补充的规则吗？
→ 没有，开始生成用例
→ 补充：________
```

### 0.3 处理用户补充

用户有补充 → 将补充内容以自然语言追加到 `extra_rules`，作为 Step 3 AI 补齐的额外输入。
用户无补充（或 30 秒无响应）→ 直接进入 Step 1。

---

## Step 1：用例缓存检查

各模式所需最少用例数：smoke=4，quick=8，standard=20，full=30。

检查 `inputs_dir/cases.cache.json` 是否存在，且 `rules_hash` 与 `inputs_dir/rules.cache.json` 中的 `skill_hash` 一致：

```
缓存未命中（文件不存在 或 hash 不一致）
  → 执行 Step 2-6，设计完成后写入 cases.cache.json

缓存命中 + 缓存用例数 < 当前模式所需最少数（如缓存 smoke=4 个，当前需 quick=8 个）
  → 用例不足，缓存视为未命中，重新设计

缓存命中 + 缓存用例数 ≥ 当前模式所需最少数
  缓存 mode == 当前 mode：全量复用，跳过 Step 2-6
  缓存 mode 级别 > 当前 mode（如 quick 缓存用于 smoke）：
    按 happy_path > e2e > edge_case 优先级取前 N 个（N = 当前模式上限）
    标注「⚡ 从 [缓存mode] 用例中取子集（[N]/[总数]），规则未变更」
  smoke/quick：自动复用，跳过 Step 2-6
  standard/full：展示摘要，询问「复用上次设计 / 重新设计？」
```

---

## Step 2：提炼被测 Skill 的规则

若 `inputs_dir/rules.cache.json` 存在：直接加载规则列表，跳过提炼。
否则：读取被测 SKILL.md，提炼所有 P1/P2 规则，写入 `rules.cache.json`：
```json
{ "skill_hash": "<md5>", "extracted_at": "<ISO>", "rules": ["规则1", "规则2", ...] }
```

> `requirements.cache.json`（Step 0 产物）与 `rules.cache.json` 并存：前者是分类后供用户确认的完整需求视图，后者是 AI 补齐用例时使用的规则列表，两者来源相同但用途不同。

---

## Step 3：加载外部用例（Golden Set）

扫描 `inputs_dir/` 下的 `*.cases.md` 和 `cases.json`：

**Markdown 解析协议**：
- `#` 一级标题 = 用例名称（`display_name`）
- `> ` 引用块 = 核心指令（`prompt`）
- `- [ ] ` 勾选列表 = 预期断言（`expectations`）

标记为 `source: "external"` 和 `tag: "golden"`，优先级高于 AI 生成。

---

## Step 4：AI 补齐用例（双源合流）

根据模式覆盖率目标，针对外部用例未覆盖的路径，AI 补齐。
输入来源：`rules.cache.json` 规则列表 + `requirements.cache.json` 中的 `extra_rules`（用户在 Step 0 补充的业务场景）。

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

## Step 5：HiL 检查（被测 Skill 含不可逆操作时必须执行）

```
HiL-1：不可逆操作前是否有用户确认步骤？→ 无：标注 ⚠️
HiL-2：确认失败/超时时是否有中止逻辑？→ 无：标注 ⚠️
```

---

## Step 6：skip_without_skill 标记

用例设计完成后，对每个用例标记是否跳过 without_skill 执行：

| 条件 | 标记 | 原因 |
|------|------|------|
| `skill_type = "mcp_based"` AND `mode ∈ {smoke, quick}` | **全部用例** `skip_without_skill: true` | mcp_based 模型无 Skill 指导时几乎必然调错工具，Δ 总为正，without_skill 无增量价值；standard/full 模式仍正常双侧以获取精确 Δ 数据 |
| `type = "negative"` | `skip_without_skill: true` | 负向测试，without_skill 无对比价值 |
| 所有断言 `precision = "existence"` | `skip_without_skill: true` | existence 断言对有无 Skill 不敏感 |
| `type = "robustness"` 且核心断言为负向存在性 | `skip_without_skill: true` | 鲁棒性用例，without_skill 行为已知（混乱） |

> **覆盖优先级**：mcp_based + smoke/quick 规则优先级最高，命中后直接标记，不再逐条判断。

---

## Step 7：写出 evals.json + cases.cache.json

**evals.json**：对象数组，每条用例含 `id`、`display_name`、`type`、`source`、`prompt`、`skip_without_skill`、`expectations[]{text, precision, rule_ref}`。

**cases.cache.json**：`{ "rules_hash", "designed_at", "mode", "evals": [...同 evals.json...] }`

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
