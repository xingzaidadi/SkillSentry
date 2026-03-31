# 9 层测评维度详解

本文件是测评维度的完整参考，在设计测试用例和分析测评结果时按需查阅。


---

## 维度全景图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      AI Skill 测评维度体系                           │
├─────────────────┬───────────────────────────────────────────────────┤
│  触发层          │  触发准确性、边界触发、模型版本兼容性               │
├─────────────────┼───────────────────────────────────────────────────┤
│  输出层          │  格式合规、内容准确、完整性、一致性                  │
├─────────────────┼───────────────────────────────────────────────────┤
│  业务层          │  业务规则遵守、业务流程正确性、指令遵循率、合规性     │
├─────────────────┼───────────────────────────────────────────────────┤
│  交互层          │  多轮对话一致性、追问质量、降级行为、可解释性         │
├─────────────────┼───────────────────────────────────────────────────┤
│  健壮层          │  原子性、鲁棒性、回归保护、安全性、幻觉检测          │
├─────────────────┼───────────────────────────────────────────────────┤
│  效率层          │  耗时、Token消耗、稳定性/方差、超时降级             │
├─────────────────┼───────────────────────────────────────────────────┤
│  设计层          │  Skill复杂度、负向增益分析、领域适配性预评估         │
├─────────────────┼───────────────────────────────────────────────────┤
│  工程层          │  风险分级、覆盖率、数据分布对齐、环境一致性          │
├─────────────────┼───────────────────────────────────────────────────┤
│  组织层          │  角色职责、测评策略、知识时效性                      │
└─────────────────┴───────────────────────────────────────────────────┘
```

---

## 一、触发层（Trigger Layer）

### 1.1 触发准确性（Trigger Accuracy）

Skill 的触发是测评的第一道门槛。触发不准确，后续所有测评都失去意义。

| 场景 | 标准 |
|------|------|
| 应触发但未触发（False Negative） | 不通过 |
| 不应触发但触发了（False Positive） | 不通过 |
| 正确触发（True Positive） | 通过 |
| 正确不触发（True Negative） | 通过 |

**触发率公式**：
```
Trigger Rate = 正确触发次数 / 总测试次数 × 100%
```

**测量方案对比**：

| 方案 | 精度 | 前提条件 | 适用场景 |
|------|------|---------|---------|
| **AI 模拟估算**（阶段一自动运行） | 估算值，附置信度 | 无特殊要求 | 日常测评、快速预判 |
| **精确测量**（skill-creator run_eval.py） | 精确率，可用于正式决策 | 需要 claude CLI | S/A 级正式发布前 |

AI 模拟方案在阶段一自动运行，生成 10 条测试 prompt（5 TP + 3 TN + 2 边界），输出 `trigger_eval.json`，在报告第十一章可视化。

**调优方向**：触发问题 90% 出在 `description` 字段。优先检查描述是否清晰表达了"何时使用"，可通过 skill-creator 的 `run_loop.py` 做自动优化。

### 1.2 边界触发（Boundary Trigger）

测模糊地带，而不只是明确场景：

- **语义模糊**：用户的意图不明确，Skill 应询问而非乱触发
- **多 Skill 竞争**：多个 Skill 都可能匹配时，最相关的应该赢
- **部分关键词命中**：仅关键词匹配但意图不符时，不应触发
- **优雅退出**：错误触发后，能引导用户到正确路径

### 1.3 模型版本兼容性（Model Compatibility）

底层模型升级时，Skill 行为可能发生变化。在模型升级前后各跑一轮完整 benchmark 对比。

---

## 二、输出层（Output Layer）

### 2.1 格式合规性

- 输出结构是否符合 SKILL.md 规定（JSON 格式、表格、模板等）
- 必填字段是否完整，文件类型是否正确

**纯文本 Skill 的格式验证**：
- Markdown 标题层级是否符合 SKILL.md 要求（H1/H2/H3）
- 列表、代码块、引用格式是否规范
- 输出长度是否在 SKILL.md 规定范围内

### 2.2 内容准确性

- 关键信息是否正确提取、计算或生成
- 是否有事实性错误或遗漏
- 边界情况（edge cases）处理是否正确

### 2.3 完整性

- 输出是否覆盖了用户请求的所有要点
- 没有截断或半成品输出

### 2.4 一致性（Consistency）

同一语义的不同表达，输出的关键字段应完全一致。

```
一致性得分 = 关键字段完全一致的组数 / 总对比组数 × 100%
目标：≥ 90%
```

---

## 三、业务层（Business Layer）

### 3.1 业务规则遵守

纯技术指标只验证"输出了什么"，业务规则测试才能验证"输出的对不对"。

从 SKILL.md 提取规则的方法：
1. 找所有"如果...则..."→ 条件判断测试
2. 找所有数值限制 → 边界测试
3. 找所有必填/禁止字段 → 合规性断言
4. 找路由规则和优先级 → 流程测试

### 3.2 指令遵循率（IFR）

```
IFR = 正确遵循硬性规则的次数 / 触发硬性规则的总次数 × 100%
```

**S级 Skill 要求 IFR = 100%**，不允许任何硬性规则被绕过。

测试方法：针对每条硬性规则，构造"应该触发该规则"的场景，验证规则是否真的执行了。

### 3.3 合规性（Compliance）

合规性约束来自外部法规和公司制度，**不写在 SKILL.md 里，但输出必须符合**：

- **数据隐私**：不暴露个人敏感信息
- **财务合规**：金额精度、审批权限告警
- **流程合规**：审批节点不被绕过，关键操作有确认步骤

---

## 四、交互层（Interaction Layer）

### 4.1 多轮对话一致性

- 分多条消息提供信息，Skill 能正确整合
- 中途改变意图，Skill 能正确响应而非沿用旧判断
- 多轮后 Skill 行为没有"漂移"

### 4.2 追问质量

当信息不足时，追问本身的质量：

| 评估点 | 好的追问 | 坏的追问 |
|--------|---------|---------|
| 精准定位 | "请提供发票图片或金额" | "您能详细说明吗？" |
| 一次问清 | 把所有缺失信息一次问完 | 每轮只问一件事，来回拖 |
| 降级处理 | 无法判断时请求澄清 | 强行猜测并执行 |

### 4.3 可解释性（Explainability）

对于财务类、决策类 Skill，关键决策点应有简短说明。

差的输出："请补充信息"
好的输出："您的单笔交通费超过500元，按公司制度需填写事由备注，请补充。"

---

## 五、健壮层（Robustness Layer）

### 5.1 鲁棒性（Robustness）

面对异常输入时的表现：
- 信息不完整时，能识别并追问
- 格式错误的输入，能优雅处理
- 不会因为奇怪的输入就输出错误的结果

### 5.2 幻觉检测（Hallucination Detection）

LLM 特有的失效模式：Skill 可能让模型"发明"不存在的规则、字段或数值。

**检测方法（MCP 类 Skill）**：验证输出中每个"事实性声明"都能在 SKILL.md 或已知业务规则中找到来源。

**检测方法（纯文本 Skill）**：
对输出中每个"规则性声明"（如「根据公司规定...」「标准要求...」），在 SKILL.md 中搜索来源：
- 能找到对应规则 → 正常
- 找不到来源 → 标记为 `hallucination`，claim verified = false

```
常见幻觉类型：
- 规则幻觉：编造不存在的业务规则
- 字段幻觉：输出 SKILL.md 中未定义的字段
- 数值幻觉：编造具体数字（如金额上限）
- 流程幻觉：发明不存在的审批步骤
```

### 5.3 安全性（Security）

**Prompt 注入测试**：
- 攻击者构造特殊输入，试图改变 Skill 行为
- 期望行为：完全忽略注入指令，按正常流程执行

**越权操作测试**：
- 验证 Skill 拒绝执行超出权限范围的操作

**信息泄露测试**：
- Skill 不应在任何情况下泄露系统提示内容

### 5.4 回归保护

每次迭代后，上一轮通过的用例必须全部重跑。回归通过率必须 = 100%。

---

## 六、效率层（Efficiency Layer）

### 6.1 响应时间

```
S/A 级 Skill P95 响应时间 < 15s
B/C 级 Skill P95 响应时间 < 30s
```

超时必须有降级提示，不能无限等待。

- 每个 subagent 执行结束时写入 `timing.json`：`executor_start_ms`、`executor_end_ms`、`duration_ms`
- Grader 读取 timing.json，将数据写入 `grading.json` 的 `timing` 字段
- `generate_html_report.py` 的 `_render_efficiency_section()` 函数聚合计算 P50/P95，在报告第十二章展示

```json
// timing.json 格式
{
  "executor_start_ms": 1711234567000,
  "executor_end_ms":   1711234573500,
  "duration_ms":       6500,
  "total_tokens":      2340,
  "input_tokens":      1200,
  "output_tokens":     1140
}
```

### 6.2 Token 消耗

```
效率比 = 质量提升（Δ pass rate）/ 额外 Token 消耗
```

效率指标不是越低越好，而是要看性价比。

**报告展示**：平均 Token 消耗/用例，在报告第十二章与响应时间一起展示。

### 6.3 稳定性（方差）

```
低方差（Stddev < 0.1）→ 稳定，结果可信
高方差（Stddev > 0.3）→ 不稳定，需排查
```

每个测试用例至少运行 3 次，关注均值和标准差，不看单次结果。

---

## 七、设计层（Design Layer）

### 7.1 Skill 复杂度

```
复杂度得分 = 模块数 × 2 + (SKILL.md行数 / 50) + 硬性规则条数 × 0.5

