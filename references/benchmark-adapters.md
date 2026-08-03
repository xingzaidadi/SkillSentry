# Benchmark Adapter Mapping

`scripts/sentry_methodology_v2.py` 不直接复刻外部 benchmark，而是把 SkillSentry case 字段映射到可解释的 adapter 家族，方便衡量用例集是否覆盖工具调用、安全、多轮状态、真实任务和长时程任务。

## 字段映射

- `openai_evals_style`: `assertions`、`expected_output`、`expected_answer`。
- `bfcl_style`: `tool_call_assertions`、`expected_tool_args`、`tool_chain_expected`，或 prompt 中存在工具/参数语义。
- `toolbench_style`: `tool_chain_expected`、`tool_sequence_expected`、`tool_sequence_score`。
- `agentbench_style`: `environment`、`task_completion_score`。
- `gaia_style`: `real_world_task`，或 `dimension=real_world/e2e`。
- `tau_bench_style`: `user_simulation_profile`、`state_goal`、`turns`、`messages`。
- `metr_style`: `time_horizon_bucket`、`checkpoint_required`。
- `agentdojo_style`: `security_family`，或 `dimension=security`。
- `owasp_llm_top10`: `security_family`，或 `dimension=security`。

## 内置样本

首批样本在 `benchmarks/v2/evals.json`，覆盖 BFCL、AgentDojo/OWASP、GAIA、τ-bench、METR 和 AgentBench 风格字段。可用下面命令验证映射：

```powershell
python scripts/sentry_methodology_v2.py benchmarks/v2 --format json --output benchmarks/v2/methodology-result.json
```

运行后应看到 `benchmark_adapters.adapter_counts`、`tool_assertion_score`、`sampling_plan` 和 `sampling_result`。
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | Skill 测评方法论与质量门禁 |
| 当前文件 | `SkillSentry_repo\references\benchmark-adapters.md` |
| 学习重点 | benchmark-adapters |
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
