# Gate Policy

`scripts/sentry_gate.py` 默认读取 `config/gate-policy.default.json`。如果某次 session 需要更严格或更宽松的门禁，可以在 session 目录放置 `gate-policy.json` 覆盖默认策略。

## 读取优先级

1. 代码内置默认值。
2. 仓库级 `config/gate-policy.default.json`。
3. Session 级 `gate-policy.json`。

`gate-result.json` 会包含 `gate_policy.source` 和 `gate_policy.policy`，用于审计最终生效配置。

## 可配置项

- `methodology.route.block_statuses`: V2 route 状态命中后直接阻断发布。
- `methodology.route.warn_statuses`: V2 route 状态命中后把 `PASS` 降为 `CONDITIONAL PASS`。
- `methodology.apply_without_route_cases`: 是否在没有 route case 时仍让污染、工具参数、benchmark 等 V2 信号影响 gate；默认 `false` 以兼容旧用例。
- `methodology.contamination.warn_min`: 污染风险达到该数量后给出条件通过提醒。
- `methodology.contamination.block_min`: 污染风险达到该数量后阻断发布。
- `methodology.calibration.*`: grader 校准的 agreement、severe miss、evidence coverage 阈值。
- `methodology.benchmark.coverage_warn_min`: benchmark adapter 覆盖率提醒阈值。
- `methodology.tool_assertions.pass_rate_warn_min`: 工具名/参数断言通过率提醒阈值。
- `methodology.tool_assertions.block_failed_p0`: 是否将 P0 工具断言失败升级为阻断。
- `token.budget_total_max` / `token.budget_per_case_max`: 预留 token 预算门禁字段。

## Session 覆盖示例

```json
{
  "methodology": {
    "apply_without_route_cases": true,
    "route": {
      "block_statuses": ["warn_low_confidence", "block", "block_no_route_precision"]
    },
    "tool_assertions": {
      "block_failed_p0": true
    }
  }
}
```
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | Skill 测评方法论与质量门禁 |
| 当前文件 | `SkillSentry_repo\references\gate-policy.md` |
| 学习重点 | gate-policy |
| 阅读目标 | 看懂这份资料解决什么问题、为什么重要、怎么落地、面试时怎么讲。 |

### 背景、痛点、举措、收益

| 维度 | 内容 |
|---|---|
| 背景 | Skill 上线前需要证明它在目标任务上稳定、准确、安全、可回归。 |
| 痛点 | 只看几个演示样例无法发现漏触发、误触发、格式漂移、安全违规和版本退化。 |
| 举措 | 构建 golden set、回归集、红队集，结合规则评分、LLM-as-judge、人工抽检和 CI gate。 |
| 收益 | 把主观“感觉好用”变成可量化、可解释、可阻断发布的质量体系。 |

### 面试话术怎么回答

> Skill 测评要分层看：先看该不该触发，再看执行过程是否遵守 workflow，然后看输出质量和格式，最后看安全、稳定性和成本，并把阈值放进 CI gate。

### 具体案例是什么

SkillSentry 对报销 Skill 跑 100 条样本，统计触发率、任务成功率、格式合规率、安全违规率，并输出失败根因。

### 专业术语解释

| 中文术语 | 英文术语 | 专业解释 | 白话解释 |
|---|---|---|---|
| Benchmark | Benchmark | 用于比较能力的标准化测试集或流程。 | 统一考卷。 |
| Rubric | Rubric | 描述评分维度和分值标准的规则。 | 打分细则。 |
| CI Gate | CI Gate | 持续集成中的质量门禁，未达标则阻断发布。 | 自动质量红线。 |

### 复习抓手

1. 先用一句话说清这个文件的主题。
2. 再用“背景—痛点—举措—收益”解释它为什么重要。
3. 最后补一个 SkillSentry 或业务场景案例，证明你不是只背概念。
