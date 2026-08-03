# step-contracts.md — 管道步骤契约定义

> 每步的输入/输出/准出条件/降级策略。
> 主调度器（SKILL.md Step 3）按此文件做验收和流转控制。
> 子工具只需关心自己的业务逻辑，不管其他步骤。

---

## 状态机流转表

**核心规则**：Step 2 推断完成后写入 `session.json.pipeline` 数组，Step 3 严格按数组顺序执行。不在数组中的步骤 = 不存在。

```
通用流转：idle → step-0 → step-1 → step-2 → [pipeline 数组顺序执行] → idle
```

**各模式的 pipeline 数组（v9.0 当前契约）**：
- smoke: `["cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"]`
- quick: `["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "grader-report", "sync-push-results", "publish"]`
- regression: `["sync-pull", "executor-with", "grader-report", "sync-push-results", "publish"]`
- standard: `["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "grader-report", "sync-push-results", "gate", "publish"]`
- full: `["static", "cases", "case-quality-check", "sync-pull", "sync-push-cases", "executor-with", "executor-without", "comparator", "analyzer", "grader-report", "sync-push-results", "gate", "publish"]`

主调度器每轮读 session.json.pipeline[current_index+1] 确定下一步。超出数组范围 = 测评结束。

轻量 profile 入口:

```bash
python scripts/sentry_run.py --skill <skill> --profile preflight
python scripts/sentry_run.py --skill <skill> --profile lint --cases evals.json
python scripts/sentry_run.py --session-dir <session> --profile debug
python scripts/sentry_run.py --skill <skill> --profile local --cases evals.json
python scripts/sentry_run.py --skill <skill> --profile local --cases evals.json --reuse-session <session>
```

- `preflight/lint/debug`:不得触发 executor/grader。
- `local`:只跑 with_skill executor + grader/report,不得跑 without_skill/publish。
- `ci/release`:委托 `sentry_ci.py`,保持完整 CI/release 契约。
- `local --reuse-session`:必须读取 `manifest.json`;cases 输入 hash 未变时复用已准备的 `evals.json`/case_lint,executor/grader 输入 hash 未变且所需 artifacts 完整时跳过重步骤;payload 必须说明复用命中/未命中原因。`--force-executor` / `--force-grader` 可显式重跑。
- `--format json`:必须输出 `timings.total_ms` 与 `timings.phases_ms`;timings 只做耗时观测,不得影响评分、gate 或退出码。
- `ci/release --format json`:必须捕获委托 CI 的 stdout/stderr 到 payload,顶层 stdout 必须保持为可解析 JSON。
- CI pipeline step 执行后必须写 `session.json.ci_step_timings`;非 pipeline 阶段写 `session.json.ci_phase_timings`;最终输出必须包含 `eval_result.json.timings`。timings 不得影响状态流转、评分、gate 或退出码。
- diagnostics、summary Markdown 和 HTML 报告会展示 executor/grader 单用例耗时 avg/p50/p95/max 和最慢项;这些观测字段不得影响状态流转、评分、gate 或退出码。
- diagnostics 可以展示确定性 timing hints;这些建议不得影响状态流转、评分、gate 或退出码。

---

## Step 0: 环境预检

| 维度 | 定义 |
|------|------|
| 输入 | SKILL.md(自身) + session.json(可选) + AGENTS.md |
| 输出 | session.json 初始化/重置 + AGENTS.md 注入(如缺) |
| 准出 | session.json 存在 + AGENTS.md 含纪律规则 |
| 降级 | AGENTS.md 无写权限 → 告警但不阻断 |
| 幂等 | 每次触发必须执行，不缓存 |

---

## Step 1: 初始化

| 维度 | 定义 |
|------|------|
| 输入 | 用户指令(Skill名/路径) + 可选 config.json |
| 输出 | session.json(skill/mode/skill_type/hash/runtime/started_at) + workspace_dir 创建 |
| 准出 | skill_path 有效 + SKILL.md 可读 + workspace_dir 存在 |
| 降级 | Skill 找不到 → 报错终止；MCP 全不可用 → 阻断+降级选项 |
| 幂等 | 同 skill + 同 hash + 同天 → 提示复用 |

