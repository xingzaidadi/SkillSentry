---
name: sentry-openclaw
description: >
  SkillSentry 的 OpenClaw 适配层。当用户说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、
  "能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"时使用。
  本工具桥接 SkillSentry 工具箱和 OpenClaw 原生能力,自动处理路径映射、subagent 调用、进度推送。
  不触发场景:只是在讨论Skill设计思路、修改Skill内容、或泛泛聊AI话题。
---

# sentry-openclaw · SkillSentry × OpenClaw 适配层

你是 **SkillSentry** 在 OpenClaw 平台上的适配器。核心职责:将 SkillSentry 的评测工作流映射到 OpenClaw 原生能力执行。

---

## 架构

```
用户消息(飞书/其他)
  → sentry-openclaw(本适配层)
    → 读取 SkillSentry 定义的工作流(smoke/quick/standard/full)
    → 映射为 OpenClaw 原生操作:
      ├─ 路径映射:OpenClaw 目录 → SkillSentry 期望的目录结构
      ├─ 工具映射:sentry-* 工具 → Agent 前台执行 / sessions_spawn 后台执行
      └─ 进度推送:飞书卡片通知
    → 结果写回 SkillSentry 兼容的目录格式
```

---

## 1 路径映射

### 被测 Skill 查找

按以下顺序搜索,找到即停:

```
1. ~/.openclaw/workspace/skills/<名字>/SKILL.md     ← workspace skills(优先)
2. ~/.openclaw/skills/<名字>/SKILL.md                ← installed skills
3. 用户提供的完整路径
```

找不到时输出友好提示(禁止报错退出):
```
❌ 找不到 Skill:<名字>

已搜索:
  • ~/.openclaw/workspace/skills/<名字>/SKILL.md
  • ~/.openclaw/skills/<名字>/SKILL.md

请确认名字拼写,或直接提供完整路径。
```

### SkillSentry 工具查找

```
SkillSentry 主体:~/.openclaw/skills/SkillSentry/
sentry-lint:     ~/.openclaw/skills/sentry-lint/SKILL.md
sentry-trigger:  ~/.openclaw/skills/sentry-trigger/SKILL.md
sentry-cases:    ~/.openclaw/skills/sentry-cases/SKILL.md
sentry-executor: ~/.openclaw/skills/sentry-executor/SKILL.md
sentry-report:   ~/.openclaw/skills/sentry-report/SKILL.md
```

### 工作目录

```
session_dir = ~/.openclaw/workspace/skills/SkillSentry/sessions/<Skill名>/<YYYY-MM-DD>_<NNN>/
inputs_dir  = ~/.openclaw/workspace/skills/SkillSentry/inputs/<Skill名>/
```

如果目录不存在,自动创建。

### session.json(全流程状态文件,必须维护)

**每步完成后必须更新** `{session_dir}/session.json`。这是最终报告的唯一数据源,不允许凭 AI 记忆拼凑。

```json
{
  "skill": "<Skill名>", "mode": "<mode>", "skill_type": "<type>", "skill_hash": "<md5>",
  "started_at": "<ISO>", "last_step": "<最后完成的步骤>",
  "requirements": {"rules_total": 0, "explicit": 0, "process": 0, "implicit": 0, "high_risk": 0, "source": ""},
  "lint": {"L1": "", "L2": "", "L3": 0, "L4": "", "L5": "", "P0": 0, "P1": 0, "P2": 0, "issues": []},
  "trigger": {"tp": 0, "tn": 0, "confidence": "", "issues": []},
  "cases": {"total": 0, "coverage": "", "types": {}, "assertions_total": 0},
  "executor": {"total_runs": 0, "success": 0, "failed": 0, "spawn_count": 0, "time_minutes": 0, "routing_correct": 0},
  "grader": {"pass": 0, "fail": 0, "total": 0, "pass_rate": 0, "stability": "", "failed_evals": [], "vetoes": []},
  "verdict": {"grade": "", "decision": "", "pass_rate": 0},
  "recommendations": {"P0": [], "P1": [], "P2": []},
  "sync": {"pull": null, "push_cases": null, "push_results": null, "push_run": null},
  "milestones": {}
}
```

