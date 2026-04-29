---
name: sentry-grader
description: >
  执行 Grader 评审 + 生成报告：对 Executor 的 transcript 逐条评审断言，输出 grading.json，然后汇总生成 report.html。
  触发场景：说"评审这批结果"、"帮我评分"、"跑 Grader"、"断言评审"。
  不触发场景：要执行测试用例（用 sentry-executor）、仅生成报告且 grading 已完成（用 sentry-report）、要做完整流程（用 SkillSentry 主编排器）。
---

# sentry-grader · 断言评审 + 报告生成（v3.0 合并架构）

## 调用模式

本工具支持两种调用模式：
- **主编排模式**（默认）：SkillSentry 主编排器 spawn 单个 grader-report subagent，串行评审所有 runs + 合并 grading + 生成报告
- **独立调用模式**：用户单独触发 sentry-grader 时，可走 run-stratified 多 subagent 并行评审（见下方"并行执行架构"章节）

读取 Executor 产出的 transcript，逐条评审断言，输出 grading.json，**然后直接汇总生成 report.html**。grader 和 report 合并在同一个 subagent 中执行，减少 yield/resume 次数。

> **为什么合并**：每 spawn 一个 subagent 需要经过 LLM 调度，yield/resume 开销 3-7 分钟。将 grader 和 report 合并为 1 个 subagent，省掉 1 次 spawn，节省 ~5 分钟。

**前置条件**：workspace_dir 下各 eval-N 目录中存在 `with_skill/outputs/transcript.md`。

---

## 输入

- `workspace_dir`：本次测评工作目录（从 session.json 读取）
- `skill_type`：被测 Skill 类型（从 session.json 读取）
- `mode`：测评模式（从 session.json 读取）

---

## 并行执行架构（run-stratified，与 executor 对齐）

**核心原则**：grader 按 run 拆分为多个 subagent 并行评审，消除单 subagent 串行瓶颈。

### 分组策略

| mode | runs | subagent 数 | 每个 subagent 负责 | 预计耗时 |
|------|------|------------|-------------------|----------|
| smoke / regression | 1 | 1 | 全部 eval 的 run-1 | ~3min |
| quick | 2 | 2（并行） | 各负责 1 个 run 的全部 eval | ~4min |
| standard / full | 3 | 2+1（两波） | 先并行 2 个，完成 1 个后启动第 3 个 | ~6min |

### spawn 策略

**❗ gateway 并发限制：同时最多 spawn 2 个 subagent**（见踩坑记录问题 1）

```
standard/full 模式（3 runs）：
  第 1 波：同时 spawn Grader-run-1 + Grader-run-2（2 并发）
  第 2 波：任一完成后 spawn Grader-run-3
  runTimeoutSeconds = 600

quick 模式（2 runs）：
  同时 spawn 2 个 subagent（刚好在限制内）

smoke/regression（1 run）：
  1 个 subagent
```

> 注意：gateway websocket 握手有并发瓶颈，实测同时只能处理 ~2 个 spawn 请求。
> 超过 2 个会触发 `gateway timeout after 10000ms`。
> 因此 3 runs 必须分两波 spawn，与 executor 的 spawn 策略保持一致。

### subagent task 构造

```
你是 Grader subagent，负责所有 eval 的 run-{R} 评审。

对每个 eval（1-N）：
1. 读取 eval-{N}/run-{R}/with_skill/outputs/transcript.md 和 response.md
2. 读取 evals.json 中该用例的 assertions
3. 逐条评审，标注 pass/fail + evidence
4. 评审结果写入内存，全部完成后统一写 grading.json
```

### 产物合并（主会话执行）

```
所有 subagent 完成后，主会话合并：
  对每个 eval：
    读取 3 个 subagent 输出的 run-1/run-2/run-3 评审结果
    合并为单个 grading.json（包含所有 runs）
    写入 eval-{N}/grading.json
```

> **写入时机**：每个 grader subagent 将评审结果写入 `eval-{N}/grading-run-{R}.json`（临时文件），主会话合并后写入最终 `eval-{N}/grading.json`。避免多 subagent 同时写同一文件的竞争。

---

## 调度策略（与 Executor 的协同）

| 模式 | 首批 Executor | Grader 策略 | 尾批 Executor |
|------|-------------|-----------|-------------|
| smoke | eval-1 ~ eval-2 | **同步**（等本批结束再启下一批） | — |
| quick | eval-1 ~ eval-3 | **同步等待前 ⌈N/3⌉ 个 eval 的 Grader 完成**，剩余 eval 非阻塞 | 后续 eval 并行 |
| standard/full | eval-1 ~ eval-3 | **非阻塞**（Grader 与 Executor 并行） | 后续 eval 并行 |