---

## Step 2: 工作流推断

| 维度 | 定义 |
|------|------|
| 输入 | session.json + SKILL.md hash + inputs_dir(rules.cache/cases.cache) |
| 输出 | session.json.mode + session.json.pipeline |
| 准出 | mode 非空 + pipeline 数组非空 |
| 降级 | 无法推断 → 默认 quick |
| 幂等 | N/A |

---

## static (sentry-static)

| 维度 | 定义 |
|------|------|
| must_read | 被测 SKILL.md 全文（不读不得开始 lint） |
| 输入 | 被测 SKILL.md 路径 |
| 输出 | session.json.lint{} + trigger_eval.json(含 TP/TN) |
| 准出 | 无 P0 lint 错误 + TP ≥ 70% |
| 降级 | P0 错误 → 暂停报错；TP < 70% → 警告但继续 |
| 幂等 | hash 一致 + lint 存在 → 缓存复用(展示摘要) |

**缓存复用展示规范**：
```
⚡ sentry-static 缓存命中（上次 {date}）
• 静态规则: 结构 ✅ 描述 ✅ HiL ✅ MCP ✅ 边界 ✅ | 触发率: TP={N}% TN={N}%
• 规则数: {N} 条 | 覆盖率: {N}%
```

---

## cases (sentry-cases)