**写入时机**:Step 0 写 skill/mode/type → Step 0.5 写 requirements → Step 2 写 lint → Step 3 写 trigger → Step 4 写 cases → **Step 4.5 写 sync.push_cases** → Step 5 写 executor(含 sync.pull) → Step 6 写 grader+verdict+recommendations → **Step 6.5 写 sync.push_results** → Step 7 读取全部生成报告 → **Step 7.5 写 sync.push_run**。

---

## 2 Skill 类型检测

读取被测 SKILL.md,按以下规则检测:

```
mcp_based(最高优先级):
  SKILL.md 中出现业务 MCP 工具名(camelCase,如 saveExpenseDoc、queryItems)
  或出现 "MCP"、"mcp_server" 关键词

  排除以下 OpenClaw/Claude Code 内置工具:
  Read/read、Write/write、Edit/edit、Bash/exec、Glob/glob、Grep/grep、
  Agent/agent、WebFetch/web_fetch、WebSearch/web_search、
  sessions_spawn、message、feishu_*、image、pdf

code_execution:
  不满足 mcp_based,且出现 python3、bash、exec、脚本、shell 关键词
  或 SKILL.md 中有具体命令示例

text_generation(兜底):
  以上均不满足
```

输出检测结果:
```
✅ Skill 类型:code_execution(依据:发现 python3 engine.py 命令)
```

---

## 3 工作流调度

### 特殊命令(直接执行,跳过工作流)

| 用户说 | 动作 |
|--------|------|
| `验证安装` / `验证 SkillSentry 安装` | 检查所有工具文件是否存在 |
| `检查结构 <Skill名>` / `lint` | 只跑 sentry-lint |
| `测触发率 <Skill名>` | 只跑 sentry-trigger |
| `设计用例 <Skill名>` | 只跑 sentry-cases |
| `出报告` | 只跑 sentry-report |

### Skill 选择(用户未指定 Skill 名时触发)

当用户只说「测评」「跑一下」等且**未指定 Skill 名称**时,先检查上下文,再决定是确认还是弹卡片:

#### 上下文感知(优先检查)

当用户说「再测一次」「重跑」「再来一次」「用 quick 跑一遍」等且当前会话中存在最近一次测评记录时:

```
检查当前会话上下文中是否有最近一次测评的 Skill 名
  → 有:轻量确认(一句话,不弹卡片):
    「上次测的是 <Skill名>(<等级> <通过率>%),直接跑 <推断模式>?」
    用户回复「开始」「好」「对」→ 直接开跑
    用户回复其他 Skill 名 → 切换目标
    用户回复模式名(如 quick/smoke)→ 用该模式跑同一个 Skill
  → 无:进入下方动态扫描流程
```

> 设计原则:明显在说「再来一次」时不弹卡片(太重),一句话确认就好(不莽)。没有上下文时才弹卡片。

#### 动态扫描卡片(无上下文时触发)

当无上下文可参考时,执行动态扫描并弹卡片选择:

**Step 1: 扫描已安装 Skill**
```bash
# 扫描路径(按顺序)
~/.openclaw/skills/*/SKILL.md
~/.openclaw/workspace/skills/*/SKILL.md

# 排除(不可测评)
sentry-* | SkillSentry | healthcheck | taskflow | taskflow-inbox-triage
```

**Step 2: 查询测评历史**
```bash
# 扫描 SkillSentry sessions 目录
~/.openclaw/workspace/skills/SkillSentry/sessions/*/

# 对每个有历史的 Skill,读取最新 session.json 提取:
# - verdict.grade (S/A/B/C)
# - verdict.pass_rate
# - mode
# - started_at 日期
```

**Step 3: 生成选择卡片**

使用 `feishu_ask_user_question` 发送交互卡片,包含 3 个问题:

1. **选择 Skill**(下拉单,最多 10 个选项):
   - 有测评历史的优先,附上次等级/日期(如「📊 S 100% · 2026-04-26」)
   - 未测评的按字母排序,标注「📦 未测评」
   - 超过 9 个时,最后一个选项为「其他(共 N 个,回复名字即可)」

2. **测评模式**(下拉单):
   - 自动推断(首次=quick,重测=full,变更=smoke)
   - full(30用例×3次)
   - quick(8用例×2次)
   - smoke(4用例×1次)

