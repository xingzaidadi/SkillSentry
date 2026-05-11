# pitfall-guide.md - SkillSentry 踩坑指南 & 设计模式应用

> 本文档总结 SkillSentry 经历 v3→v5→v7.x 共 30+ 次迭代中反复踩到的坑,
> 以及从《AI Skill 设计模式》中提炼的结构性解法。
> 供 Skill 作者和 AI Agent 参考。

---

## 一、核心设计模式映射

| 遇到的问题 | 对应设计模式 | SkillSentry 中的解法 |
|------------|------------|---------------------|
| 步骤合并/偷懒跳步 | **管道模式** (Pipeline §5.4) | 每步有独立输入/输出契约,步骤间不能"跳线" |
| executor 输出不规范(Run-2/3 缺 transcript) | **管道 + 降级兜底** (§5.4+§5.7) | 每步定义必须产物,缺失时触发降级而非静默跳过 |
| 上下文疲劳导致规则遗忘 | **状态机** (§5.3) | session.json 显式跟踪阶段,每阶段有严格输出规范 |
| grader 超时(被断连) | **循环重试 + 降级** (§5.2+§5.7) | 超时→批量快速验证(L2 降级),不逐个读文件 |
| 规则放不到高优先位置 | **分层设计** (§4) | 输入解析层(SOUL)→业务逻辑层(SKILL)→输出层 分开 |
| 重复执行相同测评 | **幂等** (§5.5) | 同 hash + 同模式不重跑,缓存命中直接复用 |

---

## 二、管道模式(Pipeline)-- 坑与解法

### 坑 1:步骤合并
**症状**:Agent 把 check + cases + executor 合并到一个 subagent 里,声称"一步完成"。
**根因**:SKILL.md 没有定义每步的独立输入/输出契约,Agent 找不到"边界"。
**解法**:

```
每步必须有:
├── 输入契约(从哪个文件/状态读什么)
├── 输出契约(产出哪些文件,必须字段)
├── 准出条件(什么条件算完成)
└── 降级策略(超时/失败时如何兜底)
```

### 坑 2:跳过中间步骤
**症状**:Agent 从 Step 1 直接跳到 executor,跳过 cases。
**根因**:session.json 的 `last_step` 没被用作流转约束,只是记录。
**解法**:状态机模式 -- `last_step` 不仅是记录,更是**流转约束**。下一步只能是 `pipeline[indexOf(last_step) + 1]`。

### 坑 3:产物不完整但继续了
**症状**:executor 只产出了 eval-1~eval-3 的 transcript,eval-4/5 缺失,但 grader 照跑。
**根因**:验收只检查"是否有文件",不检查"是否数量完整"。
**解法**:

```python
# 验收公式
expected = len(evals_json["evals"])
actual = count_existing("eval-*/run-{R}/with_skill/outputs/transcript.md")
if actual < expected:
    # 不是 continue,而是 degrade
    trigger_degradation(missing=expected-actual)
```

---

## 三、状态机模式(State Machine)-- 坑与解法

### 坑 4:上下文疲劳
**症状**:第 5 轮 yield/resume 后,Agent 忘了 Step 3 的输出格式要求,输出退化为纯文本。
**根因**:规则写在 SKILL.md 中间(第 400 行),每次 resume 后上下文窗口可能不含这段。
**解法**:

1. **session.json 是唯一权威状态**(不靠上下文记忆)
2. **每次 resume 都重新读 session.json** → 确认当前阶段 → 重新加载该阶段的规则
3. **格式规则注入 subagent task prompt**(不是写在主 SKILL.md 中间期待被记住)

### 坑 5:阶段越权
**症状**:在 cases 阶段,Agent 直接跑了 executor(因为"反正都在同一个对话里")。
**根因**:没有严格的状态转移限制。
**解法**:

```
合法转移表:
  idle       → check | cases (如果有缓存)
  check      → cases
  cases      → executor
  executor   → grader
  grader     → report
  report     → idle

任何不在表中的转移 = 非法,必须 abort + 告警
```

---

## 四、降级兜底模式(Graceful Degradation)-- 坑与解法

### 坑 6:grader 超时导致整个测评作废
**症状**:grader subagent 要逐个读 12 个 eval 的 transcript(每个 2000+ 字),超过 10 分钟被断连。
**根因**:无降级策略,要么全做要么全废。
**解法**:

