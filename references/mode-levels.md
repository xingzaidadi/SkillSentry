# mode-levels.md — 模式分级控制

> sentry-cases / executor / report 根据 mode 参数自动调整流程深度。
> 主调度器在 spawn subagent 时注入 mode 参数。

---

## sentry-cases 流程深度

| 能力 | smoke | quick | standard | full |
|------|:---:|:---:|:---:|:---:|
| 三步扫描 | ❌ 跳过 | ⚡ 用缓存 | ✅ 完整 | ✅ 完整 |
| 测试数据采集 | ⚡ mcp_based查+确认/其他no_data | ⚡ 尝试查 | ✅ 必须查 | ✅ 必须查+用户确认 |
| 用例确认 | ❌ 跳过 | ❌ 跳过 | ✅ 需确认 | ✅ 需确认 |
| security 用例 | ❌ 不含 | ✅ ≥1 | ✅ ≥2 | ✅ ≥3 |
| 飞书 PULL | ⚡ 执行(可降级skipped_no_config) | ⚡ 有就拉 | ✅ 必须 | ✅ 必须 |
| 飞书 PUSH | ⚡ 执行(可降级skipped_no_config) | ⚡ 执行(可降级) | ✅ 必须 | ✅ 必须 |
| history.json | ❌ 不更新 | ✅ 更新 | ✅ 更新 | ✅ 更新 |

---

## executor 执行分级

| 能力 | smoke | quick | standard | full |
|------|:---:|:---:|:---:|:---:|
| with_skill runs | 1 | 2 | 3 | 3 |
| without_skill | ❌ 跳过 | ❌ 跳过(mcp) / ✅(text) | ✅ 1 run | ✅ 1 run |
| Delta 计算 | N/A | N/A(mcp) / ✅(text) | ✅ | ✅ |
| 批次大小 | 全部 | 全部 | ∖55/batch | ∖55/batch |

**without_skill 跳过规则**：
- mcp_based + smoke/quick → 跳过，Delta 卡片展示 "N/A(跳过 without_skill，mcp_based 无法在无 Skill 时调用工具)"
- text_generation 所有模式 → 必须执行（可以纯文本对比）
- mcp_based + standard/full → 必须执行（without_skill 只跑文本部分，不调 MCP）

---

## 报告产出分级

| 模式 | 产出 |
|------|------|
| smoke | grading-summary.json（本地） |
| quick | grading-summary.json + 飞书卡片推送 |
| standard/full | 三件套（HTML + summary + history）+ HTML 上传飞书 |

---

## auto-exempt 规则

auto 模式跳过的是「步骤间的继续确认」，以下场景即使 auto 也必须阻断：

| 场景 | 原因 | 所在步骤 |
|------|------|----------|
| MCP 预检全不可用 | 无法执行 real_data 用例 | Step 1 |
| real_data 测试数据采集 | 禁止 AI 编造单号/ID | sentry-cases |
| 用例设计审核 | 用户需确认覆盖度 | sentry-cases(standard/full) |
| 写操作/不可逆操作确认 | 安全要求 | 任意步骤 |

---

*v1.0 · 2026-05-02 · 从 SKILL.md 模式分级章节提取*