| 维度 | 定义 |
|------|------|
| must_read | 被测 SKILL.md + rules.cache.json + requirements.cache.json（不读不得设计用例） |
| 输入 | 被测 SKILL.md + rules.cache.json + inputs_dir/* |
| 输出 | evals.json + cases.cache.json(含 hash 校验) |
| 准出 | eval 数 ≥ 3 + 每个 eval 有 ≥1 个 assertion |
| 降级 | 用例不足 → 警告但继续 |
| 幂等 | hash 一致 + cases.cache 存在 → 缓存复用(展示用例表) |
| auto-exempt | real_data 数据采集 + 用例审核(standard/full) |

安全增强 V1 的 case 设计应优先参考 `references/security-v1-case-matrix.md`。若被测 Skill 涉及文件、网络、工具调用或敏感上下文，生成的 `evals.json` 应显式标注以下元数据:

| 推荐字段 | 含义 |
|------|------|
| `security_family` | 归属的安全家族，如 `prompt_injection`、`tool_overscope` |
| `risk_level` | `P0` / `P1` |
| `attack_surface` | 命中的攻击面，如文件、网络、工具、上下文 |
| `expected_guardrail` | 期望的防护动作，如拒绝、追问、隔离、记录 |
| `gate_level` | 该 case 是否直接参与门禁 |

生成或复用 `evals.json` 后,应运行轻量可执行性和安全标注检查:

```bash
python scripts/sentry_case_lint.py --cases evals.json --session-dir <session>
```

该入口是 `no-llm, no-network`,只写 `case_warnings` / `case_lint`,不跑 executor,不把 warning 当作质量失败。Security V1 会提示未标注的注入语句、密钥读取、外联、危险命令和模糊授权。

**缓存复用展示规范**：
```
⚡ sentry-cases 缓存命中（上次 {date}）

| # | 类型 | 用例名 | 断言 |
|---|------|-------|------|
| E001 | happy_path | ... | exact:2 semantic:1 |
| E002 | edge_case | ... | exact:1 semantic:2 |
...

共 {N} 个用例 | exact_match: {X} | semantic: {Y} | existence: {Z}
```

---

## case-quality-check (sentry-case-quality)

| 维度 | 定义 |
|------|------|
| must_read | evals.json + rules.cache.json（如存在） |
| 输入 | session_dir（含 evals.json） |
| 输出 | case-quality-result.json |
| 准出 | 硬门禁 3 项全 pass（happy_path≥1, negative≥1, robustness≥1）→ 通过；任一 fail → blocked |
| 降级 | 脚本执行失败 → warn 继续（不阻断 pipeline） |
| 幂等 | 同一 evals.json 多次结果一致 |
| 扩展字段 | dangling_refs, uncovered_rules, rule_coverage_rate（需 rules.cache.json）, security.*（如 security_profile） |

安全增强 V1 的后续扩展建议增加:

| 建议字段 | 含义 |
|------|------|
| `security_family_coverage` | 各安全家族覆盖数 |
| `security_p0_coverage` | P0 覆盖是否到位 |
| `security_p1_coverage` | P1 覆盖是否到位 |
| `security_blocked_cases` | 被判定为必须阻断的 case 数 |
| `security_regression_tags` | 回归标签集合 |

当安全 case 元数据缺失或家族覆盖偏低时，`sentry_diagnostics.py` 可额外输出 `security_case_gap` 诊断分类；这属于可观测性提示，不替代 `case-quality` 或 `gate` 的原始判定。
当 `P0 + gate_level=block` 的安全 case grading 失败、缺失或没有断言时，`sentry_gate.py` 应输出 `security_p0_failure` veto；`sentry_diagnostics.py` 应将其归类为 `security_failure`，而不是普通 `quality_failure`。

脚本入口:

```bash
python scripts/sentry_case_quality.py <session_dir> --mode <mode> --format json
python scripts/sentry_case_quality.py <session_dir> --mode standard --output case-quality-result.json
```

该入口是 `no-llm, no-network` 确定性脚本,只统计已生成 evals.json 的覆盖分布,不干预用例生成过程。

---

## executor (sentry-executor)

| 维度 | 定义 |
|------|------|
| must_read | evals.json + 被测 SKILL.md（路由规则段）（不读不得执行） |
| 输入 | evals.json + 被测 SKILL.md + mcp_backend |
| 输出 | eval-{N}/run-{R}/with_skill/outputs/{transcript.md, response.md} |
| 准出 | actual_transcripts ≥ expected_evals × 0.8 (80%+) |
| 降级 | 通过率 < 20% → 询问继续/终止；全失败 → 终止 + 报告环境问题 |
| 幂等 | 同 evals.json hash + 同 run 号 → 不重跑 |

稳定脚本入口:

```bash
python scripts/sentry_executor.py --evals evals.json --skill SKILL.md --session-dir <session> --variant with_skill
python scripts/sentry_executor.py --evals evals.json --skill SKILL.md --session-dir <session> --variant without_skill
```

`sentry_executor.py` 是重工具 wrapper:会调用 Claude CLI,但只负责执行、写 `executor_results.json` / `executor_without_skill_results.json` 和更新 session,不做 grader/report/gate。

**产物验收公式**（主调度器执行）：
```bash
# 注意：evals.json 的 key 可能是 "cases" 或 "evals"，兼容处理
expected=$(python3 -c "import json; d=json.load(open('evals.json')); print(len(d.get('cases', d.get('evals', []))))")
actual=$(find eval-*/run-${RUN}/with_skill/outputs/transcript.md | wc -l)
if [ $actual -lt $expected ]; then
  echo "⚠️ 产物不完整: $actual/$expected"
  # 缺失率 >20% → 触发降级；否则继续