```
降级分级:
L1(正常):逐个 eval 详细评审,断言级别判定
L2(超时降级):批量快速验证,只看关键断言
L3(异常降级):纯统计(文件存在性 + 字数 + 关键词匹配)

触发条件:
- grader subagent 600s 未完成 → 降级到 L2
- L2 也超时 → 降级到 L3
- L3 输出标注 "[DEGRADED-L3]",报告中醒目标记
```

### 坑 7:MCP 不可用但继续了
**症状**:预检发现 MCP Server 不可用,但 Agent 仍尝试执行,所有 eval 全失败。
**根因**:预检是"告警"而非"阻断+降级"。
**解法**:MCP 全不可用 = 阻断 + 提供降级选项(纯静态分析模式)。

---

## 五、幂等模式(Idempotent)-- 坑与解法

### 坑 8:同一个 Skill 反复跑相同测评
**症状**:SKILL.md 没改,用户重复说"测评",每次都从 0 开始。
**根因**:缺乏幂等判断。
**解法**:

```
幂等键 = MD5(SKILL.md) + mode + date
if 同一天存在相同幂等键的 session:
    提示:"今天已有相同配置的测评(session-XXX),是否复用结果?"
    - 复用 → 直接出报告
    - 重跑 → 新建 session
```

### 坑 9:cases 没变但重新生成
**症状**:SKILL.md hash 一致,cases.cache.json 存在,但 Agent 仍重新设计用例。
**根因**:缓存命中逻辑写在 SKILL.md 里但 subagent 读不到主 SKILL.md 的这段逻辑。
**解法**:缓存命中判断在**主调度器**执行(不委派给子工具),命中后直接跳过 cases subagent。

---

## 六、分层设计模式 -- 坑与解法

### 坑 10:大杂烩 SKILL.md
**症状**:SKILL.md 642 行,混合了输入解析、步骤调度、输出格式、异常处理。
**根因**:所有关注点堆在一个文件。
**解法**:

```
分层架构:
SKILL.md(调度层)
├── 输入解析:用户意图识别 + 参数提取(~50行)
├── 状态机流转:session.json 读写 + 步骤路由(~80行)
├── 输出格式:统一消息模板引用(→ references/)
└── 异常处理:降级规则 + 错误恢复(~30行)

references/(规范层)
├── execution-phases.md(跨工具接口定义)
├── step-contracts.md(每步的输入/输出/准出契约)
├── degradation-rules.md(降级规则)
└── feishu-templates.md(输出模板)

tools/sentry-*/(业务逻辑层)
├── 每个子工具独立 SKILL.md
└── 只关心自己的业务,不管调度
```

### 坑 11:子 agent 读不到主 SKILL.md 的规则
**症状**:格式要求写在主 SKILL.md,但 executor subagent 根本没看过。
**根因**:subagent 只拿到 task prompt,不会自动继承父会话的 SKILL.md。
**解法**:**规则跟着数据走**--关键格式要求必须注入 subagent 的 task prompt,不能只写在主 SKILL.md 里"期望被记住"。

---

## 七、飞书/OpenClaw 环境特有坑

### 坑 12:纯文本代替交互卡片
**症状**:列 23 个 Skill 用 Markdown 表格,用户在飞书里看到一堵文字墙。
**根因**：SKILL.md 只写了“发交互卡片”但没给完整的 V2 card JSON 模板。
**解法**:**可执行模板 > 描述性指令**。写具体的 JSON 调用示例,而非一句话描述。

### 坑 13:message(msg_type="interactive") 不支持
**症状**:想发卡片消息,但 message 工具只支持 text 类型。
**根因**:环境限制未文档化,AI 按工具 schema 理解可以发任何类型。
**解法**:在 SKILL.md 中明确标注 `msg_type="text"`,不使用 interactive。

### 坑 14:进度消息合并
**症状**:Step 0/1/2 的结果合并到一条消息里发出。
**根因**:SKILL.md 没有写"每步独立消息"的硬约束。
**解法**:明确规则--**每个 Step 完成后发一条独立 message,禁止合并**。