≤ 10 分 → 精简，预期稳定
11-20 分 → 适中，可接受
> 20 分 → 过于复杂，建议拆分
```

SkillsBench 研究证明：精简型 Skill（2-3模块）效果显著优于内容庞杂的综合性文档。

### 7.2 负向增益分析（Negative Delta Analysis）

SkillsBench 在 84 个任务中发现 16 个出现负向 delta——加了 Skill 反而让模型变差。

```
增益 Δ = Pass Rate(with_skill) - Pass Rate(baseline)
```

- Δ > 10%：增益显著
- 0% < Δ ≤ 10%：增益偏低，评估维护成本
- Δ < 0：**发布红线**，根因未明确不允许上线

**根因排查二分法**：逐条禁用 Skill 规则模块，定位导致负向的具体模块。

### 7.3 领域适配性

- 有严格业务流程 + 内部知识 + 模型先验弱 → 高适配
- 通用创意类 + 模型本身很强 → 低适配，增益有限

**Skill 类型适配性参考**：

| Skill 类型 | 典型增益范围 | 核心验证侧重点 |
|-----------|-----------|------------|
| `mcp_based` | 高（MCP 调用顺序、参数正确性） | transcript 中工具调用验证 |
| `code_execution` | 中高（命令正确性、输出文件验证） | Bash 调用记录验证 |
| `text_generation` | 低到中（取决于领域知识密度） | response.md 内容质量验证 |

---

## 八、工程层（Engineering Layer）

### 8.1 测评覆盖率

```
功能覆盖率 = 有用例的规则数 / 总规则数 × 100%
路径覆盖率 = 已测分支数 / 总分支数 × 100%
断言覆盖率 = 有断言字段数 / 关键字段总数 × 100%

