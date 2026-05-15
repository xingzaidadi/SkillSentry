---
name: skill-eval-测评
version: "9.0.0"
description: >
  SkillSentry - AI Skill 质量测评系统。Each run is a fresh execution. Current SKILL.md and session state override memory.
  触发场景:说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  ⚠️ 强制执行规则:当用户消息匹配上述触发词时,你必须先读取本 skill 的 SKILL.md 并按其流程执行,禁止跳过 skill 直接编排 subagent 或自行执行测评流程。即使你觉得自己知道怎么做,也必须先读 SKILL.md。
  ⚠️ 旧记忆警告:如果你的 memory 中有 SkillSentry 的旧版执行记录(如用纯文本列表选择 skill、跳过交互卡片),这些是过时的行为模式。当前版本要求用飞书 V2 卡片(独立 select_static 下拉框)选择 Skill 和模式。必须读 SKILL.md 确认当前版本的行为,不要照搬 memory 中的旧做法。
  不触发场景:讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
metadata:
  author: 刘四星
  created_at: "2026-03-27"
---

## ⛔ 版本锁定 & 行为优先级(本节不可删除)

**本文件是 SkillSentry v9.0.0,是唯一权威的行为定义。**

**v9.0 定位**:契约收敛版。当前版本优先统一执行契约、术语口径和文档入口,不新增测评维度、不新增平台适配、不改变报告视觉结构。

**当前口径速记**:
- 主流程评分报告步骤叫 `grader-report`:由 `sentry-grader` 在同一个 subagent 内完成断言评审 + `grading-summary.json` + `report.html`。
- `sentry-report` 只用于独立重出报告:已有 grading 后,用户说「出报告/重新生成报告/看结果」才调用。
- 正式静态工具叫 `sentry-static`;`sentry-lint` / `sentry-trigger` / `sentry-check` 仅作为兼容命令。
- 正式发布结论为 `PASS / CONDITIONAL PASS / FAIL`;正式等级为 `S/A/B/C/D/F`;`Pass³` 和 `L0-L5` 仅作为历史/方法论资料。
- `mcp_based + smoke/quick` 默认跳过 without_skill;`mcp_based + standard/full` 默认保留可比较的 without_skill 侧,无法裸跑的单个 eval 才逐条跳过。
- 下一阶段确定性内核已提供脚本入口:`scripts/sentry_preflight.py`、`scripts/sentry_pipeline.py`、`scripts/sentry_state.py`、`scripts/sentry_gate.py`、`scripts/sentry_sync.py`、`scripts/sentry_publish.py`、`scripts/sentry_contract_lint.py`、`scripts/sentry_article_lint.py`。优先用这些脚本处理环境预检、pipeline 查询、session 状态读写、同步/发布包装、发布门禁计算和当前口径自检,不要让 LLM 手写 JSON、临场心算评分或凭感觉扫描旧术语。

更多冲突消解规则见 `references/current-contract.md`。本文件与旧 references 或旧文章冲突时,以本文件和 `references/current-contract.md` 为准。

**行为优先级(一行版)**:当前用户请求 > 当前 SKILL.md > 本次读取的 references/文件 > 本次工具输出 > 对话历史 > memory

执行本 Skill 时,遵守以下优先级规则:

**规则 1:SKILL.md > memory**
当 memory 中的行为模式与本文件冲突时,以本文件为准。

**规则 2:每次触发都是独立执行**
每次用户说「测评」都是一次全新的执行,不因之前测评过其他 Skill 就跳过读本文件、不因上次用了某种做法就照搬。memory 中关于其他 Skill 的测评记录(如「上次我用文本列表列了 23 个 skill」)不代表本次也该这么做。

**规则 3:交互方式以本文件为准**
- 选择 Skill/模式 → 必须用飞书 V2 卡片(独立 `select_static` + `markdown`)，通过 `message(action=send, kind=interactive)` 发送
- 禁止用纯文本 Markdown 表格罗列选项
- 即使 memory 中有「上次用文本列表」的记录,本次也必须用卡片
- ⚠️ 飞书卡片必须用 V2 schema 原生组件,禁止使用已废弃的 V1 `action` 容器标签