### 坑 15:.bak 目录被 scanner 误读
**症状**:available_skills 列出的是 `.bak.20260422` 目录,不是正式目录。
**根因**:scanner 按字母排序扫描,.bak 在 S 之前。
**解法**:备份目录的 SKILL.md 重命名为 `.bak`,scanner 忽略非 `.md` 后缀。

---

## 八、数据层面的坑

### 坑 16:AI 编造测试数据
**症状**:eval 中出现虚构的单号/ID,MCP 调用必然失败。
**根因**:sentry-cases 没有标注 auto-exempt + 数据采集步骤。
**解法**:real_data 用例的测试数据**必须**来自 MCP 查询或用户提供,禁止 AI 编造。

### 坑 17:缓存跳过时无摘要展示
**症状**:cases 缓存命中,输出"缓存命中,跳过"--用户看不到有哪些用例。
**根因**:跳过 = 没有输出。
**解法**:**跳过 ≠ 静默**。缓存命中时必须展示内容摘要(用例列表、规则统计等)。

---

## 九、设计模式落地检查清单

在修改 SkillSentry 或设计新 Skill 时,逐项对照:

- [ ] **管道**:每步有明确的输入文件、输出文件、准出条件?
- [ ] **状态机**:session.json 有 last_step?步骤转移有合法性校验?
- [ ] **降级**:每步超时/失败有对应降级方案?降级结果有标记?
- [ ] **幂等**:同配置重跑有检测+复用提示?
- [ ] **分层**:调度逻辑和业务逻辑分离?格式规则注入 subagent task?
- [ ] **可执行模板**:关键工具调用有完整参数示例,不是描述?
- [ ] **独立消息**:每步有独立通知,不合并不静默跳过?
- [ ] **产物验收**:验收检查数量+内容,不只检查文件存在?

---

*v1.0 · 2026-05-02 · 从 30+ 次迭代实战经验提炼*

---

## 十、Fresh Execution Contract 相关坑(v7.12.1 新增)

### 坑 18:规则写了但主调度器自己不遵守

**症状**:加了 must_read、Completion Gate、evidence ledger,但主调度器照样合并消息、一行摘要、不写 evidence。

**根因**:规则写给 subagent,没人约束主调度器自己。

**解法**:主调度器自约束清单(每次发消息前 5 项检查),任何一项不过 = 不发送。

### 坑 19:must_read 写在 step-contracts 但没注入 task prompt

**症状**:step-contracts 每步有 must_read,但 spawn subagent 时 task prompt 里没写。

**根因**:缺标准注入模板,每次靠主调度器"记得"要注入。

**解法**:SKILL.md 写死「subagent task prompt 标准注入清单」,包含 must_read + 输出路径 + 格式要求 + evidence 要求。不含这些 = 违规。

### 坑 20:Completion Gate 定义了但 publish 没引用

**症状**:output-format.md 有 7 项 Gate,但 SKILL.md 的 publish 步骤没提,Agent 跑完 report 就认为结束了。

**解法**:publish 步骤明确写"执行 Completion Gate 检查 → 确定 COMPLETE/PARTIAL/BLOCKED"。

---

*v1.1 · 2026-05-02 · 新增坑 18-20(Fresh Execution Contract 落地问题)*

## 十一、数据隔离相关坑(v8.1.0 新增)

### 坑 21:sessions 目录导致 LLM "偷懒"
**症状**:Agent 跳步、合并步骤、grader 评分虚高,加再多约束规则也效果递减。
**根因**:sessions/ 放在 skill 目录下,包含旧测评的完整答案(verdict=S, grading=100% pass)。主调度器在 Step 1 初始化时就能 ls 到这些数据。LLM 看到答案后产生认知捷径--"已经知道结果了",后续步骤不再认真执行。
**解法**:sessions 移到 skill 目录外部(`~/.openclaw/data/skill-eval/sessions/`)。所有依赖通过绝对路径或参数传入,不需要同目录。
**教训**:不是"规矩不够",是"旧答案太容易被看到"。约束规则解决的是"该怎么做",数据隔离解决的是"能看到什么"。两层独立。