综合覆盖率 = 功能覆盖率 × 0.5 + 路径覆盖率 × 0.3 + 断言覆盖率 × 0.2
```

目标：S/A级 ≥ 85%，B/C级 ≥ 60%

### 8.2 测评环境一致性

测评环境必须与生产环境在以下参数上完全一致：
- 模型版本（model）
- Temperature 参数
- System Prompt
- Skill 版本（git commit hash）
- 上下文长度限制

**新增字段**：`eval_environment.json` 中需包含 `skill_type`（系统自动检测填写）和 `execution_mode`（`real` / `text` / `simulated`）。

每次测评必须归档 `eval_environment.json`。

### 8.3 数据分布对齐

测评集的输入分布应与线上真实用户输入尽量一致：
- 避免 prompt 过于"工程化"（太整洁、太正式）
- 包含口语化表达、甚至拼写错误
- 加入真实用户历史输入样本

---

## 九、组织层（Organization Layer）

### 9.1 知识时效性

Skill 里的业务规则有保质期。建立以下机制：
- 在 SKILL.md 中标注规则有效期：`# 规则名（最后验证：YYYY-MM，下次复核：YYYY-MM）`
- 每季度对 S/A 级 Skill 做规则有效性复核
- 公司制度更新时立即触发相关 Skill 复核

### 9.2 业务逻辑断言必须经业务方确认

测评工程师对业务规则的理解可能存在偏差，断言本身可能是错的。
S/A 级 Skill 的业务逻辑断言需要业务方审核。

---

## 十、防编造可信度体系

> SkillSentry 的测评结论可信度，根本上取决于 Skill 类型和执行环境。本章是不同场景下防编造能力的诚实评估。

### 10.1 各 Skill 类型防编造评分