**为什么**:本 Skill 经历过多次重构(v3→v5→v7.x→v8.x),memory 中可能残留旧版行为模式。本文件 > memory。

---

# skill-eval-测评 (SkillSentry) · AI Skill 质量守门人

极简调度器:找 Skill → 选模式 → 按顺序调子工具 → 每步等确认。

---

## 平台适配层

检测方式:消息来自飞书/Telegram → `runtime="openclaw"`;其他 → `runtime="cli"`。

| 能力 | CLI / OpenCode | OpenClaw(飞书)| CI(sentry_ci.py) |
|------|---------------|----------------|-------------------|
| 子任务调用 | `Agent(task=...)` | `sessions_spawn(task=..., runTimeoutSeconds=900)` | `subprocess.run(["claude", "-p", ...])` + Anthropic SDK |
| 步骤输出 | 打印到终端 | `message(msg_type="text", ...)` | stdout/stderr + 文件产物 |
| 步骤校验 | `[sentry-proof]` + `verify_proof.py` | `validate_step.py` + milestone audit | 文件存在性检查 |
| 步骤等待 | 60s 无响应自动继续 | 等用户说「继续」(无超时)| 无等待,全自动 |
| 自动模式 | `--ci` 跳过步骤间等待 | `自动` 跳过步骤间等待 | 强制 auto,跳过所有确认 |

### ⛔ auto 模式不可跳过清单(auto-exempt)

auto 模式跳过的是「步骤间的继续确认」,以下场景即使 auto 模式也**必须阻断等待用户**:

| 场景 | 原因 | 所在步骤 |
|------|------|----------|
| MCP 预检全不可用 | 无法执行任何 real_data 用例,用户需决定配置 MCP 或降级 | Step 1 |
| real_data 测试数据采集 | AI 禁止编造单号/ID,必须用户提供或确认 | sentry-cases Step 0.3 |
| 用例设计审核 | 用户需确认用例覆盖度并决定是否补充 | sentry-cases Step 0.2 |
| 写操作/不可逆操作确认 | 安全要求 | 任意步骤 |

规则:`auto-exempt` 标记的步骤,auto 模式下仍必须展示内容并等待用户响应。

**OpenClaw 额外要求**:每步完成后将 `{msg_type, message_id, sent_at}` 写入 `session.json.milestones.step-N`。`validate_step.py` 会校验此字段。

---

## 步骤输出格式

**规则:所有面向用户的步骤输出,必须通过 `message` 工具发送。禁止直接回复文本代替 message 工具调用。**

格式:使用 `msg_type="text"`,内容用 markdown 格式化(表格、粗体、emoji)。

示例:
```
message(action=send, msg_type="text", message="✅ Step 1 初始化 (Initialization)\n• 被测 Skill (Target):xxx\n• 类型 (Type):xxx")
```

---

## 子工具

所有子工具位于本 skill 的 `tools/` 目录下,通过相对路径加载:`./tools/sentry-*/SKILL.md`

| 工具 | 路径 | 职责 |
|------|------|------|
| `sentry-static` | `./tools/sentry-static/SKILL.md` | 静态规则检查 + 触发率(TP/TN),三合一(原 check/lint/trigger),支持 --lint-only / --trigger-only |
| `sentry-cases` | `./tools/sentry-cases/SKILL.md` | 测试用例设计,输出 evals.json |
| `sentry-executor` | `./tools/sentry-executor/SKILL.md` | 用例并行执行,输出 transcript |
| `sentry-grader` | `./tools/sentry-grader/SKILL.md` | 主流程 `grader-report`:断言评审 + 汇总 + 生成 report.html |
| `sentry-report` | `./tools/sentry-report/SKILL.md` | 独立重出报告:已有 grading 后重新生成 report.html |
| `sentry-comparator` | `./tools/sentry-comparator/SKILL.md` | 盲测对比(with vs without),仅 standard/full |
| `sentry-analyzer` | `./tools/sentry-analyzer/SKILL.md` | 解盲分析 + 改进建议,仅 full |
| `sentry-sync` | `./tools/sentry-sync/SKILL.md` | 飞书 Bitable 同步(PULL/PUSH) |
| `sentry-openclaw` | `./tools/sentry-openclaw/SKILL.md` | OpenClaw 环境适配层 |