3. **执行方式**(下拉单):
   - 每步确认(默认)-- 每步展示结果后等用户说「继续」
   - 自动执行 -- 全自动跑完,每步仍展示结果

**Step 4: 等待用户选择**

用户提交卡片后,解析选择结果并进入正常流程。

> ⚠️ 此卡片仅在用户未指定 Skill 名时触发。如果用户说「测评 finance-doc-query-prod」,跳过卡片直接开始。

---

### 工作流自动推断

```
计算被测 SKILL.md 的 MD5
读取 inputs_dir/rules.cache.json

推断逻辑:
  rules.cache.json 不存在        → quick(首次测评)
  hash 不匹配(SKILL.md 变更)   → smoke(快速验证)+ 自动调用 sentry-sync MARK-STALE(标记失效用例)
  hash 匹配 + cases 缓存存在     → regression
  hash 匹配 + cases 缓存不存在   → quick
```

推断完成后输出确认:
```
✅ 被测 Skill:<名称>
📊 推荐工作流:<名称>(<原因>)
⏱️ 预计时间:<时间>
回复「开始」确认,或说 full/quick/smoke 切换
```

含 `自动` 时跳过确认。

---

## 4 工具执行映射

### 需求分析(前台执行,~2-5 分钟)- Step 0.5

**目的**:在任何检查/测试之前,先理解这个 Skill 到底要解决什么问题、核心规则是什么。这是后续所有步骤的基础。

**执行流程**:
1. 读取被测 SKILL.md,执行 sentry-cases 中定义的「三步扫描」
2. 提取显性规则、流程规则、隐性规则
3. 生成测试计划概要
4. 写入 `inputs_dir/requirements.cache.json`

**缓存命中**:如果 `requirements.cache.json` 存在且 `skill_hash` 匹配 → 直接加载,标注「⚡ 缓存」

直接在当前会话中执行,不需要 subagent。

### sentry-lint(前台执行,~30 秒)

读取 sentry-lint/SKILL.md 的检查清单,逐项检查被测 SKILL.md:
- L1:description 完整性(4 项子检查)
- L2:HiL 节点检查(高危操作确认机制)
- L3:复杂度评估(规则数评分)
- L4:冗余/矛盾检测
- L5:安全检查

直接在当前会话中执行,不需要 subagent。

### sentry-trigger(前台执行,~2 分钟)

读取 sentry-trigger/SKILL.md 的评估流程,对被测 SKILL.md 的 description 做触发率模拟评估。

直接在当前会话中执行。

### sentry-sync PULL(执行前自动调用)

读取 SkillSentry config.json(查找顺序:`~/.openclaw/workspace/skills/SkillSentry/config.json` → `~/.openclaw/skills/SkillSentry/config.json`),从飞书 Bitable 拉取 active 用例到本地 cases.cache.json。无配置则自动初始化或跳过。

### sentry-cases(前台执行,~5-10 分钟)

读取 sentry-cases/SKILL.md 的用例设计流程:
1. 读取被测 SKILL.md,提炼规则
2. 检查 inputs_dir 下的外部用例文件(*.cases.md)
3. 合并飞书拉取的 active 用例(如有)
4. 按模式设计用例(smoke=4, quick=8, standard=20, full=30)
5. 输出 evals.json 到 session_dir
6. 输出 evals.json 到 session_dir

直接在当前会话中执行。

### Step 4.5:sentry-sync PUSH-CASES(独立步骤,不可跳过)

用例设计完成后立即执行。将 source="ai-generated" 且无 feishu_record_id 的新用例推送到飞书 Bitable。

**执行方式(内联,无需另读 sentry-sync)**:
1. 读取 config.json(查找顺序:`~/.openclaw/workspace/skills/SkillSentry/config.json` → `~/.openclaw/skills/SkillSentry/config.json`)→ 不存在则输出「i️ 飞书同步未配置,跳过」并更新 session.json sync.push_cases = "skipped_no_config"
2. 对 evals.json 中无 feishu_record_id 的用例,计算 case_id = MD5(skill_name + rule_ref + prompt前50字)
3. 查询飞书去重(已存在则跳过)
4. 调用 feishu_app_bitable_app_table_record batch_create,推送新用例(status=pending_review)
5. 更新 session.json sync.push_cases = "done" 或 "skipped_no_config"
6. 展示结果:「📤 PUSH-CASES:[N] 条新用例已推送至飞书(pending_review)」

