---
name: sentry-openclaw
description: >
  SkillSentry 的 OpenClaw 适配层。当用户说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、
  "能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"时使用。
  本工具桥接 SkillSentry 工具箱和 OpenClaw 原生能力，自动处理路径映射、subagent 调用、进度推送。
  不触发场景：只是在讨论Skill设计思路、修改Skill内容、或泛泛聊AI话题。
---

# sentry-openclaw · SkillSentry × OpenClaw 适配层

你是 **SkillSentry** 在 OpenClaw 平台上的适配器。核心职责：将 SkillSentry 的评测工作流映射到 OpenClaw 原生能力执行。

---

## 架构

```
用户消息（飞书/其他）
  → sentry-openclaw（本适配层）
    → 读取 SkillSentry 定义的工作流（smoke/quick/standard/full）
    → 映射为 OpenClaw 原生操作：
      ├─ 路径映射：OpenClaw 目录 → SkillSentry 期望的目录结构
      ├─ 工具映射：sentry-* 工具 → Agent 前台执行 / sessions_spawn 后台执行
      └─ 进度推送：飞书卡片通知
    → 结果写回 SkillSentry 兼容的目录格式
```

---

## ① 路径映射

### 被测 Skill 查找

按以下顺序搜索，找到即停：

```
1. ~/.openclaw/workspace/skills/<名字>/SKILL.md     ← workspace skills（优先）
2. ~/.openclaw/skills/<名字>/SKILL.md                ← installed skills
3. 用户提供的完整路径
```

找不到时输出友好提示（禁止报错退出）：
```
❌ 找不到 Skill：<名字>

已搜索：
  • ~/.openclaw/workspace/skills/<名字>/SKILL.md
  • ~/.openclaw/skills/<名字>/SKILL.md

请确认名字拼写，或直接提供完整路径。
```

### SkillSentry 工具查找

```
SkillSentry 主体：~/.openclaw/skills/SkillSentry/
sentry-lint：     ~/.openclaw/skills/sentry-lint/SKILL.md
sentry-trigger：  ~/.openclaw/skills/sentry-trigger/SKILL.md
sentry-cases：    ~/.openclaw/skills/sentry-cases/SKILL.md
sentry-executor： ~/.openclaw/skills/sentry-executor/SKILL.md
sentry-report：   ~/.openclaw/skills/sentry-report/SKILL.md
```

### 工作目录

```
session_dir = ~/.openclaw/workspace/skills/SkillSentry/sessions/<Skill名>/<YYYY-MM-DD>_<NNN>/
inputs_dir  = ~/.openclaw/workspace/skills/SkillSentry/inputs/<Skill名>/
```

如果目录不存在，自动创建。

---

## ② Skill 类型检测

读取被测 SKILL.md，按以下规则检测：

```
mcp_based（最高优先级）：
  SKILL.md 中出现业务 MCP 工具名（camelCase，如 saveExpenseDoc、queryItems）
  或出现 "MCP"、"mcp_server" 关键词

  排除以下 OpenClaw/Claude Code 内置工具：
  Read/read、Write/write、Edit/edit、Bash/exec、Glob/glob、Grep/grep、
  Agent/agent、WebFetch/web_fetch、WebSearch/web_search、
  sessions_spawn、message、feishu_*、image、pdf

code_execution：
  不满足 mcp_based，且出现 python3、bash、exec、脚本、shell 关键词
  或 SKILL.md 中有具体命令示例

text_generation（兜底）：
  以上均不满足
```

输出检测结果：
```
✅ Skill 类型：code_execution（依据：发现 python3 engine.py 命令）
```

---

## ③ 工作流调度

### 特殊命令（直接执行，跳过工作流）

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry 安装` | 检查所有工具文件是否存在 |
| `检查结构 <Skill名>` / `lint` | 只跑 sentry-lint |
| `测触发率 <Skill名>` | 只跑 sentry-trigger |
| `设计用例 <Skill名>` | 只跑 sentry-cases |
| `出报告` | 只跑 sentry-report |

### 工作流自动推断

```
计算被测 SKILL.md 的 MD5
读取 inputs_dir/rules.cache.json

推断逻辑：
  rules.cache.json 不存在        → quick（首次测评）
  hash 不匹配（SKILL.md 变更）   → smoke（快速验证）
  hash 匹配 + cases 缓存存在     → regression
  hash 匹配 + cases 缓存不存在   → quick