**非阻塞模式执行顺序**：
1. **并行审计**：检查 Executor 的工具调用日志，检测隐藏错误（静默失败、误用 API、遗漏必选参数等）
2. **启动 Grader 后台**：对前一批 eval 的 transcript 开始断言评审（按 run 分组并行，不阻塞后续 Executor）
3. **立即启动下一批 Executor**：不等 Grader 完成，保持流水线满载

---

## Grader 调用规范

- 每个 grader subagent 处理 **1 个 run 的全部 eval**（批量评审，非逐个 spawn）
- 详细评审规范见 `agents/grader.md`
- 降级用例（`direct_fallback: true`）：A1/A2/A3/E3 正常评审，C3/C6 标记为 null
- **预编译优化**：主会话预读 evals.json 的 assertions 列表，注入 subagent task，subagent 无需再读 evals.json

---

## 脚本预验证（Step 0，AI 评审前执行）

对 `exact_match` 类断言先用 `scripts/verify_assertions.py` 脚本验证：

```bash
python3 scripts/verify_assertions.py \
  --transcript <eval-N>/with_skill/outputs/transcript.md \
  --response <eval-N>/with_skill/outputs/response.md \
  --assertions <eval-N>/assertions.json \
  --output <eval-N>/grading_script.json
```

脚本结论即最终结论，不允许 AI 重判（避免 15-20% 高估偏差）。

---

## 快速失败检测（仅 quick 模式）

```
第一批 Grader 完成后：
  first_batch_pass_rate < 20%：
    ⚠️ 前 [N] 个用例平均通过率 [X]%，Skill 可能存在根本性问题
    选项：
      [继续执行剩余用例]
      [立即终止，查看当前结果] ← 默认，30 秒后自动选择

  first_batch_pass_rate ≥ 20%：静默继续
```

---

## Grader 超时处理

Grader subagent 超时（600s 无响应）时：

1. 检查已完成的 `grading-run-{R}.json` 文件数
2. 部分完成 → 保留已完成结果，缺失 eval 标记 `"grader_timeout": true`
3. 全部超时 → 标记该 run 所有 eval 为超时
4. 输出：「⚠️ Grader run-{R} 超时，{N} 个 eval 评审缺失」
5. 不阻塞其他 run 的 grader（并行独立）
6. report 阶段对超时 eval 标注「评审缺失」，不计入通过率

### 重试策略

超时的 run 自动重试 1 次（仅重跑缺失的 eval），仍失败则标记超时。

---

## 回执格式

```
✅ grader 完成 | ⏱ Xmin

总断言：N 条 | 通过：X | 失败：Y | 不确定：Z
精确通过率：X% | 综合通过率：Y%
脚本验证：N 条 exact_match（method: script）
```

---

## 输出

每个 eval 目录下写入 `grading.json`。

**❗ 格式必须统一**（无论哪个 grader subagent）：

```json
{
  "eval_id": "eval-N",
  "runs": {
    "run-1": {
      "pass": true,
      "assertions": [
        {"id": "E1", "type": "exact_match", "expect": "断言文本", "pass": true, "evidence": "引用原文"}
      ]
    },
    "run-2": { ... },
    "run-3": { ... }
  },
  "summary": {
    "pass": N, "fail": N, "total": N,
    "precision_breakdown": {"exact_match": {"pass": N, "total": N}, "semantic": {"pass": N, "total": N}},
    "authoritative_pass_rate": 0.XX
  },
  "feishu_record_id": "recXXX（从 evals.json 透传，无则省略）"
}
```

**字段计算规则**：
- `precision_breakdown`：按断言类型（exact_match / semantic）分别统计通过数和总数
- `authoritative_pass_rate`：= precision_breakdown.exact_match.pass / precision_breakdown.exact_match.total（精确断言通过率，report 用此做准入判定）
- `feishu_record_id`：从 evals.json 中对应用例的 feishu_record_id 字段透传，用于 PUSH-RESULTS 回写飞书
```

**禁止的格式**：`runs` 为数组、`expectations` 嵌套 `runs`、`verdict` 替代 `pass` 等变体。必须严格按上述结构。

更新 `session.json` 的 `last_step` 为 `"step6_grader_done"`。

---

## Step 7：合并 grading 并生成报告（grader 完成后自动执行）

grader 评审全部完成后，在同一个 subagent 中执行以下步骤（无需另起 subagent）：

### 7.1 合并 grading.json

对每个 eval，读取 run-1/run-2/run-3 的 grading-run-{R}.json，合并为最终 grading.json：

```python
# 合并逻辑
for eval_id in eval_ids:
    merged = {"eval_id": eval_id, "runs": {}}
    for run in ["run-1", "run-2", "run-3"]:
        grading_file = f"{session_dir}/{eval_id}/grading-{run}.json"
        if exists(grading_file):
            merged["runs"][run] = read_json(grading_file)
    write_json(f"{session_dir}/{eval_id}/grading.json", merged)