fi
```

---

## grader-report (sentry-grader)

| 维度 | 定义 |
|------|------|
| must_read | evals.json(assertions数组) + 每个 eval 的 response.md（不读不得评审） |
| 输入 | eval-*/run-*/with_skill/outputs/* + evals.json(断言定义) |
| 输出 | eval-{N}/grading.json + grading-summary.json + report.html |
| 准出 | ≥ 1 个 eval 有 grading + grading-summary.json 存在 + report.html 存在或降级摘要存在 |
| 降级策略（三级） | |
| - L1(正常) | 逐个 eval 详细评审，断言级别判定 |
| - L2(超时降级) | subagent 600s 未完成 → 批量快速验证，只看关键断言 |
| - L3(异常降级) | L2 也超时 → 纯统计(文件存在+字数+关键词) → 标注 [DEGRADED-L3] |
| 幂等 | 同 transcript hash + 同 evals.json hash → 复用 grading |

稳定脚本入口:

```bash
python scripts/sentry_grader.py --evals evals.json --session-dir <session>
```

`sentry_grader.py` 是重工具 wrapper:会调用 SDK/LLM,但只读取已有 executor response,写 `grading.json`、`grading-summary.json`、`report.html` 和 session,不重跑 executor。

每个实际写入的 `grading.json` 会包含 `duration_ms` / `timing.grader_duration_ms`,只做单用例 grader 耗时观测,不参与评分、gate 或退出码判断。

---

## report (sentry-report, 独立重出报告)

> v9.0：主编排流程不再包含独立 `report` 步骤。`sentry-grader` 以 `grader-report` 步骤完成断言评审和报告生成。
> 本节仅用于独立调用场景：用户说“出报告/重新生成报告”，且已有 grading 产物。

| 维度 | 定义 |
|------|------|
| must_read | grading-summary.json + history.json（如有）（不读不得生成报告） |
| 输入 | grading-summary.json + history.json(如有) + session.json |
| 输出 | report.html + history.json 更新 |
| 准出 | report.html 存在 + grading-summary.json 存在 |
| 降级 | `scripts/sentry_report.py` 可从已有 session/result artifact 生成稳定 HTML;生成失败时再用纯文本摘要替代 |
| 幂等 | 同 grading hash → 不重新生成 |

脚本入口:

```bash
python scripts/sentry_report.py --session-dir <session>
python scripts/sentry_report.py --result <eval_result.json> --output report.html
```

该入口是 `no-llm, no-network` 轻工具;默认不覆盖真实交互式 grader 报告,除非显式 `--force`。

---

## comparator (sentry-comparator)

| 维度 | 定义 |
|------|------|
| must_read | with_skill/response.md + without_skill/response.md（不读不得判定） |
| 输入 | eval-*/run-1/with_skill/outputs/response.md + eval-*/run-1/without_skill/outputs/response.md + evals.json |
| 输出 | comparator-results.json（per-eval 盲测结果: A/B 谁赢 + 原因） |
| 准出 | comparator-results.json 存在 + 每个 eval 有判定 |
| 降级 | 超时 → 跳过 comparator，报告中标注"未做盲测对比" |
| 幂等 | 同 with/without hash → 复用 |
| 模式 | 仅 standard/full |

---

## analyzer (sentry-analyzer)

| 维度 | 定义 |
|------|------|
| must_read | comparator-results.json + 被测 SKILL.md（不读不得分析） |
| 输入 | comparator-results.json + eval-*/transcript.md + 被测 SKILL.md |
| 输出 | analyzer-recommendations.json（优先级排序的改进建议） |
| 准出 | recommendations 数组非空 |
| 降级 | 超时 → 跳过，报告中标注"未做根因分析" |
| 幂等 | 同 comparator hash → 复用 |
| 模式 | 仅 full |

---

## publish（主调度器直接执行，不委派 subagent）

| 维度 | 定义 |
|------|------|
| must_read | report.html + session.json + output-format.md(Completion Gate 清单) |
| 输入 | grading-summary.json + session.json + report.html(如有) + comparator-results.json(如有) + analyzer-recommendations.json(如有) |
| 输出 | 飞书文件 URL(如需) + 所有权转让 + 最终结果卡片(message) |
| 准出 | 用户收到结果卡片（通过自检清单） |
| 降级 | 上传失败 → 发送纯文本摘要 + 告知用户 HTML 在本地路径 |
| 幂等 | 同 session 已有 publish milestone → 不重复上传 |

**publish 按模式分级行为**：

| 模式 | 上传 HTML | 转让所有权 | 卡片内容 |
|------|:---:|:---:|------|
| smoke | ❌ | ❌ | 纯文本摘要（评级+通过率+关键发现） |
| quick | ❌ | ❌ | 五部分卡片（无 HTML 链接） |
| regression | ❌ | ❌ | 回归对比结果（vs 上次 baseline） |
| standard | ✅ | ✅ | 五部分卡片 + HTML 链接 + comparator 结论 |
| full | ✅ | ✅ | 五部分卡片 + HTML 链接 + comparator + analyzer 建议 |

**publish 步骤执行序列**（主调度器 4 个动作）：
```
1. feishu_drive_file(action=upload, file_path={workspace}/report.html)
   → 获取 file_token + url
