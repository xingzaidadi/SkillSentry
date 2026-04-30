# session.json 结构定义

> 主编排器在各步骤间传递状态的数据结构。
> 执行步骤时按需读取，不需要一次性全部理解。

```json
{
  "skill": "", "mode": "", "skill_type": "", "skill_hash": "", "runtime": "", "mcp_backend": "",
  "started_at": "", "last_step": "",
  "requirements": {"rules_total": 0, "explicit": 0, "process": 0, "implicit": 0, "high_risk": 0},
  "lint": {"L1": "", "L2": "", "L3": 0, "P0": 0, "P1": 0, "P2": 0, "issues": []},
  "trigger": {"tp": 0, "tn": 0, "confidence": "", "issues": []},
  "cases": {"total": 0, "coverage": "", "types": {}, "assertions_total": 0},
  "executor": {"total_runs": 0, "success": 0, "failed": 0, "spawn_count": 0, "time_minutes": 0},
  "grader": {"pass": 0, "fail": 0, "total": 0, "pass_rate": 0, "failed_evals": [], "vetoes": []},
  "verdict": {"grade": "", "decision": "", "pass_rate": 0},
  "recommendations": {"P0": [], "P1": [], "P2": []},
  "sync": {"pull": null, "push_cases": null, "push_results": null, "push_run": null},
  "milestones": {}
}
```

## 写入时机

- Step 1：写基础字段（skill / mode / skill_type / skill_hash / runtime / mcp_backend / started_at）
- 各步完成后：写对应字段（lint / trigger / cases / executor / grader）
- grader 完成：写 verdict / recommendations
- 飞书同步步骤：更新 sync 字段