---

## 确定性内核脚本

这些脚本是 Tool-as-Code 改造的第一阶段,用于把机械流程从 Prompt 中抽出来。当前主流程仍按上方子工具执行,但涉及环境预检、状态读写和门禁计算时,优先调用脚本,不要手写等价逻辑。

| 脚本 | 用途 | 典型命令 |
|------|------|----------|
| `scripts/sentry_preflight.py` | 定位被测 Skill、读取 frontmatter、计算 hash、识别 skill_type、检查 config 和 cases 缓存 | `python scripts/sentry_preflight.py --skill <Skill名> --mode quick` |
| `scripts/sentry_pipeline.py` | 输出当前稳定口径 pipeline、下一步、步骤类型、工具和 required artifacts | `python scripts/sentry_pipeline.py plan --mode quick` |
| `scripts/sentry_state.py` | 初始化/读取/写入 `session.json`,校验 pipeline transition,写入 milestone evidence | `python scripts/sentry_state.py transition <session_dir> grader-report` |
| `scripts/sentry_gate.py` | 聚合 grading,计算 `authoritative_pass_rate`、等级、Delta 状态、IFR、否决项和最终 verdict | `python scripts/sentry_gate.py <session_dir>` |
| `scripts/sentry_ci.py` | CI 编排入口;支持 `--timeout-per-eval`,并将不可执行用例风险写入 `session.json.case_warnings` | `python scripts/sentry_ci.py --skill <Skill名> --mode smoke --timeout-per-eval 180` |
| `scripts/sentry_sync.py` | 为 `sync-pull`/`sync-push-*` 输出稳定 JSON,无飞书配置时显式记录 `skipped_no_config` | `python scripts/sentry_sync.py sync-pull --skill <Skill名> --session-dir <session_dir>` |
| `scripts/sentry_publish.py` | 为发布步骤输出稳定 JSON,生成本地报告兜底并保留 legacy `publish.py` 入口 | `python scripts/sentry_publish.py --session-dir <session_dir>` |
| `scripts/sentry_contract_lint.py` | 扫描 SkillSentry 本体是否混入旧工具名、旧指标、旧 pipeline 口径 | `python scripts/sentry_contract_lint.py --format text` |
| `scripts/sentry_article_lint.py` | 扫描文章仓库是否把历史术语误写成当前口径 | `python scripts/sentry_article_lint.py --root <文章仓库> --format text` |

执行规则:
- 可由脚本完成的状态流转和评分计算,禁止改为 LLM 手写 JSON 或口算。
- 脚本输出 JSON 是主流程和报告的事实来源;LLM 可以解释原因,但不能改写核心数值。
- 当前口径自检优先用 `sentry_contract_lint.py` / `sentry_article_lint.py`,不要只靠人工肉眼搜索。
- 如果脚本返回 `ERROR` 或 `FAIL`,必须把原始错误展示给用户,不能静默降级。

---