```

推断完成后输出确认：
```
✅ 被测 Skill：<名称>
📊 推荐工作流：<名称>（<原因>）
⏱️ 预计时间：<时间>
回复「开始」确认，或说 full/quick/smoke 切换
```

含 `自动` 时跳过确认。

---

## ④ 工具执行映射

### sentry-lint（前台执行，~30 秒）

读取 sentry-lint/SKILL.md 的检查清单，逐项检查被测 SKILL.md：
- L1：description 完整性
- L2：HiL 节点检查
- L3：复杂度评估
- L4：安全检查

直接在当前会话中执行，不需要 subagent。

### sentry-trigger（前台执行，~2 分钟）

读取 sentry-trigger/SKILL.md 的评估流程，对被测 SKILL.md 的 description 做触发率模拟评估。

直接在当前会话中执行。

### sentry-cases（前台执行，~5-10 分钟）

读取 sentry-cases/SKILL.md 的用例设计流程：
1. 读取被测 SKILL.md，提炼规则
2. 检查 inputs_dir 下的外部用例文件（*.cases.md）
3. 按模式设计用例（smoke=4, quick=8, standard=20, full=30）
4. 输出 evals.json 到 session_dir

直接在当前会话中执行。

### ⚡ 透明执行原则（所有步骤通用）

**核心要求：每个步骤完成后，必须立即向用户展示该步骤的完整结果。不允许黑盒运行——用户必须能看到每一步发生了什么。**

各步骤完成后必须展示的内容：

| 步骤 | 完成后必须展示 | 展示格式 |
|------|-------------|---------|
| sentry-lint | 检查结果表格（L1-L4 各项 ✅/❌ + 具体问题） | Markdown 表格 |
| sentry-trigger | TP/TN 触发率 + 置信度 + 误触发风险 | 关键指标卡片 |
| sentry-cases | 用例列表（id、类型、名称、prompt 摘要） | 编号列表 |
| sentry-executor | 每批完成后：通过/失败状态 + 耗时 + 并行率 | 进度卡片 |
| grader | 12 项指标（A1-A3 + C1-C6 + E1-E3）+ 否决项检测 | 指标面板 |
| sentry-report | 完整报告（等级 + 结论 + 指标 + 失败用例） | 报告卡片 |

**展示时机**：步骤完成 → 立即展示 → 确认用户看到 → 再启动下一步。禁止「全部跑完再一次性展示」。

**示例流程**：
```
1. lint 完成 → 展示检查结果表格
   "✅ lint 完成：L1 ✅ L2 ✅ L3 ⚠️（复杂度 18）L4 ✅"

2. trigger 完成 → 展示触发率
   "🎯 触发率：TP 92%（high）TN 88%（high）"

3. cases 完成 → 展示用例列表
   "📝 生成 8 个用例：happy_path×3, edge_case×2, negative×2, robustness×1"

4. executor 每批完成 → 展示进度
   "⚡ 批次 1/3 完成：eval-1 ✅ eval-2 ✅ eval-3 ❌（3/4 通过）"

5. grader 完成 → 展示 12 项指标
   "📊 12 项指标：A1 97% ✅ A2 0% ✅ A3 100% ✅ C1 100% ✅ C2 0% ✅ C3 89% ⚠️ ..."

6. report 完成 → 展示完整报告
   "📊 综合等级：A   结论：PASS"
```

### sentry-executor（subagent 并行执行，核心模块）

这是最关键的模块。将 SkillSentry 的并行 subagent 执行映射到 OpenClaw 的 sessions_spawn。

**执行流程**：

```
1. 读取 evals.json，确认用例列表
2. 按批次启动 subagent：

   批次大小：
     smoke：全部一次性（4-5 个 eval，每个 1 个 subagent = 4-5 个）
     quick（mcp_based）：全部一次性（8-10 个 eval × 1 run = 8-10 个 subagent）
     quick（其他）：每批 4-5 个 eval（每 eval × 2 run = 8-10 个 subagent/批）
     standard/full：每批 2-3 个 eval（4-6 个 subagent/批）

3. 每个 eval 的 subagent 启动方式：

   sessions_spawn(
     task = "<执行提示词，包含 eval prompt + transcript 格式要求>",
     label = "eval-N-with-skill",
     cwd = "<session_dir>/eval-N/with_skill/workspace/",
     runTimeoutSeconds = 300
   )

4. 等待批次内所有 subagent 完成
5. 汇总结果，写入 transcript.md / metrics.json
6. 启动下一批次
```

**skip_without_skill 处理**：

```
evals.json 中 skip_without_skill=true 的用例：
  → 只启动 with_skill subagent
  → without_skill 侧标记为 "skipped"

skip_without_skill=false 的用例：
  → with_skill 和 without_skill 各启动一个 subagent
  → without_skill 的 task 中注入沙箱隔离声明
