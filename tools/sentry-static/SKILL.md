---
name: sentry-static
description: >
  对 AI Skill 做静态质量检查和触发率模拟评估（三合一：Lint + Trigger + 汇总）。
  触发场景：说"检查这个skill的结构"、"lint"、"检查HiL"、"分析复杂度"、
  "帮我看看这个skill写得好不好"、"发布前做结构检查"、"有没有安全风险"、
  "测试触发率"、"description写得好不好"、"这个skill触发准不准"、"会不会误触发"。
  不触发场景：要运行测试用例、要做完整测评流程（用 SkillSentry）。
---

# sentry-static · 静态检查 + 触发率评估（v8.0 三合一）

> 原 sentry-check / sentry-lint / sentry-trigger 合并而来（v8.0）。

## 执行模式参数

| 参数 | 效果 |
|------|------|
| `--lint-only` | 只执行 Sub-step 1（静态规则检查），跳过触发率 |
| `--trigger-only` | 只执行 Sub-step 2（Trigger TP/TN），跳过静态检查 |
| 无参数（默认） | 执行全部 3 个子步骤：Lint → Trigger → 汇总 |

**CI/研发自检用法**：`lint xxx --lint-only` 或 `测触发率 --trigger-only`

## 三子步骤架构

```
Sub-step 1: Static rules        → 独立输出静态规则检查报告
Sub-step 2: Trigger (TP/TN)     → 独立输出触发率报告
Sub-step 3: Summary             → 汇总两项结果 + 发布建议
```

每个子步骤完成后**立即输出**该步骤的结果（不是最后一起吐），便于 CI 流水线逐步消费。

## Required Reads (must_read)

执行前必须读取以下文件，不读不得开始：
1. 被测 SKILL.md 全文

未读取上述文件时，输出 BLOCKED 并说明缺少什么。

两项分析合一：静态规则检查（约 30 秒）+ AI 模拟触发测试（TP/TN，约 2 分钟）。

**调用方式**：
- `lint xxx` / `检查结构` / `--lint-only` → 只跑 Sub-step 1（静态检查）
- `测触发率` / `description 准不准` / `--trigger-only` → 只跑 Sub-step 2（触发率）
- `check xxx` / `static xxx` / 流水线中 → 三步全跑

---

## 输入

优先级：
1. 用户提供路径 → 直接使用
2. 用户只说名字 → 按顺序查找：`~/.openclaw/skills/<名字>/` → `~/.claude/skills/<名字>/`
3. 「检查这个 skill」→ 当前工作目录下的 SKILL.md

---

## Sub-step 1：静态规则检查

对目标 SKILL.md 做零执行的静态分析，约 30 秒完成。

### 规则组 1：description 字段完整性

读取 frontmatter 中的 `description` 字段，逐项检查：

```
□ description 存在且非空
□ 包含「触发场景」描述
□ 包含「不触发场景」描述
□ 描述中有具体业务动词（如「报销」「创建单据」），而非泛化描述（如「帮助用户」）
□ 描述总长度 ≥ 50 字
```

每项标注 ✅ / ⚠️ / ❌，并给出具体理由。

### 规则组 2：Human-in-the-Loop（HiL）节点检查

扫描全文，查找不可逆操作关键词：

```
通用：提交、删除、创建、写入、发送、上传、支付、更新、修改、
      save、submit、delete、create、write、send、update、publish

mcp_based 额外扫描工具名（camelCase/snake_case）中含：
  save* / delete* / submit* / update* / create* / publish* / send* / upload*
  → 不可逆操作，须有 HiL 确认
```

对每个不可逆操作检查：
- HiL-1：操作前是否有用户确认步骤？→ 无：❌ 「缺少 HiL 确认节点」
- HiL-2：用户拒绝时是否有中止逻辑？→ 无：⚠️ 「确认节点无拒绝处理」

### 规则组 3：复杂度评分

```
复杂度得分 = (行数/50) + (## 章节数 × 2) + (硬性规则数 × 0.5)
硬性规则数：统计含「必须」「禁止」「不得」「must」「shall not」的行数
```

| 指标 | 数值 | 评级 |
|------|------|------|
| 总行数 | N | 正常/偏多/过多 |
| 二级标题数 | N | — |
| 硬性规则数 | N | — |
| 复杂度得分 | N | ✅ <10 / ⚠️ 10-20 / ❌ >20 建议重构 |

### 规则组 4：冗余规则自检

对每条含「必须」「禁止」「需要」的规则，问：
> 「如果删掉这条，真实对话中会出现什么具体问题？」

