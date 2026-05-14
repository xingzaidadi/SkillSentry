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