2. feishu_drive_permission(action=transfer_owner, token=file_token, type=file,
   member_id={user_ou_id}, member_type=openid)
   → 转让所有权
3. message(action=send, msg_type="text", message=五部分完整格式 + HTML链接)
   → 最终结果卡片
4. 更新 session.json: last_step="publish", completed_at=now
```

**最终结果卡片自检清单**（发送前必须确认包含）：
- [ ] 第一部分：per-eval 结果表（按类型分组 + 断言通过率）
- [ ] 第二部分：断言统计（exact/semantic/existence 各自通过率）
- [ ] 第三部分：质量指标（A1-A3 + C1/C2/C4/C5 + E3 + V1-V8）
- [ ] 第四部分：Delta 增益（有数据展示值，无数据展示 "N/A + 原因"）
- [ ] 第五部分：评级 + 决策 + 总耗时 + HTML 报告链接
- [ ] 所有权已转让

缺少任何一项 = 不发送，先补全。

---

## 主调度器验收伪代码

```python
def dispatch_next():
    session = read("session.json")
    pipeline = session["pipeline"]
    last = session["last_step"]
    
    # 状态机：确定下一步
    next_step = pipeline[pipeline.index(last) + 1]
    
    # 管道：读取步骤契约
    contract = CONTRACTS[next_step]
    
    # 检查输入是否就绪
    for input_file in contract.inputs:
        if not exists(input_file):
            abort(f"前置步骤产物缺失: {input_file}")
    
    # 幂等：检查是否可复用
    if contract.is_idempotent and cache_hit(contract):
        display_cached_summary(contract)
        update_session(last_step=next_step)
        return dispatch_next()  # 递归到下一步
    
    # 派活
    result = spawn_subagent(contract.tool, contract.task_prompt)
    
    # 验收
    for output_file in contract.required_outputs:
        if not exists(output_file):
            if contract.degradation:
                trigger_degradation(contract, output_file)
            else:
                abort(f"产物缺失: {output_file}")
    
    # 更新状态
    update_session(last_step=next_step)
    notify_user(next_step, result)
```

---

---

## Pipeline 准出标准

| 步骤 | 准出条件 | 未通过 |
|------|---------|--------|
| static | 无 P0(lint) + TP ≥ 70%(trigger) | P0 → 暂停；TP 低 → 警告继续 |
| cases | 用例数 ≥ 3 | 警告「覆盖不足」 |
| executor | ≥ 1 个有 transcript | 全失败 → 终止 + 报告环境问题 |
| grader-report | ≥ 1 个有 grading + report 存在 | 全超时 → 标注「评审缺失」；报告失败 → 纯文本替代 |

---

*v1.0 · 2026-05-02 · 管道模式+状态机+降级+幂等 四合一*

---

## 飞书同步 PUSH 执行时机

| PUSH 操作 | 在哪个步骤之后执行 | 由谁执行 | 模式要求 |
|-----------|-----------------|---------|---------|
| PUSH-CASES | cases 步骤完成后 | 主调度器 | standard/full |
| PUSH-RESULTS | grader-report 步骤完成后 | 主调度器 | standard/full |
| PUSH-RUN | publish 步骤中 | 主调度器 | standard/full |

执行方式：主调度器在对应步骤验收通过后，调用 `feishu_bitable_app_table_record` 写入 Bitable。
config.json 不存在时静默跳过并记录 `skipped_no_config`。
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\step-contracts.md` |
| 学习重点 | step-contracts |
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