### 坑 22:JSON 示例的通过/失败分布不均导致评审偏差
**症状**:grader 系统性高估通过率 15-20%(与 IFEval 研究吻合)。
**根因**:grader.md 和 comparator 的 JSON 示例中,通过示例 >> 失败示例。LLM 从示例分布中学到"通过是常态,失败是异常"。comparator 示例中 A(with_skill)永远赢 B(without_skill),强化了"有 Skill 一定好"的偏见。
**解法**:在 grader.md 补充完整的 `passed: false` 示例(含 evidence);在 comparator 补充 B 赢 A 的示例。加评审员须知:"通过和失败是等概率事件"。
**教训**:JSON 示例的示范效应比文字说明强 10 倍。写示例时必须平衡通过/失败分布。

---

*v1.2 · 2026-05-03 · 新增坑 21-22(数据隔离 + 示例偏差)*

## 十二、数据污染四层模型(v8.2.0 总结)

> 2026-05-03 完整对话复盘,从"为什么加了这么多约束还偷懒"出发,逐层挖到根因。

### 四层污染模型

| 层级 | 污染源 | 内容 | 影响 | 解法 |
|------|--------|------|------|------|
| **L1** | sessions/ | 旧 session 的 grading.json/verdict/transcript | LLM 直接看到答案 → 跳步偷懒 | 移出 skill 目录 |
| **L2** | inputs/ 的 history/baseline | 历史成绩(grade=S, pass_rate=100%) | 锚定效应 → 评分偏高 | 禁止主调度器在 Step 2 读结果文件 |
| **L3** | output-format.md 模板示例 | 模板里写了"评级: S""基线: S→S" | 表面看像泄露好成绩 | **经分析不需要改**(见下方) |
| **L4** | grader/comparator JSON 示例 | pass:true 示例远多于 pass:false | 示例偏差 → 系统性高估 15-20% | 补充平衡的 false 示例 |

### 坑 23:inputs/ 历史成绩对主调度器的锚定效应

**症状**:grader 评分虚高,即使 sessions 已移走。

**根因**:`inputs/<Skill>/history.json` 包含 `grade: A, exact_match: 96.1`,`baseline.snapshot.json` 包含 `grade: S, pass_rate: 100.0`。主调度器在 Step 2 推断模式时 `ls inputs/<Skill>/` 能看到这些文件。LLM 的"好奇心"会顺手读一下,读到"上次 S 级"后,后续评审被锚定。

**解法**:SKILL.md Step 2 加数据隔离规则--只读 `rules.cache.json`(判断 hash),禁止读 history/baseline/trigger_eval。这些文件只在 report 阶段由 sentry-report subagent 使用。

**关键区分**:L1(sessions)是"答案泄露"→ 直接抄答案;L2(inputs)是"成绩锚定"→ 潜意识偏高。两者机制不同,解法也不同。

### 坑 24:L3 模板示例--看似有害但实际无害(反面教训)

**初始判断**:output-format.md 的示例写了"评级: S""基线: S→S",以为会教 LLM "S 是正常的"。

**深入分析后推翻**:
- 这个文件**只有主调度器在 publish 步骤读**
- publish 时 grader 已经结束,真实数据已在 grading-summary.json 里
- 主调度器只是按模板填值,模板里写 S 还是 {grade} 对评审判断**没有影响**
- executor 的 completion message 示例里的具体业务数据("查BR单号→返回详情")是**必需的格式参考**,改成占位符会导致 executor 不知道该输出什么粒度

**教训**:污染分析要看"谁在什么阶段读",不能只看"文件里有没有好成绩"。时序很重要--评审后读到的数据不会影响评审结果。

### 坑 25:"约束规则 vs 数据可见性"是两个独立维度

**背景**:v3→v7 期间,每次发现偷懒/跳步/评分虚高,解法都是"加更多约束"--must_read、sentry-proof、auto-exempt、自约束清单、状态机、铁律......约束越加越多但效果递减。

**根因发现**:约束规则解决的是"LLM 该怎么做"。但如果 LLM 能看到答案(sessions)或历史成绩(inputs),再多规则也挡不住认知捷径。这就像让一个人先看了考试答案再去考试--你可以要求他"认真答题",但他不可能假装不知道答案。

**结论**:
- **约束规则**:控制行为("必须读文件""必须写 evidence""禁止合并步骤")
- **数据隔离**:控制可见性("看不到旧答案""看不到历史成绩")