| Skill 类型 | 评分 | 核心机制 | 核心缺口 |
|-----------|------|---------|---------|
| **mcp_based（MCP 可用）** | **5/10** | transcript 双分离 + 强制 FAIL + claims 交叉验证 | transcript 由 AI 手写，无系统级拦截机制，AI 技术上可以伪造 Return 值 |
| **mcp_based（MCP 不可用）** | **1/10** | 仅有规则推断，无任何客观锚点 | 完全依赖 AI 按 SKILL.md 规则编写剧本，所有字段值均为推断 |
| **code_execution** | **6.5/10** | 上述全部 + 文件系统输出独立验证 | 文件内容是物理锚点，Grader 可独立读取；但脚本本身可能输出假数据 |
| **text_generation** | **2.5/10** | 量化断言（字数/格式）+ without_skill 对照 + 幻觉声明检测 | 全链路 AI 闭环，无外部真相锚点，评分天花板约 5 分 |

**重要说明**：
- 评分反映的是「当前设计下，测评结论不被 AI 编造的概率」
- mcp_based 在 MCP 真实可调用时，评分 5/10 的含义是：能防住「软性编造」和「粗心遗漏」，无法防住「精心构造的完整伪造」
- text_generation 的 2.5 分不是失败，而是这类 Skill 的客观上限较低——判断「文章写得好不好」本身就没有客观标准

---

### 10.2 提升方案

#### mcp_based：5 → 8 分路径

**【❌ 已核查不可行，已废弃】MCP Side-car 日志方案**

经查 OpenCode 官方文档（https://opencode.ai/docs/agents/）：*"subagents will use the model of the primary agent that invoked the subagent"* — 主 agent 通过 Task 工具启动 subagent 后，只能拿到 subagent 最终的文字输出，**无法获取 subagent 执行期间的工具调用原始记录**。「主 agent 独立监听 subagent MCP 调用」在当前 OpenCode 架构下做不到，此方案已废弃。

---

**【✅ 当前可行方案 1】MCP STDIO 拦截代理**

**依据**：MCP 官方架构文档（modelcontextprotocol.io）：*"Stdio transport: Uses standard input/output streams for direct process communication between local processes on the same machine"*

本地 MCP 服务器使用 STDIO 传输，可在其前面插入一个代理脚本，自动捕获所有 JSON-RPC 原始通信。这个日志由系统级进程写入，AI 不知道它的存在，无法修改。

实现方式参见：`scripts/verify_assertions.py`（已包含 transcript 与拦截日志的对比逻辑）。

可行条件：MCP server 使用 STDIO 传输（本地 MCP 均支持此传输方式）。

---

**【✅ 当前可行方案 2】Python 脚本替代 Grader 做量化验证**

**依据**：OpenCode 工具文档（https://opencode.ai/docs/tools/）：*"bash: Execute shell commands in your project environment"* — Grader 可调用 bash 执行 Python 脚本，结果 0/1，完全绕过 AI 主观判断。

工具脚本：`scripts/verify_assertions.py`，支持以下确定性验证类型：
- `tool_call_count`：统计 [tool_calls] 区块中工具名出现次数
- `args_field`：提取工具调用入参字段值精确匹配
- `response_not_contains`：全文检索占位符/禁止字符串
- `response_contains`：关键词存在性
- `response_word_count`：字数统计
- `response_has_heading`：标题结构检测

结果在 `grading.json` 中标注 `"method": "script"`，与 `"method": "grader"` 明确区分，报告单独统计「脚本验证通过率」。

**【✅ 当前已实现】工具调用次数交叉核查（agents/grader.md 已包含）**：
- Grader 对每条 exact_match 断言，统计工具名在 transcript 中出现次数，与断言声明数字交叉核查
- 发现「声明调用 1 次但工具名出现 3 次」类矛盾 → FAIL
- Return 值以自然语言描述而非原始 JSON → `fabrication_risk: "high"`，报告橙色警告

#### code_execution：7 → 9 分路径

**方案：不读 transcript，直接读输出文件**

Bash 命令的产出文件是物理锚点，AI 无法在「不实际执行命令」的情况下伪造它。Grader 直接调用 bash 读取并验证文件内容，完全不依赖 transcript 里的 Return 字段。

```
❌ 不要写断言：命令执行返回 status=success
✅ 要写断言：outputs/result.json 存在，且 json["status"] == "success"
```

验证逻辑在 `scripts/verify_assertions.py` 中可直接扩展。

#### text_generation：2.5 → 5 分路径（这是上限，无法突破）

**为什么上限是 5 分**：「判断文章写得好不好」本身没有客观标准，这是 LLM 评估领域的普遍难题。即使 LMSYS Chatbot Arena（业界最权威的 LLM 评测）也依赖大量人工评分来解决这个问题。这不是 SkillSentry 的缺陷，是 text_generation 类型评测的本质局限。

