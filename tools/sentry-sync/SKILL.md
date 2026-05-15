---
name: sentry-sync
description: >
  SkillSentry 飞书同步步骤的薄路由。由主 SkillSentry pipeline 自动调用,把 sync-pull、sync-push-cases、sync-push-results 交给 scripts/sentry_sync.py 输出稳定 JSON;通常不需要用户显式触发。
---

# sentry-sync

本工具不再承载 prompt 版同步流程。同步的确定性入口是:

```bash
python scripts/sentry_sync.py sync-pull --skill <Skill名> --session-dir <session_dir>
python scripts/sentry_sync.py sync-push-cases --skill <Skill名> --session-dir <session_dir>
python scripts/sentry_sync.py sync-push-results --session-dir <session_dir>
```

规则:
- `config.json` 缺失时返回 `skipped_no_config`,不中断主流程。
- `config.json` 存在时 wrapper 调用 legacy `scripts/sync_cases.py` 执行真实飞书同步。
- 每个 sync 步骤都必须写入 `session.json.sync.*`,禁止静默跳过。
- 详细字段与飞书表结构见 `../../references/feishu-sync.md`。