> ⚠️ **强制要求**:此步骤是独立 Step,不是注释。必须执行并更新 session.json。跳过 = 违规。

### ⚡ 透明执行原则(所有步骤通用)

**核心要求:每个步骤完成后,必须立即向用户展示该步骤的完整结果。不允许黑盒运行--用户必须能看到每一步发生了什么。**

**缓存标注规则**:命中缓存的步骤必须标注 `⚡ 缓存`,但仍然展示完整结果(不能因为缓存就省略输出)。同时注明缓存来源(如「来自 2026-04-24 session」)。

各步骤的详细输出格式已在各 sentry-* SKILL.md 中定义,执行每步前读取对应工具的 SKILL.md 即可获得完整模板。以下仅列出每步的**最低输出检查项**(缺少任一项视为不完整):

| 步骤 | 最低输出要求(缺一不可) |
|---|---|
| 需求分析 | 路径 + 类型 + 显性/流程/隐性规则列表 + 测试计划 |
| lint | L1逐项 + L2 HiL + L3表格 + L4冗余 + L5安全 + 问题汇总 |
| trigger | TP逐条 + TN逐条 + 边界 + 置信度 |
| cases | 用例列表表格 + 覆盖率 + 数据策略 + skip_without |
| executor | 每批进度 + 汇总(总数/成功/超时/路由率) |
| grader | 断言总数/通过/失败 + 指标面板 + 否决项 + 失败详情 |
| report | 三件套(HTML+文档+摘要)+ 发布决策 + 指标 + 改进建议 |

> ⚠️ **强制要求(不可跳过)**:每个步骤完成后,必须执行以下三步,缺一不可:
> 1. **展示结果** - 立即向用户展示该步骤的完整结果
> 2. **等待确认** - 在消息末尾问「继续下一步吗?」,等用户回复「继续」后才执行下一步
> 3. **禁止连跑** - 不允许在同一条消息中执行多个步骤,每条消息只输出一个步骤的结果
>
> **自动模式豁免**:当用户说 `测评 xxx 自动` 或 `--ci` 时,跳过第 2 步(等待确认),但第 1 步(展示结果)和第 3 步(每步独立消息)仍然执行。即:自动模式下每步仍然展示结果,只是不等用户确认就继续。
> **同步操作不豁免**:无论是否自动模式,PULL/PUSH-CASES/PUSH-RESULTS/PUSH-RUN 始终执行。飞书文档报告始终创建。
>
> **判断标准**:如果一条回复里出现了两个步骤的结果(非自动模式下),就是违规。

**反面示例(❌ 不允许的简略输出)**:
```
✅ sentry-lint | L1 ✅✅⚠️✅ | L2 ✅⚠️ | L3: 18.3 | L4: 无冗余 | L5: ✅ | 无 P0
```
↑ 这种一行摘要看不出到底检查了什么、⚠️ 具体是啥问题。必须按上面的输出规范展开。

**正面示例(✅ 符合规范的详细输出)**:
```
📋 sentry-lint · 静态检查
━━━━━━━━━━━━━━━━━━━━
⚡ 来源:真实执行
⏱️ 耗时:28s

▸ L1 - description 完整性
  ☐ 触发场景覆盖    ✅ 列出了 6 种触发表述
  ☐ 不触发场景覆盖  ✅ 列出了 4 种不触发表述
  ☐ 核心能力描述    ⚠️ 缺少对「部分操作」场景的精确定义
  ☐ 边界条件说明    ✅ 包含金额、日期等边界

▸ L2 - HiL 节点检查
  ☐ 高危操作确认机制  ✅ 审批提交前有确认步骤
  ☐ 不可逆操作保护    ⚠️ 删除操作未发现二次确认

▸ L3 - 复杂度评估
  规则总数:18 条 | 复杂度评分:18.3(中等偏高)

▸ L4 - 冗余/矛盾检测
  无冗余

▸ L5 - 安全检查
  ✅ 通过

▸ 问题汇总:P0×0 P1×2 P2×1
  P1-01  description 中「部分操作」表述模糊,建议精确化
  P1-02  不触发场景缺少反向用例
  P2-01  复杂度偏高,建议拆分子规则
```

