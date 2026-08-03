# SkillSentry 与 skill-creator 的能力关系

> 本文档说明 SkillSentry 在设计上借鉴了 skill-creator 的哪些核心机制，
> 以及两者的定位区别。面向希望深入了解工具原理的工程师。

---

## 两者的定位

| 工具 | 解决什么问题 | 核心能力 |
|------|------------|---------|
| **skill-creator** | Skill 的创建、迭代优化、触发率测评 | 写 Skill → 测触发率 → 优化 description |
| **SkillSentry** | Skill 触发后的行为质量测评 | 读 Skill → 穷举路径 → 设计用例 → 四层验证 → 出报告 |

两者互补，不是替代关系：
- 先用 skill-creator 确认 Skill 能被正确触发（触发率 ≥90%）
- 再用 SkillSentry 验证触发后的行为质量（通过率 ≥95%）

---

## SkillSentry 借鉴自 skill-creator 的设计

### 1. 独立 Grader Agent（`agents/grader.md`）

**来源**：skill-creator 的 `agents/grader.md`

**借鉴内容**：
- 执行者和评审者分离的思路（消除自判卷偏差）
- 8 步评审工作流
- evidence 必须引用原文的约束

**我们的扩展**：
- 增加了 `claims` 隐含声明验证（幻觉检测）
- 增加了 `eval_feedback` 断言质量批评
- 中文化适配，增加 `method` 字段标注 ground_truth vs grader
- evidence 为空时在报告中标红警告
- 增加「纯文本评审标准」章节，支持 text_generation Skill 的 evidence 从 response.md 引用；增加 `skill_type` 输入字段；增加效率指标（timing.json）读取

### 2. 盲测 Comparator Agent（`agents/comparator.md`）

**来源**：skill-creator 的 `agents/comparator.md`

**借鉴内容**：
- 盲测设计：Comparator 不知道哪个是 with_skill，消除评审偏见
- 内容/结构维度 1-5 分制评分
- 综合得分计算方法

**我们的扩展**：
- 中文化适配
- 增加了「E2E 用例必须执行 Comparator」的强制规则

### 3. Analyzer Agent（`agents/analyzer.md`）

**来源**：skill-creator 的 `agents/analyzer.md`

**借鉴内容**：
- 解盲后读双份 transcript 分析根因的思路
- priority 排序的改进建议格式

**我们的扩展**：
- 中文化适配
- 增加了对「E2E 规则组合失败」的专项分析指引

### 4. timing.json 数据采集

**来源**：skill-creator SKILL.md 中 Step 3 的 timing 采集规范

**借鉴内容**：
- task notification 含 `total_tokens` 和 `duration_ms`，必须即时保存的设计
- timing.json 的字段格式

grader.md 现在会主动读取 timing.json 并将 `executor_duration_ms` 和 `total_tokens` 写入 grading.json；generate_html_report.py 新增 `_render_efficiency_section` 函数聚合显示 P50/P95 响应时间。

### 5. 样本标准差计算

**来源**：skill-creator 的 `scripts/aggregate_benchmark.py`（`calculate_stats` 函数）

**借鉴内容**：
- 使用样本标准差（n-1）而非总体标准差（n）的设计
- mean / stddev / min / max 的统计指标集合

---

## skill-creator 有哪些能力 SkillSentry 的集成状态

| skill-creator 能力 | 集成状态 | 说明 |
|-------------------|---------|------|
| **触发率测评**（`run_eval.py`）| ✅ **估算 + 可选精确探测** | `sentry_trigger_eval.py` 默认给出确定性触发估算；`--precise` 在本机有 Claude CLI 时尝试真实触发探测，否则显式 skipped |
| **description 自动优化循环**（`run_loop.py`）| ✅ **轻量集成** | `sentry_optimize_description.py` 已提供非破坏性优化建议，不直接改写 `SKILL.md` |
| **60/40 防过拟合分割** | ✅ **已集成** | description 优化时自动拆分 train/test，分别输出命中摘要 |
| **实时 live report**（边跑边看）| ✅ **轻量集成** | `report_server.py` 可指向 sessions 根目录浏览最新 `report.html` |
| **generate_review.py 交互式 viewer** | ⚠️ 部分 | 我们重写了 HTML 报告，不是 server 模式，但加入了人工反馈区 |
| **aggregate_benchmark.py** | ✅ 思路借鉴 | 我们在 generate_html_report.py 中实现了类似的聚合逻辑 |
| Grader / Comparator / Analyzer | ✅ 借鉴并扩展 | 见上方详细说明 |
| **纯文本 Skill 测评** | ✅ **已支持** | Skill 类型自动检测（mcp_based/text_generation/code_execution），纯文本模式使用 response.md 作为 evidence 来源 |
| **效率层指标采集** | ✅ **已支持** | grader.md 读取 timing.json，generate_html_report.py 聚合展示 P50/P95/Token |
| **V2 方法论分析**（路由/归因/污染/校准/benchmark）| ✅ **已集成** | `sentry_methodology_v2.py` 输出 route matrix、failure taxonomy、contamination、grader calibration 和 benchmark adapter 映射 |

---

## 触发率测评的当前方案与未来路径

### 当前方案：AI 模拟估算

```
阶段一：从 description 提取触发语义
         ↓
生成 10 条测试 prompt（5 TP + 3 TN + 2 边界）
         ↓
AI 逐条判断触发概率（prediction + confidence + reasoning）
         ↓
计算 TP 触发率、TN 不触发率、边界 uncertain 率
         ↓
输出 trigger_eval.json，报告第十一章展示（标注「AI 模拟，非精确测量」）
```

**适用场景**：快速预判 description 质量，发现明显的触发问题。
**局限性**：不是真实触发测量，置信度有限。

### 未来精确方案：集成 skill-creator run_eval.py

```python
# 核心机制：
# 1. 临时创建 Skill 命令文件到 .claude/commands/
# 2. 执行 claude -p <query> --output-format stream-json --include-partial-messages
# 3. 监听 SSE 流事件，检测 Skill/Read 工具调用，一旦触发立即返回
# 4. 每个 query 默认跑 3 次取触发率均值
# 5. 10 个 worker 并行
```

集成需要：
- `claude` CLI 在测评执行环境中可调用
- 当条件满足时，可直接调用 skill-creator 的 `run_loop.py`，无需重新实现

---

*本文档记录工具设计的技术溯源，供工程师参考。Last Updated: 2026-03-26*
---

## AI Skill 测评学习补充卡

> 说明：本补充卡按《AI Skill 测评学习总纲：唯一主线版》的学习口径补齐，方便复习、面试和项目复盘。

### 本文件定位

| 项目 | 内容 |
|---|---|
| 所属主题 | AI Skill 测评学习资料 |
| 当前文件 | `SkillSentry_repo\references\archive\skill-creator-capability-notes.md` |
| 学习重点 | skill-creator-capability-notes |
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
