# references 目录总览

> 这里放的是 SkillSentry 的当前口径、测评规则、报告模板、平台约定和少量历史参考。
> 如果你只想先找“现在应该看什么”，按下面顺序读就够了。

---

## 1. 先读哪些

- `current-contract.md`：当前稳定口径，优先级最高
- `step-contracts.md`：每一步的输入、输出、准出约定
- `session-json-schema.md`：session 结构和字段含义
- `execution-phases.md`：执行流程和阶段边界
- `runtime-router-guide.md`：运行时路由、OpenClaw/本地执行规则
- `mode-levels.md`：quick / standard / full 等模式定义

---

## 2. 测评怎么设计

- `eval-dimensions.md`：9 层测评维度
- `admission-criteria.md`：准入阈值和发布门槛
- `case-matrix-templates.md`：用例设计模板
- `security-v1-case-matrix.md`：安全增强 V1 的用例家族、风险等级和门禁映射
- `custom-cases-template.md`：自定义用例填写模板
- `report-template.md`：HTML 报告模板
- `output-format.md`：输出格式约定

---

## 3. 平台与交互

- `ci-guide.md`：CI 使用与流程说明
- `feishu-sync.md`：飞书同步机制
- `feishu-templates.md`：飞书消息模板
- `card-templates.md`：交互卡片模板

---

## 4. 问题处理与复盘

- `faq.md`：常见问题答复
- `pitfall-guide.md`：踩坑与设计模式应用
- `tool-as-code-refactor-pitfalls-2026-05-19.md`：Tool-as-Code 重构坑位复盘

---

## 5. 历史归档

这部分只作参考，不作为当前口径。

- `archive/eval-dimensions-full.md`
- `archive/skill-creator-capability-notes.md`

---

## 6. 阅读建议

- 想改主流程：先看 `current-contract.md` 和 `step-contracts.md`
- 想改测评指标：先看 `eval-dimensions.md` 和 `admission-criteria.md`
- 想改报告：先看 `report-template.md`
- 想查旧材料：再进 `archive/`
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\README.md` |
| 学习重点 | README |
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