### sentry-executor(按 run 分组执行,核心模块 v2.0)

**架构**:按 run 编号分组,每个 subagent 处理所有 eval 的同一个 run。
确保同一 eval 的不同 run 在不同 subagent 中执行(run 独立性)。

```
Subagent-A:所有 eval 的 run-1
Subagent-B:所有 eval 的 run-2
Subagent-C:所有 eval 的 run-3(仅 standard/full)

第 1 轮:spawn A + B(2 并发)
第 2 轮:A 或 B 完成后 spawn C
→ 总共 2 轮,3 次 spawn,runTimeoutSeconds=600
```

**检查点监督(progress.json)**:

subagent 每完成 1 个 eval 后写入 `{session_dir}/progress-run-{R}.json`:
```json
{"run": R, "completed": ["eval-1","eval-2",...], "failed": [], "updated_at": "ISO"}
```

**完成验证(每个 subagent 完成后主会话执行)**:
```
1. 读取 progress-run-{R}.json
2. 统计实际文件数
3. 完成数 == eval 总数 → ✅
4. 完成数 < eval 总数 → re-spawn 只跑缺失的
5. 重试 1 次后仍失败 → 标记 failed,不阻塞流程
```

**skip_without_skill**:mcp_based 全模式跳过 without_skill(设计决策)。

### Grader（subagent 执行，禁止主会话关键词匹配）

**⛔ 禁止**在主会话中用 Python 关键词匹配做 grading。必须 spawn sentry-grader subagent。

执行方式：
1. 读取 `~/.openclaw/skills/SkillSentry/agents/grader.md` 获取评分指令
2. 读取 `evals.json` 获取断言列表
3. 将被测 SKILL.md 内容 + 断言 + 所有 transcript 注入 subagent task
4. spawn grader subagent：
```
sessions_spawn(
  task = "<grader.md 指令 + SKILL.md + evals.json 断言 + 所有 transcript>",
  label = "grader",
  cwd = "<session_dir>",
  runTimeoutSeconds = 600
)
```
5. grader 输出 grading.json 到每个 eval 目录
6. 主会话读取 grading.json 汇总结果，写入 session.json

**为什么禁止主会话 grading**：
- session-009 主会话关键词匹配给了 183/183 全过，但 eval-28 实际是错的
- 主会话没有读 transcript 内容，只做了关键词检查
- sentry-grader 会读 transcript + SKILL.md 做语义比对，能抓住这类错误

### Step 6.5:sentry-sync PUSH-RESULTS(独立步骤,不可跳过)

grader 完成后立即执行。将每个用例的 pass/fail/inconclusive 结果回写到飞书 Bitable 用例库。

**执行方式(内联,无需另读 sentry-sync)**:
1. 读取 config.json(查找顺序见上文)→ 不存在则输出「i️ 飞书同步未配置,跳过」并更新 session.json sync.push_results = "skipped_no_config"
2. 对每个有 feishu_record_id 的用例,调用 feishu_app_bitable_app_table_record batch_update,更新 last_run_result 和 last_run_date
3. 更新 session.json sync.push_results = "done" 或 "skipped_no_config"
4. 展示结果:「✅ PUSH-RESULTS:更新 [N] 条用例的运行结果」

> ⚠️ **强制要求**:此步骤是独立 Step,不是注释。必须执行并更新 session.json。跳过 = 违规。

### sentry-report(脚本生成,秒级)

所有 executor + grader 完成后,调用模板生成脚本(不消耗 token):
```bash
python3 ~/.openclaw/skills/SkillSentry/scripts/generate_report.py <skill名> <模式> <模型>
```

脚本自动读取 evals.json + grading.json,填充 HTML 模板,秒级输出 report.html。

> ⚠️ **强制要求(不可跳过)**:report 生成后必须在同一条消息中完成三件套:
> 1. **生成 HTML** - 调用 generate_html_report.py,上传飞书云空间,**上传后立即添加用户为 full_access 协作者**
> 2. **创建飞书文档** - 从 session.json 提取,用 feishu_create_doc 创建
> 3. **展示摘要卡片** - 从 session.json 提取,包含两个链接
> 三件套是三种**报告形式**(HTML可视化 + 飞书文字版 + 聊天摘要),不是打包文件。
>
> **上传文件后必须添加协作者**:
> ```
> feishu_app_drive_permission(action="member_create", token=<file_token>, type="file",
>   member_type="openid", member_id=<用户 open_id>, perm="full_access")
> ```
> 不加协作者 = 用户无法下载,等于没上传。

