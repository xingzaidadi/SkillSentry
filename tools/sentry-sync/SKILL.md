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
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | SkillSentry 工程执行组件 |
| 当前文件 | `SkillSentry_repo\tools\sentry-sync\SKILL.md` |
| 学习重点 | SKILL |
| 阅读目标 | 看懂这份资料解决什么问题、为什么重要、怎么落地、面试时怎么讲。 |

### 背景、痛点、举措、收益

| 维度 | 内容 |
|---|---|
| 背景 | SkillSentry 需要把分析、执行、比较、评分、报告和同步拆成可维护组件。 |
| 痛点 | 如果所有逻辑混在一起，难以定位失败、复用组件、扩展平台或设置门禁。 |
| 举措 | 按组件职责拆分输入、处理、输出和失败处理，并用契约文档约束交互。 |
| 收益 | 工程链路更清晰，便于调试、扩展、自动化和团队协作。 |

### 面试话术怎么回答

> SkillSentry 的工程设计核心是职责拆分：执行组件产生日志和结果，评分组件给出结构化判断，报告组件服务决策，比较组件用于回归和横评。

### 具体案例是什么

executor 负责跑样本，grader 负责按 rubric 打分，report 负责把结果转成可读报告，comparator 负责跨版本或跨 Agent 对比。

### 专业术语解释

| 中文术语 | 英文术语 | 专业解释 | 白话解释 |
|---|---|---|---|
| Executor | Executor | 负责运行评测任务并采集结果的组件。 | 执行器。 |
| Grader | Grader | 根据规则或模型判断输出质量的评分组件。 | 评分器。 |
| Comparator | Comparator | 比较不同版本、平台或运行结果差异的组件。 | 对比器。 |

### 复习抓手

1. 先用一句话说清这个文件的主题。
2. 再用“背景—痛点—举措—收益”解释它为什么重要。
3. 最后补一个 SkillSentry 或业务场景案例，证明你不是只背概念。
