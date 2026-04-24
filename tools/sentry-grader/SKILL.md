---
name: sentry-grader
description: >
  执行 Grader 评审：对 Executor 的 transcript 逐条评审断言，输出 grading.json。
  触发场景：说"评审这批结果"、"帮我评分"、"跑 Grader"、"断言评审"。
  不触发场景：要执行测试用例（用 sentry-executor）、要生成报告（用 sentry-report）、要做完整流程（用 SkillSentry 主编排器）。
---

# sentry-grader · 断言评审调度层

读取 Executor 产出的 transcript，调度 Grader Agent 逐条评审断言，输出 grading.json。

**前置条件**：workspace_dir 下各 eval-N 目录中存在 `with_skill/outputs/transcript.md`。

---

## 输入

- `workspace_dir`：本次测评工作目录（从 session.json 读取）
- `skill_type`：被测 Skill 类型（从 session.json 读取）
- `mode`：测评模式（从 session.json 读取）

---

## 调度策略（按模式）

| 模式 | 首批 Executor | Grader 策略 | 尾批 Executor |
|------|-------------|-----------|-------------|
| smoke | eval-1 ~ eval-2 | **同步**（等本批结束再启下一批） | — |
| quick | eval-1 ~ eval-3 | **同步等待前 ⌈N/3⌉ 个 eval 的 Grader 完成**，剩余 eval 非阻塞 | 后续 eval 并行 |
| standard/full | eval-1 ~ eval-3 | **非阻塞**（Grader 与 Executor 并行） | 后续 eval 并行 |

**非阻塞模式执行顺序**：
1. **并行审计**：检查 Executor 的工具调用日志，检测隐藏错误（静默失败、误用 API、遗漏必选参数等）
2. **启动 Grader 后台**：对前一批 eval 的 transcript 开始断言评审（异步，不阻塞后续 Executor）
3. **立即启动下一批 Executor**：不等 Grader 完成，保持流水线满载

---

## Grader 调用规范

- 每次调用必须传入 **≥ 2 个用例** 的 transcript
- 详细评审规范见 `agents/grader.md`
- 降级用例（`direct_fallback: true`）：A1/A2/A3/E3 正常评审，C3/C6 标记为 null

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

Grader subagent 超时（180s 无响应）时：

1. 标记该批 eval 的 grading 为 `"grader_timeout": true`
2. 输出：「⚠️ Grader 超时，该批 eval 的评审结果缺失」
3. 继续下一批（不阻塞流程）
4. report 阶段对超时 eval 标注「评审缺失」，不计入通过率

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

每个 eval 目录下写入 `grading.json`，格式见 `agents/grader.md`。

更新 `session.json` 的 `last_step` 为 `"step5_grader_done"`。

---

## 读取证明（主编排器校验用）

输出的最后一行必须包含以下格式的校验标记：

```
[sentry-proof] skill=<本工具名> steps=<本次执行的步骤数> ts=<ISO时间>
```

主编排器通过检查此标记确认子工具确实读取并执行了 SKILL.md，而非凭记忆发挥。
缺少此标记 → 主编排器判定为「未按 SKILL.md 执行」，要求重跑。