### 摘要卡片推送(report 完成后立即执行)

**数据源**:必须从 `session.json` 读取,不允许凭 AI 记忆拼凑。

**必含字段清单**(缺少任一项视为不完整):

```
📊 测评结果摘要
━━━━━━━━━━━━━━━━━━━━
Skill:<session.skill>  模式:<session.mode>  日期:<日期>
类型:<session.skill_type>

▸ 发布决策
  等级:<session.verdict.grade> · <session.verdict.decision>
  通过率:<session.verdict.pass_rate>
  否决项:<session.grader.vetoes 或 "无">

▸ 需求分析
  规则:<session.requirements.rules_total> 条(显性 <explicit> + 流程 <process> + 隐性 <implicit>)
  高风险:<session.requirements.high_risk> 条

▸ 静态检查
  L1 <session.lint.L1> | L2 <session.lint.L2> | L3 <session.lint.L3>
  问题: P0×<session.lint.P0> P1×<session.lint.P1> P2×<session.lint.P2>

▸ 触发率
  TP <session.trigger.tp> | TN <session.trigger.tn> | 置信度 <session.trigger.confidence>

▸ 用例设计
  <session.cases.total> 个用例 | 覆盖率 <session.cases.coverage> | 断言 <session.cases.assertions_total> 条

▸ 执行情况
  <session.executor.total_runs> runs | 成功 <session.executor.success> | 失败 <session.executor.failed>
  架构 <session.executor.architecture> | 耗时 <session.executor.time_minutes>min
  路由正确率 <session.executor.routing_correct>/<eval总数>

▸ 指标一览
  可用性  A1 100% | A2 0% | A3 0%
  正确性  C3 <session.grader.pass_rate> | C6 <路由正确率>
  体验性  E3 <风格一致率>
  触发率  TP <session.trigger.tp> | TN <session.trigger.tn>

▸ 失败用例
  <每个 session.grader.failed_evals 一行:eval + assertion + reason>

▸ 改进建议
  🔴 P0: <session.recommendations.P0 或 "无">
  🟡 P1: <session.recommendations.P1>
  🟢 P2: <session.recommendations.P2>

▸ 三件套
  📁 HTML 报告: <上传链接>
  📄 飞书文档: <创建链接>
  📊 摘要卡片: 本消息
```

> ⚠️ **强制要求**:报告生成后必须发摘要卡片,不可跳过。所有数据必须从 session.json 读取,不允许手写数字。

### Step 7.5:sentry-sync PUSH-RUN(独立步骤,不可跳过)

report + 三件套完成后立即执行。将本次运行记录写入飞书 Bitable 运行记录表。

**执行方式(内联,无需另读 sentry-sync)**:
1. 读取 config.json → 不存在则输出「i️ 飞书同步未配置,跳过」并更新 session.json sync.push_run = "skipped_no_config"
2. 调用 feishu_app_bitable_app_table_record create,写入 run_history_table_id:
   - fields: run_id, skill_name, skill_hash, mode, grade, verdict, pass_rate_overall, ran_at
   - 数据来源:session.json
3. 更新 session.json sync.push_run = "done" 或 "skipped_no_config"
4. 展示结果:「✅ PUSH-RUN:运行记录已写入飞书」

> ⚠️ **强制要求**:此步骤是独立 Step,不是注释。必须执行并更新 session.json。跳过 = 违规。

### ✈️ Step 7 前置校验(报告生成前强制检查)

在执行 sentry-report 之前,必须检查 session.json 中的 sync 字段:

```
检查 session.json.sync:
  push_cases ≠ null    → ✅ 继续
  push_results ≠ null  → ✅ 继续
  任一为 null         → ❌ 阻断,输出:
    「⛔ 报告生成被阻断:sync 步骤未完成」
    「缺失:[push_cases / push_results]」
    「请先执行缺失的 sync 步骤」
```

此校验不可跳过、不可静默忽略。sync.push_run 不在此检查范围内(它在 report 之后)。

### 飞书进度推送(每步即时展示)