- 模型本来就会这样做 → ⚠️ 冗余候选
- 有具体业务场景特殊性 → ✅ 保留必要
- 重复了其他规则的意思 → ⚠️ 冗余候选

输出候选列表（仅供人工复核，不自动删除）。

### 规则组 5：规则可测试性

对每条硬性规则：
- 可测试：有具体输入/输出/工具调用可验证 ✅
- 模糊难测：含「尽量」「尽可能」「适当」等主观表述 ⚠️
- 不可测：只描述意图无行为 ❌

### Sub-step 1 输出格式

```
━━━ Sub-step 1: Static rules ━━━
总览：检查项 5 类 | ✅ 通过 N | ⚠️ 建议改进 N | ❌ 需要修复 N

规则组 1 description 完整性：[逐项]
规则组 2 HiL 节点：[检查结果]
规则组 3 复杂度：[表格]
规则组 4 冗余规则候选：[列表 或「未发现」]
规则组 5 可测试性：[列表]

改进优先级：P0（必须修复）/ P1（建议修复）
━━━ Sub-step 1 完成 ━━━
```

`--lint-only` 模式到此结束，输出读取证明后退出。

---

## Sub-step 2：Trigger 触发率模拟（TP/TN）

对目标 Skill 的 `description` 做 AI 模拟触发测试，约 2 分钟完成。

### Step 1：提取 description 语义

识别触发意图、不触发意图、边界场景。

### Step 2：生成 10 条测试 prompt

| 类型 | 数量 | 要求 |
|------|------|------|
| TP（应触发）| 5 条 | 覆盖 description 中不同触发表述 |
| TN（不应触发）| 3 条 | 相关但不符合触发条件的近似场景 |
| 边界（uncertain）| 2 条 | 在触发边界上模糊的场景 |

### Step 3：AI 自评

对每条 prompt，以「不知道有哪些 Skill 可用」的模型视角判断：

```
给定 description：[内容]
用户说：「[prompt]」
此 description 是否会激活该 Skill？
打分：0（不触发）/ 0.5（不确定）/ 1（触发）
理由：[1-2 句]
```

### Step 4：汇总

```
TP 触发率 = TP 中打分 ≥ 0.7 的条数 / 5
TN 不触发率 = TN 中打分 ≤ 0.3 的条数 / 3
置信度：high（无 0.5）/ medium（1-2 条不确定）/ low（≥3 条不确定）
```

写入 `inputs/<Skill名>/trigger_eval.json`。

**发布阈值参考**：TP ≥ 80% 正常上线；70-80% 优化后重测；< 70% 暂缓发布。

### Sub-step 2 输出格式

```
━━━ Sub-step 2: Trigger (TP/TN) ━━━
TP 触发率：[X]%（[N]/5）
TN 不触发率：[X]%（[N]/3）
边界：[N] 条 uncertain | 置信度：[high/medium/low]

[每条 prompt 详情表格]

结论：[达标/需优化] + [具体建议]
━━━ Sub-step 2 完成 ━━━
```

`--trigger-only` 模式到此结束，输出读取证明后退出。

---

## Sub-step 3：汇总报告

综合 Sub-step 1 和 Sub-step 2 的结果，输出最终报告。

### Sub-step 3 输出格式

```
━━━ Sub-step 3: Summary ━━━

## sentry-static 报告：<Skill名称>

### Part 1 · 静态检查 (Lint)
[引用 Sub-step 1 结果摘要]

### Part 2 · 触发率评估 (Trigger)
[引用 Sub-step 2 结果摘要]

### 综合评估
- 静态质量：[通过/需改进/需重构]
- 触发精度：[达标/需优化/暂缓]
- 发布建议：[可发布/条件发布/暂缓发布]
- P0 改进项：[列表]

━━━ Sub-step 3 完成 ━━━
```

---

## 准则

- 静态分析，不运行任何 MCP 工具或 subagent
- 所有判断引用 SKILL.md 原文，标注行号
- ⚠️ 是建议，❌ 是必须修复，区别对待
- 不主动修改 SKILL.md，只输出报告
- 10 条 trigger prompt 必须全部生成和评估，不得减少

---

## 读取证明（主编排器校验用）

输出的最后一行必须包含以下格式的校验标记：

```
[sentry-proof] skill=sentry-static steps=<本次执行的步骤数> ts=<ISO时间>
```

主编排器通过检查此标记确认子工具确实读取并执行了 SKILL.md，而非凭记忆发挥。
缺少此标记 → 主编排器判定为「未按 SKILL.md 执行」，要求重跑。