**方案 1：量化断言比例强制 ≥ 50%，用脚本验证**

text_generation Skill 的断言中，可量化类型必须占 ≥ 50%，且交由 `verify_assertions.py` 脚本验证而非 Grader AI，确保至少一半结论不依赖主观判断。

**方案 2：发布前业务方人工确认（不可省略）**

```
⚠️ 纯文本生成型 Skill：语义断言由 AI 评审，存在主观判断空间。
   在发布决策生效前，请业务方确认以下用例的输出质量：
   - [happy_path 用例 response.md 路径]
   - [E2E 用例 response.md 路径]
```

---

### 10.3 各场景下的报告使用建议

| 场景 | 报告结论可用性 | 行动建议 |
|------|------------|---------|
| mcp_based + MCP 真实执行 + 脚本验证 | **可信，可作发布参考** | 重点看 `method: script` 标注的断言结果 |
| mcp_based + MCP 真实执行（无脚本验证） | 有一定可信度 | 人工复核 1-2 个关键断言的 evidence 原文 |
| mcp_based + MCP 不可用 | **不可用于发布决策** | 修复 MCP 环境后重测 |
| code_execution + 直接读输出文件 | **可信，可信度最高** | 验证输出文件内容本身即可 |
| text_generation | 仅供参考 | 必须经业务方人工确认核心用例输出 |

---

## 十一、ISO/IEC 25010:2023 对照表

> SkillSentry 的 9 层测评维度与国际软件质量标准 ISO/IEC 25010:2023（SQuaRE 产品质量模型）及 AI 扩展标准 ISO/IEC 25059 的对应关系。此对照表供外部专业人员验证测评框架完备性。

| SkillSentry 维度 | ISO 25010:2023 主特性 | ISO 子特性 | AI 扩展（25059）备注 |
|----------------|---------------------|------------|-------------------|
| **触发层**（触发准确性、边界触发） | 功能适用性 (Functional Suitability) | 功能正确性 (Functional Correctness)、功能适当性 (Functional Appropriateness) | AI 触发精度属于 AI 特有的功能适当性 |
| **输出层**（格式合规、内容准确、一致性） | 功能适用性 + 可靠性 (Reliability) | 功能正确性、成熟度 (Maturity) | ISO 25059 新增"输出一致性"子特性 |
| **业务层**（规则遵守、IFR、合规性） | 功能适用性 + 安全性 (Safety) | 功能完整性 (Functional Completeness)、合规性 | ISO 25059 将"指令遵循"列为 AI 核心质量属性 |
| **交互层**（多轮一致性、追问质量、可解释性） | 易用性 (Usability) | 可操作性 (Operability)、用户错误防护 | ISO 25059 新增"透明性 (Transparency)"子特性 |
| **健壮层**（鲁棒性、幻觉检测、安全性） | 可靠性 + 安全保障 (Security) | 容错性 (Fault Tolerance)、可用性 (Availability) | ISO 25059 新增"鲁棒性 (Robustness)"，幻觉检测属于 AI 特有缺陷 |
| **效率层**（响应时间、Token 消耗、稳定性） | 性能效率 (Performance Efficiency) | 时间行为 (Time Behaviour)、资源利用率 (Resource Utilization) | Kapoor et al. (2024) 提出成本-准确率联合优化，与此维度直接对应 |
| **设计层**（Skill 复杂度、负向增益） | 可维护性 (Maintainability) | 可分析性 (Analysability)、模块性 (Modularity) | ISO 25059 新增"AI 模型可维护性"子特性 |
| **工程层**（覆盖率、环境一致性、数据分布） | 可靠性 + 灵活性 (Flexibility) | 可测试性 (Testability)、适应性 (Adaptability) | ISO 25059 将"数据分布对齐"列为 AI 测评要求 |
| **组织层**（知识时效性、业务确认） | 可维护性 | 可修改性 (Modifiability) | — |

**参考标准**：
- [ISO/IEC 25010:2023](https://www.iso.org/standard/78176.html) — Systems and software Quality Requirements and Evaluation (SQuaRE)
- [ISO/IEC 25059](https://www.iso.org/standard/80655.html) — SQuaRE for AI Systems（AI 系统质量扩展）
- Kapoor et al., *AI Agents That Matter*, arXiv:2407.01502, 2024

---

*Last Updated: 2026-03-30*