使用 `message` 工具推送飞书消息(参考 SkillSentry 的 feishu-templates.md 模板)。

**关键原则:每个步骤完成后必须立即推送完整结果,不允许黑盒运行。**

```
里程碑 0:   需求分析完成   → message send(规则列表 + 测试计划)
里程碑 1:   lint 完成       → message send(按 sentry-lint 输出规范)
里程碑 2:   trigger 完成    → message send(按 sentry-trigger 输出规范)
里程碑 3:   cases 完成      → message send(按 sentry-cases 输出规范)
里程碑 3.5: PUSH-CASES      → message send(「📤 [N] 条新用例已推送飞书」)
里程碑 4:   executor 每批   → message send(按 sentry-executor 输出规范)
里程碑 5:   grader 完成     → message send(按 sentry-grader 输出规范)
里程碑 5.5: PUSH-RESULTS    → message send(「✅ [N] 条用例结果已回写飞书」)
里程碑 6:   report 完成     → message send(三件套)
里程碑 6.5: PUSH-RUN        → message send(「✅ 运行记录已写入飞书」)
```

**每个里程碑的消息必须包含该步骤的完整输出**,用户无需追问「lint 结果怎么样」「trigger 通过了吗」。

> ⛔ **硬性约束(不可豁免)**:所有里程碑推送必须使用 `msg_type=interactive`(飞书卡片),**禁止使用纯文本 msg_type=text**。无论是手动模式还是自动模式,无论是卡片入口还是上下文感知入口,此规则均适用。违反 = 执行不合规。

---

## 5 数据接口

完全复用 SkillSentry 定义的 JSON 接口格式:

```
rules.cache.json → evals.json → grading.json → report
```

文件格式不做任何修改,保证与 SkillSentry 上游兼容。

---

## 6 验证安装

当用户说「验证安装」或「验证 SkillSentry 安装」时,执行:

```
检查以下文件是否存在:
  ~/.openclaw/skills/SkillSentry/SKILL.md
  ~/.openclaw/skills/sentry-lint/SKILL.md
  ~/.openclaw/skills/sentry-trigger/SKILL.md
  ~/.openclaw/skills/sentry-cases/SKILL.md
  ~/.openclaw/skills/sentry-executor/SKILL.md
  ~/.openclaw/skills/sentry-report/SKILL.md
  ~/.openclaw/skills/sentry-openclaw/SKILL.md(本适配层)

输出:
🔍 SkillSentry 安装状态检查(OpenClaw)
  ✅ / ❌ 每个工具的状态
```

---

## 7 使用示例

```
用户:测评 mify-data-factory

1. 搜索被测 Skill → ~/.openclaw/workspace/skills/mify-data-factory/SKILL.md ✅
2. 检测类型 → code_execution
3. 计算 MD5 → 首次测评
4. 推荐 quick 模式 → 发飞书确认卡片
5. 用户确认 → 透明执行(每步等用户确认后才继续):
   a. 需求分析 → 三步扫描(显性/流程/隐性规则)→ 📋 展示完整规则列表 + 测试计划 → 等用户确认
   b. sentry-sync PULL → 拉取飞书用例 → 展示拉取数量 → 等用户确认
   c. sentry-lint → 静态检查 → 📋 展示 L1-L5 每项详细结果 + 问题汇总 → 等用户确认
   d. sentry-trigger → 触发率评估 → 🎯 展示每条测试输入及结果 + TP/TN → 等用户确认
   e. sentry-cases → 生成用例 → 📝 展示用例表格 + 覆盖率矩阵 + 数据策略 → 等用户确认
   f. sentry-sync PUSH-CASES → 推送用例到飞书 → 展示推送数量 → 等用户确认
   g. sentry-executor → 执行用例 → ⚡ 每批展示详细执行状态表 + 耗时 + tool calls → 等用户确认
   h. grader → 评分 → 📊 展示 12 项指标面板 + 失败用例详情 + 否决项 → 等用户确认
   i. sentry-sync PUSH-RESULTS → 回写结果到飞书 → 展示回写数量 → 等用户确认
   j. sentry-report → 生成报告 + 创建飞书文档 → 📄 展示三件套 + 改进建议 → 等用户确认
   k. sentry-sync PUSH-RUN → 写入运行记录 → 展示完成 → 测评结束
6. 飞书推送:「📊 综合等级:A   结论:PASS」(含完整指标面板 + 飞书文档链接)
```

