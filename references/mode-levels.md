# mode-levels.md — 模式分级控制

> sentry-cases / executor / report 根据 mode 参数自动调整流程深度。
> 主调度器在 spawn subagent 时注入 mode 参数。

---

## sentry-cases 流程深度

| 能力 | smoke | quick | standard | full |
|------|:---:|:---:|:---:|:---:|
| 三步扫描 | ❌ 跳过 | ⚡ 用缓存 | ✅ 完整 | ✅ 完整 |
| 测试数据采集 | ⚡ mcp_based查+确认/其他no_data | ⚡ 尝试查 | ✅ 必须查 | ✅ 必须查+用户确认 |
| 用例确认 | ❌ 跳过 | ❌ 跳过 | ✅ 需确认 | ✅ 需确认 |
| security 用例 | ❌ 不含 | ✅ ≥1 | ✅ ≥2 | ✅ ≥3 |
| 飞书 PULL | ⚡ 执行(可降级skipped_no_config) | ⚡ 有就拉 | ✅ 必须 | ✅ 必须 |
| 飞书 PUSH | ⚡ 执行(可降级skipped_no_config) | ⚡ 执行(可降级) | ✅ 必须 | ✅ 必须 |
| history.json | ❌ 不更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 |

---

## executor 执行分级

| 能力 | smoke | quick | standard | full |
|------|:---:|:---:|:---:|:---:|
| with_skill runs | 1 | 2 | 3 | 3 |
| without_skill | ❌ 跳过 | ❌ 跳过(mcp) / ✅(text/code) | ✅ 1 run | ✅ 1 run |
| Delta 计算 | N/A | N/A(mcp) / ✅(text) | ✅ | ✅ |
| 批次大小 | 全部 | 全部 | ∖55/batch | ∖55/batch |

**without_skill 跳过规则**：
- mcp_based + smoke/quick → 跳过，Delta 卡片展示 "N/A(跳过 without_skill，mcp_based 无法在无 Skill 时调用工具)"
- text_generation / code_execution 所有模式 → 默认执行（安全或环境原因跳过时必须说明）
- mcp_based + standard/full → 默认执行可比较的 without_skill 侧；无法裸跑的单个 eval 才逐条跳过，报告标注 partial

---

## 报告产出分级

| 模式 | 产出 |
|------|------|
| smoke | grading-summary.json（本地） |
| quick | grading-summary.json + report.html（本地）+ 飞书卡片推送 |
| standard/full | 三件套（HTML + summary + history）+ HTML 上传飞书 |

---

## auto-exempt 规则

auto 模式跳过的是「步骤间的继续确认」，以下场景即使 auto 也必须阻断：

| 场景 | 原因 | 所在步骤 |
|------|------|----------|
| MCP 预检全不可用 | 无法执行 real_data 用例 | Step 1 |
| real_data 测试数据采集 | 禁止 AI 编造单号/ID | sentry-cases |
| 用例设计审核 | 用户需确认覆盖度 | sentry-cases(standard/full) |
| 写操作/不可逆操作确认 | 安全要求 | 任意步骤 |

---

*v1.0 · 2026-05-02 · 从 SKILL.md 模式分级章节提取*
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\mode-levels.md` |
| 学习重点 | mode-levels |
| 阅读目标 | 看懂这份资料解决什么问题、为什么重要、怎么落地、面试时怎么讲。 |

### 背景、痛点、举措、收益

| 维度 | 内容 |
|---|---|
| 背景 | AI Skill 从个人提示词沉淀走向工程化资产，需要把知识、流程、评测、安全和交付统一管理。 |
| 痛点 | 如果只看原始说明，容易知道“是什么”，但面试时讲不出背景、问题、措施、收益和案例。 |
| 举措 | 围绕该文件主题补齐面试话术、具体案例、背景痛点举措收益、英文专业术语解释和复习抓手。 |
| 收益 | 学习时能快速建立业务语境，面试时能用结构化表达说明为什么做、怎么做、带来什么价值。 |

### 面试话术怎么回答

> 这份材料我会按“背景—痛点—举措—收益”来讲：背景是 Agent 能力需要被资产化和评测；痛点是执行不稳定、触发不准、安全边界不清；举措是用 Skill 固化流程，用指标和 CI gate 做验证；收益是让能力可复用、可比较、可回归。

### 具体案例是什么

以 SkillSentry 为例：先读取 Skill 或评测材料，再构造样本执行 Agent，最后用评分器和报告判断质量是否达标。

### 专业术语解释

| 中文术语 | 英文术语 | 专业解释 | 白话解释 |
|---|---|---|---|
| Skill | Skill | 面向 Agent 的结构化任务说明、流程和约束包。 | 给 AI 的专业说明书。 |
| Agent | Agent | 能围绕目标规划步骤、调用工具并交付结果的 AI 系统。 | 会自己安排步骤做事的 AI。 |
| Evaluation | Evaluation | 用样本、指标和评分规则系统衡量效果。 | 统一考试和打分。 |

### 复习抓手

1. 先用一句话说清这个文件的主题。
2. 再用“背景—痛点—举措—收益”解释它为什么重要。
3. 最后补一个 SkillSentry 或业务场景案例，证明你不是只背概念。