两层独立,缺一不可。v8.1 之前只做了约束层,没做隔离层,所以效果递减。

---

## 十三、架构决策记录(v8.0 重构)

### 坑 26:sentry-static 三合一--为什么 lint 要保留独立调用

**决策**:sentry-check + sentry-lint + sentry-trigger 合并为 sentry-static,但保留 `--lint-only` 和 `--trigger-only` 参数。

**原因**:
- 三者共享完全相同的输入(被测 SKILL.md),都是纯读操作,无副作用 → 合并零风险
- sentry-lint 和 sentry-trigger 原来各只有 14 行,本来就是 sentry-check 的子集
- 但 lint 在 CI 集成和研发自检场景中需要独立调用(`sentry-static --lint-only`),不能只作为 full pipeline 的一部分
- 合并后子步骤必须有独立输出(L1-L5 各自展示),不能最后一起吐

### 坑 27:comparator 不能合并到 executor--盲测方法论要求

**曾考虑的优化**:把 comparator 合并到 executor,因为 executor 已经同时跑 with/without,比较逻辑可以在内部完成。

**否决原因**:comparator 的核心价值是**盲测**--它不知道哪份输出是 with_skill 哪份是 without_skill。这是消除评判 bias 的关键设计。如果合并到 executor:
1. executor 天然知道 which is which(它自己执行的)
2. 盲性彻底丧失,对比结果不可信
3. 坑 11 说"子 agent 读不到主 SKILL.md 的规则"--comparator 恰恰利用这个特性(它不该读到 SKILL.md)

**教训**:不是所有"减少 subagent 数量"的优化都是好优化。有些独立性是方法论要求,不是工程冗余。

### 坑 28:analyzer 不能合并到 grader--context 超载风险

**曾考虑的优化**:把 analyzer 的根因分析合并到 grader 的 recommendations 字段。

**否决原因**:
- grader 已经在超时边缘--要逐个读 17 个 eval 的 transcript + response + 逐条断言评审
- v3.0 已经把 report 合并进 grader(省 1 次 spawn),再塞 analyzer 的逻辑会增加 ~60% context 负载
- analyzer 需要额外读 comparator-results.json + 被测 SKILL.md 全文 + 双方 transcript 对比
- 坑 6(grader 超时)会直接恶化

**教训**:subagent 的拆分不仅是关注点分离,更是 **context 容量管理**。每个 subagent 的 context 有上限,合并过多职责会导致后半段质量退化。

---

*v1.3 · 2026-05-03 · 新增坑 23-28 + 四层污染模型 + 架构决策记录*

---

## 坑26:⛔ 标记 ≠ 执行保障(v8.4.0 修复)

**现象**:SKILL.md 用 ⛔ 标注"不可跳过"的步骤,实际执行时仍被跳过。

**根因(三层叠加)**:

1. **注意力稀释(Lost in the Middle)**:SKILL.md 647行 + 对话历史,到 executor 阶段时规则已被淹没。学术论文证实:模型能力随 token 数量增加而退化,与上下文窗口大小无关。
2. **约束对象错位**:SKILL.md 的校验体系(must_read、proof 标记)只约束 subagent,主调度器自身执行的步骤无外部校验。
3. **状态机未覆盖**:PUSH-CASES 等步骤不在 pipeline 数组中,session.json.last_step 不追踪,导致 resume 后无法发现遗漏。

**修复**:
```
v8.4.0: 把 sync-pull、sync-push-cases、sync-push-results、gate 加入 pipeline 数组
- 状态机强制顺序执行
- 无 config.json 时降级为 skipped_no_config(步骤仍被走过)
- last_step 精确区分"cases完成但没PUSH" vs "PUSH也完成了"
```

**设计原则**:
- 描述性约束(⛔标记)≠ 结构性保障(pipeline 状态机)
- 凡是⛔标记的步骤,必须入 pipeline
- 主调度器执行的动作也需要被状态机管理
- sync 步骤可降级但不可跳过

**引用**:
- Reinteractive (2026.03): "模型能力随输入 token 数退化,无论上下文窗口多大"
- Anthropic (2025.09): "treat context as a limited resource with decreasing returns"
- LinkedIn/stack72 (2026.04): "The agent can't skip steps: that's enforced at the model layer, not a textual constraint"