```

**without_skill subagent 注入内容**（从 sentry-executor SKILL.md 复制）：

```
你的工作目录是 eval-N/without_skill/workspace/，禁止读取 eval-N/with_skill/ 下的任何文件。
所有操作必须独立完成，不能复用 with_skill 的任何结果。
你的目标是展示没有 Skill 指导时的自然行为。

【沙箱隔离自检 - 执行完成后写入 response.md 末尾】：
1. 我是否读取了 eval-N/with_skill/ 目录下的任何文件？（是/否）
2. 我使用的所有结果，是否全部由本次独立执行产生？（是/否）
```

**断点续跑**：

```
启动前扫描 session_dir/eval-*/ 目录：
  transcript.md 存在且非空 → 标记为"已完成"
  否则 → 标记为"待执行"

有已完成的用例时输出提示，含 `自动` 时跳过已完成。
```

### Grader（subagent 执行，~5-10 分钟/批）

每批 executor 完成后，启动 grader subagent：

```
sessions_spawn(
  task = "<读取 agents/grader.md 的评分指令 + 该批所有 eval 的 transcript>",
  label = "grader-batch-N",
  cwd = "<session_dir>",
  runTimeoutSeconds = 600
)
```

grader 输出 grading.json 到每个 eval 目录下。

### sentry-report（脚本生成，秒级）

所有 executor + grader 完成后，调用模板生成脚本（不消耗 token）：
```bash
python3 ~/.openclaw/skills/SkillSentry/scripts/generate_report.py <skill名> <模式> <模型>
```

脚本自动读取 evals.json + grading.json，填充 HTML 模板，秒级输出 report.html。
生成后自动上传飞书云文档并发送链接给用户。

### 飞书进度推送（每步即时展示）

使用 `message` 工具推送飞书消息（参考 SkillSentry 的 feishu-templates.md 模板）。

**关键原则：每个步骤完成后必须立即推送完整结果，不允许黑盒运行。**

```
里程碑1：lint 完成 → message send（检查结果表格）
里程碑2：trigger 完成 → message send（TP/TN 触发率）
里程碑3：cases 完成 → message send（用例列表）→ feishu_ask_user_question（确认执行）
里程碑4：executor 每批完成 → message send（通过/失败状态 + 耗时）
里程碑5：grader 完成 → message send（12 项指标面板）
里程碑6：report 完成 → message send（完整报告卡片）+ MEDIA 报告文件路径
```

**每个里程碑的消息必须包含该步骤的完整输出**，用户无需追问「lint 结果怎么样」「trigger 通过了吗」。

---

## ⑤ 数据接口

完全复用 SkillSentry 定义的 JSON 接口格式：

```
rules.cache.json → evals.json → grading.json → report
```

文件格式不做任何修改，保证与 SkillSentry 上游兼容。

---

## ⑥ 验证安装

当用户说「验证安装」或「验证 SkillSentry 安装」时，执行：

```
检查以下文件是否存在：
  ~/.openclaw/skills/SkillSentry/SKILL.md
  ~/.openclaw/skills/sentry-lint/SKILL.md
  ~/.openclaw/skills/sentry-trigger/SKILL.md
  ~/.openclaw/skills/sentry-cases/SKILL.md
  ~/.openclaw/skills/sentry-executor/SKILL.md
  ~/.openclaw/skills/sentry-report/SKILL.md
  ~/.openclaw/skills/sentry-openclaw/SKILL.md（本适配层）

输出：
🔍 SkillSentry 安装状态检查（OpenClaw）
  ✅ / ❌ 每个工具的状态
```

---

## ⑦ 使用示例

```
用户：测评 mify-data-factory

1. 搜索被测 Skill → ~/.openclaw/workspace/skills/mify-data-factory/SKILL.md ✅
2. 检测类型 → code_execution
3. 计算 MD5 → 首次测评
4. 推荐 quick 模式 → 发飞书确认卡片
5. 用户确认 → 透明执行：
   a. sentry-lint → 静态检查 → 📋 展示检查结果表格
   b. sentry-trigger → 触发率评估 → 🎯 展示 TP/TN
   c. sentry-cases → 生成 8 个用例 → 📝 展示用例列表
   d. sentry-executor → sessions_spawn × 16（分批）→ ⚡ 每批展示进度
   e. grader → 评分 → 📊 展示 12 项指标
   f. sentry-report → 生成报告 → 📄 展示完整报告
6. 飞书推送：「📊 综合等级：A   结论：PASS」（含完整指标面板）
```

---

*Last Updated: 2026-04-16 v1.0*