## 特殊命令

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry` / `验证测评` | 检查所有子工具是否存在,逐一列出 ✅/❌ |
| `lint xxx` / `检查结构` / `有没有HiL问题` | 只跑 sentry-static --lint-only |
| `测触发率` / `description 准不准` | 只跑 sentry-static --trigger-only |
| `设计用例 xxx` / `只出 cases` | 只跑 sentry-cases |
| `跑用例` / `用现有用例` | executor → grader-report |
| `出报告` / `重新生成报告` / `通过了吗` / `看结果` | sentry-report(独立重出报告,需已有 grading.json / grading-summary.json)|
| `继续` / `resume` / `从断点继续` | 读取 session.json.last_step + pipeline 数组,从 pipeline[indexOf(last_step)+1] 继续执行,跳过 Step 0/1/2 |

### 素材自动存档

用户发文件 + 说「存到 xxx 测评素材」「给 xxx 测评用的」时:
1. 提取 Skill 名称
2. 保存到 `{skill-eval-测评根目录}/inputs/<skill名>/`(保留原始文件名)
3. 回执:「✅ 已存入 inputs/<skill名>/<文件名>」

---

## Step 0: 环境预检(每次测评必须执行)

目标:确认当前运行环境会按 Skill 执行纪律调度,不会用旧 memory 或自由发挥污染测评。

执行要点:
- 读取当前 `SKILL.md` 的 `version:` 和已有 `session.json`。如果测评目标变化,只重置当前 session 临时状态,不删除 memory 或历史记录。
- 检查 AGENTS.md 是否包含 `Skill 执行纪律`。缺失时追加纪律规则;无写权限时告警但不阻断。
- Step 0 必须独立输出一条消息:`✅ Step 0 完成 | 环境已对齐 | AGENTS.md 已检查`。

详细契约见 `references/step-contracts.md` 的 step-0 定义。可代码化预检优先使用:

```bash
python scripts/sentry_preflight.py --skill <Skill名> --mode <mode>
```

---

## Step 1:找 Skill + 初始化

优先使用 `scripts/sentry_preflight.py` 定位 Skill、计算 hash、识别 `skill_type`、检查 config/cases 缓存。不要在主会话里手写等价探测逻辑。

查找优先级:
1. 用户提供路径 → 直接使用。
2. 用户只说名字 → 按 CLI/OpenClaw 默认 skill 目录查找。
3. 「测评这个 skill」→ 使用当前目录下的 `SKILL.md`。

初始化必须写入 `session.json`: `skill`、`mode`、`skill_type`、`skill_hash`、`runtime`、`started_at`、`pipeline`、`sync`。

`mcp_based` 必须做 MCP 预检。全部不可用时属于 `auto-exempt`,必须阻断并让用户选择配置 MCP 或降级;部分不可用时展示缺失项并询问是否继续。飞书配置缺失不阻断,后续 sync 步骤由 `sentry_sync.py` 记录 `skipped_no_config`。

输出:`✅ Step 1 完成 | {skill_name} | {skill_type} | {runtime} | 工作目录已创建`

---

## Step 2:智能工作流推断

### 单工具快速调用(见「特殊命令」表,跳过推断)

### 工作流推断(用户只说「测评 xxx」)

```
计算 SKILL.md MD5 → 读取 inputs_dir/rules.cache.json

**⛔ 数据隔离规则**:Step 2 只读 `rules.cache.json`(判断 hash)。禁止读 inputs/ 下的 `history.json`、`baseline.snapshot.json`、`trigger_eval.json` 等结果文件--这些只在 grader-report / 独立 sentry-report 阶段使用。主调度器提前看到历史成绩会产生锚定效应,污染后续评审判断。

  不存在               → quick(首次测评)
  hash 不匹配          → smoke(Skill 有变更)+ MARK_STALE
  hash 匹配 + cases 存在    → regression
  hash 匹配 + cases 不存在  → quick
