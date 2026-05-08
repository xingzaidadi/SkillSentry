---
name: sentry-sync
description: >
  [已归档] 飞书同步逻辑已内联进 SkillSentry 主文件（v7.0）。
  通常由 SkillSentry 自动调用，不需要用户显式触发。
---

# sentry-sync · 已归档

此工具的飞书同步逻辑已内联进 `SkillSentry/SKILL.md`（v7.0）的「飞书同步」节。

**迁移内容**：
- 操作一 PULL（拉取 active 用例）→ SkillSentry 飞书同步·PULL
- 操作二 PUSH 结果（写入运行记录表）→ SkillSentry 飞书同步·PUSH-RUN
- 操作三 PUSH 新用例（推送 pending_review）→ SkillSentry 飞书同步·PUSH-CASES
- MARK_STALE 逻辑 → SkillSentry 飞书同步·PULL 附带步骤
- 错误处理规则 → 同步失败不中断主流程，记录 skipped_no_config

**config.json 字段参考**（如需手动配置）：
```json
{
  "feishu": {
    "app_id": "cli_xxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxx",
    "app_token": "BascXXXXXXXXXXXX",
    "cases_table_id": "tblXXXXXXXXXXXX",
    "run_history_table_id": "tblXXXXXXXXXXXX"
  }
}
```

*归档于 v7.0 · 2026-04-27*
