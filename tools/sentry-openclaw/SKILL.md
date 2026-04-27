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