```

**工作流模式**:

合法 pipeline 以 `scripts/sentry_pipeline.py` 为单一事实来源,不要在主会话中维护数组副本。

```bash
python scripts/sentry_pipeline.py plan --mode {mode} --format text
python scripts/sentry_pipeline.py next --session-dir {session_dir} --format text
```

预计时间:smoke ~10min, quick ~20min, regression ~5min, standard ~40min, full ~50min。

输出确认(自动模式直接开始):
```
message(action=send, message="
✅ Step 2 工作流推断 (Workflow Inference)

> **{mode} 模式 · {pipeline简写} · 预计 ~{time}**

• 推断依据:{reason}
• 被测 Skill:{name}({type})
• Pipeline:{tool_chain}
")
```

**OpenClaw 无上下文时(用户只说「测评」未指定 Skill)**:必须用飞书 V2 卡片发交互表单,禁止纯文本罗列。

执行方式:
- 扫描 `~/.openclaw/skills/` 和 `~/.openclaw/workspace/skills/` 下所有含 SKILL.md 的目录,排除 sentry-* / SkillSentry / .bak。
- 读取 frontmatter `description`,生成 `{skill_name} · {描述}` 选项。
- 发送 `message(action=send, kind=interactive)` 飞书 V2 卡片。模板见 `references/card-templates.md`;必须使用独立 `select_static`,禁止 V1 `action`、`form` 和 `button(form_action_type=submit)`。
- 卡片发送失败时,用 markdown 列表兜底,等待用户选择或回复后继续 Step 2。

### Checkpoint Resume 检测(Step 2 工作流推断完成后执行)

在 Step 2 确定模式和 pipeline 后,检测是否存在未完成的上次测评:

```
读取最近一次 session.json
如果 last_step != null 且 last_step != "publish" 且 pipeline 存在:
  → 提示用户:
    "检测到上次未完成的测评({skill} {mode},停在 {last_step}),是否从断点继续?"
  用户确认 → 从 pipeline[indexOf(last_step)+1] 开始,跳过 Step 0/1/2 的执行
  用户拒绝 → 正常从头开始新测评
```

当用户输入 `继续` / `resume` / `从断点继续` 时,直接触发 resume 逻辑,无需重新跑 Step 0/1/2。

**⛔ Resume 展示铁律(跳过执行 ≠ 跳过展示)**:必须按 pipeline 顺序逐步输出已完成步骤摘要,每步一条独立消息。禁止直接跳到当前步骤、合并多个步骤、只写 "5/12" 而不解释前置步骤结果。缓存命中或跳过时也必须展示摘要;cases 跳过要展示用例清单和断言统计。

如果用户指定 Skill 但未指定模式,只发模式选择卡片;如果 Skill 和模式都已指定,跳过卡片直接进入推断。

---

## 架构设计模式(四大支柱)

> 详细踩坑案例见 `./references/pitfall-guide.md`
> 步骤契约定义见 `./references/step-contracts.md`

本 Skill 的架构基于四个设计模式,**每次调度循环都必须遵守**:

| 模式 | 核心规则 | 违反后果 |
|------|---------|---------|
| **管道** (Pipeline) | 每步有独立输入/输出契约,步骤间不能跳线 | 产物缺失→降级,不是静默跳过 |
| **状态机** (State Machine) | session.json.last_step 是唯一流转依据,不靠上下文记忆 | 非法转移→abort+告警 |
| **降级兜底** (Graceful Degradation) | 超时/失败有 L1→L2→L3 三级降级 | 标注 [DEGRADED] 但不终止 |
| **幂等** (Idempotent) | 同 hash+同模式+同天 → 提示复用 | 跳过重复执行 |

**合法状态转移表**(违反即 abort):
```
idle → step-0 → step-1 → step-2 → [pipeline per mode] → publish → idle
```

**各模式的合法 pipeline**:以 `scripts/sentry_pipeline.py` 和 `references/current-contract.md` 为准。Step 2 推断完成后写入 `session.json.pipeline`,Step 3 严格按数组顺序执行;不在当前模式 pipeline 中的步骤视为不存在。

**降级触发条件**:
- subagent 900s 未完成 → L2(批量快速模式)
- L2 也超时 → L3(纯统计,标注 [DEGRADED-L3])
- 产物缺失率 > 20% → 触发降级而非继续

---

## Step 3:无状态调度循环

### 核心原则:主会话只调度,不执行

主会话永远只做三件事:**派活、验收、通知用户**。所有复杂步骤全部委派给 subagent 执行。主流程报告生成由 `grader-report` 完成;`sentry-report` 只在独立重出报告场景调用。

**⛔ 主调度器铁律(每轮必须遵守)**:
1. 每轮开始必须 read session.json(不靠记忆)
2. Step 0、1、2 各自发独立消息(禁止合并)
3. 缓存命中时展示完整摘要(见下方自约束清单)
4. 发消息前过自约束清单(任何一项未过 = 不发送)
5. 每步完成后写 session.json.evidence(files_read + artifacts_created)

原因:主会话经历多轮 yield/resume 后上下文疲劳,会导致跳步、简化、凭记忆执行。委派给 subagent 可结构性避免此问题。

### 每轮调度流程(无状态,不靠上下文记忆)

```
1. 读 session.json → 取 last_step
2. 调用 sentry_pipeline.py next 或复用其定义 → 确定 next_step
3. 读取 next_step 对应子工具的 SKILL.md(必须 read,不能凭记忆)
4. spawn subagent(task = SKILL.md 内容 + session 数据 + 输入文件路径)
5. 写入 active-pipeline.json(见下方「Pipeline 持久化与自动恢复」)
6. sessions_yield 等回调(⛔ 禁止 stop,必须 yield)
7. resume 后验收产物(检查文件是否存在)
8. 向用户展示结果 + 更新 session.json last_step
9. 删除 active-pipeline.json
10. 回到 1(不靠记忆,靠文件状态)
```

### Pipeline 持久化与自动恢复

长耗时 subagent(executor、comparator、analyzer、grader-report)必须在 spawn 后、yield 前写入 `~/.openclaw/data/skill-eval/active-pipeline.json`。恢复时从 checkpoint 的 `next_step` 继续,不重跑 Step 0/1/2。subagent 验收通过、publish 完成或用户取消时清理 checkpoint。

### pipeline 定义与发布

- 步骤定义、子工具、required artifacts:调用 `python scripts/sentry_pipeline.py describe <step>`。
- 状态流转:调用 `python scripts/sentry_state.py transition <session_dir> <step>`。
- sync 步骤:调用 `python scripts/sentry_sync.py <sync-step> --session-dir <session_dir>`;无配置必须记录 `skipped_no_config`。
- gate:调用 `python scripts/sentry_gate.py <session_dir>`。
- publish:优先调用 `python scripts/sentry_publish.py --session-dir <session_dir>` 输出 `publish-result.json`;需要交互式飞书上传时再调用 legacy `scripts/publish.py`。

`executor-without` 规则:`mcp_based + smoke/quick` 默认 N/A;`mcp_based + standard/full` 保留可比较 baseline,无法裸跑的单个 eval 才逐条跳过。

### 主调度器自约束检查清单(每次发消息前必须过)

主调度器(即我自己)在每次向用户发送消息前,必须检查:

```
☐ 本次是否 read 了 SKILL.md 或相关 references?(凭记忆 = 违规)
☐ 缓存命中时,是否展示了完整摘要(不是一行带过)?
☐ Step 0/1/2 是否各自独立发送(不合并)?
☐ 消息内容是否含具体数据(不是"完成"两字)?
☐ session.json 是否记录了 evidence(files_read + artifacts_created)?
☐ Resume 时是否逐步展示了已完成步骤的摘要?(跳过执行 ≠ 跳过展示)
☐ 进度条(N/M)出现前,前面每一步是否都有对应消息?
```

**任何一项未通过 = 不发送,先补做。**

**缓存命中时的最低展示要求**:
- check 缓存: 必须展示静态规则检查结果 + TP/TN 具体数值 + 来源 session
- cases 缓存: 必须展示完整用例表格(17 行,每行含 ID/类型/用例名/断言详情)
- 禁止用 "hp:5 edge:3" 这种一行摘要代替

---

### 产物验收(每步 subagent 完成后,主会话执行)

> 完整输出格式见 `./references/output-format.md`

subagent 完成 → 主会话按顺序执行 4 个动作(不可跳过、不可简化):

| 动作 | 内容 | 工具 |
|------|------|------|
| 1 | 读 progress.json | `exec: cat {workspace}/progress-run-{R}.json` |
| 2 | 检查产物完整性(缺失率>20% → 触发降级) | `exec: 遍历 eval-*/outputs/` |
| 3 | 向用户发送 per-eval 结果表(格式见 output-format.md) | `message(action=send, msg_type="text")` |
| 4 | 更新 session.json.last_step + milestones | `exec: python3 更新 JSON` |

**⛔ 关键约束**:
- 动作 3 **必须用 message(action=send)**,禁止纯文本回复
- 输出格式要求**必须注入 subagent task prompt**(不能只写在此处"期望被记住")
- 跳过任何动作 = 用户有权要求重跑
- 所有模式(smoke/quick/standard/full/regression)适用

### auto-exempt 步骤的特殊处理

cases 步骤含 auto-exempt 环节(数据采集、用例审核),需主会话与用户交互:
1. subagent 完成需求分析 + 用例设计 → 写入文件
2. 主会话读取文件 → 展示给用户 → 等待确认/补充
3. 用户确认后继续下一步

### 其他规则

- **缓存复用**:SKILL.md hash 一致 + 产物存在 → 复用,标注「⚡ 缓存命中(上次 {date})」

**缓存跳过展示规则**(跳过不等于静默,必须展示复用内容摘要):
- check 缓存命中:展示静态规则检查结果 + 触发率 TP/TN + 来源 session
- cases 缓存命中:展示按类型分组的用例清单表格 + 断言统计(exact/semantic/existence)
- 禁止只输出"缓存命中,跳过"
- **快速失败**(quick 模式):grader-report 评审前几个 eval 后通过率 < 20% → 询问是否继续
- **透明执行**:每步完成后必须展示结果,自动模式也不例外
- **⛔ 禁止**:主会话直接执行任何子工具的业务逻辑;凭记忆生成报告/用例/评分;手写用例替代 sentry-cases
- **⛔ 所有模式必须 spawn sentry-cases subagent**:禁止主会话自己编写 evals.json。但流程深度按模式分级(见下方「模式分级控制」)
- **⛔ 报告产出按模式分级**:详见 `./references/step-contracts.md` 的 publish 分级表

### 模式分级控制

> 详见 `./references/mode-levels.md`

sentry-cases subagent 的 task 中必须注入 `mode` 参数,子工具根据 mode 自动调整流程深度。

### 进度可见性规范

**原则**:用户不应在任何时刻感到「黑盒」。

- 每个 step 完成后发一条独立 message,不是最后一起发
- Step 0、Step 1、Step 2 必须各自独立发送,禁止合并
- grader-report 结果卡片必须包含 per-assertion 详情(smoke/quick 全量,standard/full 只展示 failed)
- 缓存命中时必须展示内容摘要,禁止只写"缓存命中,跳过"
- **进度摘要**:每完成一个 pipeline 步骤后,在消息末尾附加进度条:`[██████░░░░] 3/5 steps`(用 █ 和 ░ 字符模拟)
- 每个 pipeline 步骤启动后立即发送「正在执行」通知,说明当前步骤正在检查什么、完成后进入哪一步。步骤说明从 `scripts/sentry_pipeline.py describe <step>` 和子工具职责表生成。

---

## Sync / Gate / Publish

- sync 是正式 pipeline 步骤,不可静默跳过。调用 `scripts/sentry_sync.py`;无 `config.json` 时返回并写入 `skipped_no_config`。
- gate 仅 standard/full 强制执行。调用 `scripts/sentry_gate.py` 或复用其 `build_gate()` 输出。
- publish 调用 `scripts/sentry_publish.py` 生成稳定本地结果;需要飞书上传/所有权转让时再走 legacy `scripts/publish.py`。
- Pipeline 准出标准见 `references/step-contracts.md`;session schema 见 `references/session-json-schema.md`;飞书细节见 `references/feishu-sync.md`。

Token 计量:每步 spawn 前后读取 `session_status().usage.total_tokens`,差值写入 `session.json.cost[step_name]`,publish 时汇总 `cost.total`。

*v9.0.0 · 契约收敛版:统一 grader-report、without_skill/Delta 规则、当前术语口径、配置卫生与文档入口 · 2026-05-14*

<!-- 旧版本历史已移至 CHANGELOG.md -->

---

### subagent task prompt 标准注入清单

spawn 每个 subagent 时,task prompt **必须**包含以下内容(不可省略):

```
## must_read(不读不得执行)
1. [文件路径1]
2. [文件路径2]
(从 step-contracts.md 的 must_read 字段复制)

## 输出路径
{workspace_dir}/[具体路径]

## completion message 格式
[从 output-format.md 复制对应步骤的格式要求]

## Evidence 要求
完成后你的最终输出必须包含:
- 你实际 read 了哪些文件(路径列表)
- 你创建了哪些产物(路径列表)
- 验证结果摘要
```

⛔ 不含上述内容的 task prompt = 违规。主调度器自约束清单第 1 项检查此项。