```

### 7.2 汇总通过率

```
精确通过率 = exact_match 断言通过数 / exact_match 断言总数
语义通过率 = semantic 断言通过数 / semantic 断言总数
综合通过率 = 全部断言通过数 / 全部断言总数
稳定性 = max(per_run_pass_rate) - min(per_run_pass_rate) < 15%
```

### 7.2.1 新增指标判定（从 metrics_raw.json + evals.json 提取）

如果 evals.json 中的用例包含以下字段，grader 额外判定对应指标：

| 指标 | evals.json 字段 | 判定规则 | 通过标准 |
|------|----------------|----------|----------|
| C1 工具完整率 | `tools_required` | tools_required ⊆ transcript 中的 tools_called | ≥ 90% |
| C2 工具越界率 | `tools_forbidden` | tools_forbidden ∩ tools_called = ∅ | = 0% |
| C4 副作用率 | 无（自动检测） | transcript 中 write/delete/patch/create/update/submit 调用 ∉ tools_required | = 0% |
| C5 参数正确率 | `critical_params` | transcript Args 中关键参数值 ∈ 允许列表 | ≥ 90% |
| E1 回复质量 | `reply_contains` / `reply_not_contains` / `min_reply_length` | response.md 包含关键词 + 不含禁词 + 长度达标，满足 2/3 即过 | 2/3 项 |

**向后兼容**：如果 evals.json 中没有这些字段，对应指标标记为 `"status": "not_applicable"`，不影响等级判定。

**写入 grading-summary.json**：
```json
"indicators": {
  "C1": {"value": 0.95, "pass": true, "status": "measured"},
  "C2": {"value": 0.0, "pass": true, "status": "measured"},
  "C4": {"value": 0.0, "pass": true, "status": "measured"},
  "C5": {"value": 0.92, "pass": true, "status": "measured"},
  "E1": {"value": 0.85, "pass": true, "status": "measured"}
}
```

### 7.3 生成 report.html

生成完整独立的 HTML 报告（含内联 CSS，无外部依赖），写入 `{session_dir}/report.html`。

报告必须包含：
1. **概要卡片**：Skill 名、模式、日期、评级（S/A/B/C）、通过率
2. **各轮对比**：run-1/run-2/run-3 的通过率和趋势
3. **失败分析**：按失败模式分组（如 MCP 错误、多轮缺失、路由错误）
4. **每个 eval 详情**：通过/失败断言列表，含 evidence 引用
5. **建议**：P0/P1/P2 分级改进建议

评级标准：见 references/admission-criteria.md Step 4.1 的六档层级达标制。本步骤只输出各项指标值（精确通过率、语义通过率、IFR、一致性、稳定性等），等级判定由 report 逻辑执行。

### 7.4 更新 session.json

```json
{
  "last_step": "grader-report",
  "grader": {"pass": N, "fail": N, "total": N, "pass_rate": N, "per_run": {...}},
  "verdict": {"grade": "A", "decision": "CONDITIONAL_PASS", "pass_rate": 87.2}
}
```

### 7.5 更新 history.json

读取 `{inputs_dir}/history.json`，追加本次记录：
```json
{"run_at": "ISO", "session": "dir_name", "mode": "full", "eval_count": 33, "exact_pass_rate": 0.872, "verdict": "A"}
```

### 7.6 输出回执

```
✅ grader + report 完成 | ⏱ Xmin

总断言：N 条 | 通过：X | 失败：Y | 综合通过率：Z%
评级：A | 发布决策：CONDITIONAL PASS
⚠️ 此结论由 AI 生成，如需正式发布请人工确认。

📄 report.html（XKB）已生成
```

---

## 性能基准

| 场景 | v1.0（串行） | v2.0（并行） | v3.0（合并 report） |
|------|------------|------------|------------------|
| 33 eval × 1 run (smoke) | ~4min | ~4min | ~5min（含报告） |
| 33 eval × 2 run (quick) | ~8min+6min report | ~4min+6min | ~10min（含报告） |
| 33 eval × 3 run (full) | ~12min+6min | ~6min+6min | ~14min（含报告） |
| 100 eval × 3 run | ~36min+6min | ~18min+6min | ~24min（含报告） |

v3.0 将 grader+report 合并到同一 subagent，虽然 grader 本身耗时不变，但省掉 1 次 yield/resume（~5min），总时间更优。

---

## 读取证明（主编排器校验用）

输出的最后一行必须包含以下格式的校验标记：

```
[sentry-proof] skill=<本工具名> steps=<本次执行的步骤数> ts=<ISO时间>
```

主编排器通过检查此标记确认子工具确实读取并执行了 SKILL.md，而非凭记忆发挥。
缺少此标记 → 主编排器判定为「未按 SKILL.md 执行」，要求重跑。
