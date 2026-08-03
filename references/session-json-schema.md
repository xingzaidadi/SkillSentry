# session.json 结构定义

> 主编排器在各步骤间传递状态的数据结构。
> 执行步骤时按需读取，不需要一次性全部理解。

```json
{
  "skill": "", "mode": "", "skill_type": "", "skill_hash": "", "runtime": "", "mcp_backend": "",
  "started_at": "", "last_step": "",
  "pipeline": [],
  "requirements": {"rules_total": 0, "explicit": 0, "process": 0, "implicit": 0, "high_risk": 0},
  "lint": {"L1": "", "L2": "", "L3": 0, "P0": 0, "P1": 0, "P2": 0, "issues": []},
  "trigger": {"tp": 0, "tn": 0, "confidence": "", "issues": []},
  "cases": {"total": 0, "coverage": "", "types": {}, "assertions_total": 0},
  "executor": {"total_runs": 0, "success": 0, "failed": 0, "spawn_count": 0, "time_minutes": 0},
  "grader_report": {"pass": 0, "fail": 0, "total": 0, "pass_rate": 0, "failed_evals": [], "vetoes": [], "report_html": ""},
  "verdict": {"grade": "", "decision": "", "pass_rate": 0, "completion_status": ""},
  "recommendations": {"P0": [], "P1": [], "P2": []},
  "sync": {"pull": null, "push_cases": null, "push_results": null, "push_run": null},
  "cost": {"static": 0, "cases": 0, "executor": 0, "comparator": 0, "analyzer": 0, "grader_report": 0, "report_regen": 0, "total": 0},
  "milestones": {}
}
```

## 字段说明

### pipeline（v8.1 新增）

Step 2 推断完成后写入，Step 3 调度循环严格按数组顺序执行。

各模式的合法 pipeline（v9.0 当前契约，sync 步骤已纳入）：
- smoke: `["cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"]`
- quick: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"]`
- regression: `["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"]`
- standard: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"]`
- full: `["static", "cases", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"]`

### cost（v8.1 新增）

每步 spawn subagent 前后通过 `session_status` 获取 usage 差值，记录该步骤消耗的 token 数。

### verdict.completion_status（v8.1 新增）

publish 步骤 Completion Gate 检查结果：`"COMPLETE"` | `"PARTIAL"` | `"BLOCKED"`

### evidence（v8.1 新增）

每个 milestone 步骤必须包含 evidence 对象：

```json
{
  "milestones": {
    "step-{name}": {
      "message_id": "om_xxx",
      "sent_at": "ISO8601",
      "evidence": {
        "files_read": ["文件路径列表，证明确实读了"],
        "tools_called": ["MCP/exec 调用列表"],
        "artifacts_created": ["产出文件路径列表"],
        "validation": "验证结果摘要字符串"
      }
    }
  }
}
```

## 存储路径（v8.2.0 变更）

```
CLI:     ~/.claude/data/skill-eval/sessions/<Skill名>/<YYYY-MM-DD>_NNN/session.json
OpenClaw: ~/.openclaw/data/skill-eval/sessions/<Skill名>/<YYYY-MM-DD>_NNN/session.json
```

> v8.1.0 及以前使用 `~/.claude/skills/skill-eval-测评/sessions/`，v8.2.0 起数据/代码分离。

## 写入时机

- Step 1：写基础字段（skill / mode / skill_type / skill_hash / runtime / mcp_backend / started_at）
- Step 2：写 pipeline 数组
- 各步完成后：写对应字段（lint / trigger / cases / executor / grader_report）+ cost[step]
- grader-report 完成：写 verdict / recommendations / report_html
- publish：写 verdict.completion_status + cost.total
- 飞书同步步骤：更新 sync 字段
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\session-json-schema.md` |
| 学习重点 | session-json-schema |
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