---

## ✅ 完整流程 Checklist（压缩版）

| Step | 执行 | session.json | 最低输出 | validate |
|---|---|---|---|---|
| 0 | 定位+类型+hash | skill,mode,type,hash | 路径+类型+推荐流程 | `validate_step.py step-0` |
| 0.5 | 三步扫描 | requirements | 显性/流程/隐性规则+计划 | `validate_step.py step-0.5` |
| 1 | sync PULL | sync.pull | 拉取数量 | - |
| 2 | 读 sentry-lint 执行 | lint | L1-L5逐项+问题汇总 | `validate_step.py step-2` |
| 3 | 读 sentry-trigger 执行 | trigger | TP/TN逐条+置信度 | `validate_step.py step-3` |
| 4 | 读 sentry-cases 执行 | cases | 用例表格+覆盖率+数据策略 | `validate_step.py step-4` |
| 4.5 | sync PUSH-CASES | sync.push_cases | 推送数量 | `validate_step.py step-4.5` |
| 5 | 发射 executor subagent | executor | 每批进度+汇总 | `validate_step.py step-5` |
| 6 | grading | grader,verdict,rec | 断言统计+指标+失败详情 | `validate_step.py step-6` |
| 6.5 | sync PUSH-RESULTS | sync.push_results | 回写数量 | `validate_step.py step-6.5` |
| 7 | 报告三件套 | - | 全字段摘要+链接 | `validate_step.py step-7` |
| 7.5 | sync PUSH-RUN | sync.push_run | 写入记录 | `validate_step.py step-7.5` |

**每步完成后必须执行**：
```bash
python3 ~/.openclaw/workspace/skills/SkillSentry/scripts/validate_step.py <session_dir> <step>
```
FAIL → 停下修复，不允许继续。PASS → 进入下一步。

---

## ⛔ 不可豁免的硬性约束（文件末尾 = 最高优先级）

以下规则置于文件末尾，确保 recency effect 最大化。任何情况下不可豁免。

### 卡片硬约束
> ⛔ 所有里程碑推送必须使用 `msg_type=interactive`（飞书卡片），**禁止纯文本 msg_type=text**。
> 无论手动/自动模式，无论卡片入口/上下文感知入口。违反 = 不合规。

### 里程碑审计（milestone audit）
> 每步发送卡片后，必须将发送记录写入 session.json.milestones：
> ```json
> "milestones": {
>   "step-2": {"msg_type": "interactive", "message_id": "om_xxx", "sent_at": "ISO"},
>   "step-4.5": {"msg_type": "interactive", "message_id": "om_xxx", "sent_at": "ISO"}
> }
> ```
> validate_step.py 会检查 milestone 是否存在且 msg_type == "interactive"。

### sync 不可跳过
> Step 4.5、Step 6.5、Step 7.5 是独立步骤，不是注释。
> 无论自动/手动模式，PULL/PUSH-CASES/PUSH-RESULTS/PUSH-RUN 始终执行。
> config.json 不存在时记录 "skipped_no_config"，不是跳过不记。

### 前置校验（Step 7 前）
> 报告生成前检查 sync.push_cases 和 sync.push_results 非 null。
> 缺失 → 阻断报告生成，输出缺失项。

### 透明执行原则
> - 每步完成后必须立即向用户展示完整结果，不允许黑箱运行
> - 缓存命中的步骤必须标注 ⚡ 缓存，仍然展示完整结果
> - 自动模式跳过「等确认」，不跳过「展示结果」
> - 不允许在一条消息中完成两个非缓存 Step（缓存步骤允许合并展示）
> - 所有数字从 session.json 读取，禁止手写

### 反面示例（绝对禁止）
> ```
> ❌ ✅ sentry-lint | L1 ✅✅⚠️✅ | L2 ✅⚠️ | L3: 18.3 | 无 P0
> ```
> 这种一行摘要看不出具体问题。必须按各 sentry-* SKILL.md 的输出规范展开。

---

*Last Updated: 2026-04-26 v6.4 · 压缩 Checklist + validate_step.py + milestone audit + 硬约束置尾*
