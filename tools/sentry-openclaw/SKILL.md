---
name: sentry-openclaw
description: >
  [已归档] 此工具已并入 SkillSentry 主文件（v7.0）。请直接使用 SkillSentry。
  触发场景：同 SkillSentry。
---

# sentry-openclaw · 已归档

此工具（v6.4 及以前）的所有功能已合并进 `SkillSentry/SKILL.md`（v7.0）。

**迁移内容**：
- 飞书卡片推送（msg_type=interactive）→ SkillSentry 平台适配层
- validate_step.py + milestone audit → SkillSentry 平台适配层
- PUSH-CASES / PUSH-RESULTS / PUSH-RUN 内联逻辑 → SkillSentry 飞书同步节
- 动态 Skill 扫描卡片 → SkillSentry Step 2（OpenClaw 路径）
- session.json 完整 schema → SkillSentry session.json 结构节

**使用方式**：直接触发 `SkillSentry`，平台（CLI / OpenClaw）会自动检测。

*归档于 v7.0 · 2026-04-27*
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\tools\sentry-openclaw\SKILL.md` |
| 学习重点 | SKILL |
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
