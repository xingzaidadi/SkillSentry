# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

SkillSentry 是一套专为 AI Skill 发布质量把关而设计的端到端测评系统。从读取 SKILL.md 到输出 HTML 报告，全程自动化，覆盖从触发准确性到行为质量的完整验证链路。

---

## 核心能力

| 能力 | 说明 |
|------|------|
| **规则自动提炼** | 从任意 SKILL.md 识别条件判断、数值限制、禁止行为、路由规则 |
| **Skill 类型自动检测** | 启动时自动识别 mcp_based / text_generation / code_execution，切换对应执行模式 |
| **7 类用例自动生成** | Happy Path / 原子 / 业务逻辑 / 边界 / 鲁棒性 / 负向 / 一致性 |
| **断言强度分级** | 断言分精确★ / 语义◆ / 存在性○三级，准入判断只看精确通过率，避免存在性断言虚高结论 |
| **四层验证体系** | Executor（真实执行）→ Ground Truth（精确校验）→ Grader（独立评审）→ Comparator + Analyzer（盲测对比）|
| **文件系统隔离** | with_skill / without_skill 各有独立 workspace 沙箱，禁止互相读取，确保 Δ 可信 |
| **transcript 双分离** | `[tool_calls]`（原始数据）与 `[agent_notes]`（AI 解释）严格分区，Grader 优先引用原始数据 |
| **触发率预评估** | 阶段一自动运行 AI 模拟，生成 10 条测试 prompt，产出置信度估算；低置信自动降级发布决策 |
| **效率指标采集** | timing.json 自动读取，报告展示 P50/P95 响应时间和 Token 消耗 |
| **外部用例导入** | 测评启动时自动创建 `inputs/<Skill名>/` 并告知路径，将 `.cases.md` 放入即可，自动识别为「黄金用例」优先测试 |
| **跨迭代对比** | 自动检测历史 session 数据，在报告中展示迭代趋势 |
| **发布决策** | PASS / CONDITIONAL PASS / FAIL，含 S/A/B/C 四级准入阈值 |

---

## 快速开始

```
帮我测一下 my-skill-name
```

或者指定路径：

```
测评这个 skill：/path/to/your-skill/SKILL.md
```

**SkillSentry 会自动**：
1. 检测 Skill 类型，选择对应执行模式和文件隔离结构
2. 创建 `inputs/<Skill名>/` 素材目录，并**主动告知完整路径**——你只需把测试文件放进去即可
3. 运行触发率 AI 模拟预评估
4. 扫描 `inputs/<Skill名>/` 下的素材和自定义用例
5. 引导你选择测评模式（quick / standard / full）
6. 执行测评，生成 HTML 报告，给出发布决策

---

## 测评模式

| 模式 | 覆盖率目标 | 每用例运行次数 | 适用场景 |
|------|----------|------------|---------|
| **quick** | ≥ 40% | 2 次（取均值，差距 >15% 报告标红） | 快速冒烟、Bug 修复验证 |
| **standard** | ≥ 70% | 3 次 | 常规迭代发布（推荐） |
| **full** | ≥ 90% | 3 次 | S/A 级关键业务正式发布 |

---

## 执行可信度设计

SkillSentry 通过以下机制保障测评结论的可信度，而不是依赖 AI「感觉正确」：

**文件系统隔离**：with_skill 和 without_skill 各自运行在独立 workspace 沙箱中，禁止跨目录读取。审计发现若不隔离，without_skill 会「借用」with_skill 上传的文件，导致 Δ 被系统性低估。

**transcript 双分离格式**：执行日志强制分为 `[tool_calls]`（MCP/Bash 原始返回，一字不改）和 `[agent_notes]`（AI 主观解释）两个区块。Grader 优先引用 `[tool_calls]` 作为 evidence，只有 `[agent_notes]` 支撑而无 `[tool_calls]` 佐证的断言直接判 FAIL。

**断言强度分级**：每条断言标注 `precision`（精确★ / 语义◆ / 存在性○），准入判断只看精确断言通过率。存在性断言（如「输出非空」）不计入准入，避免通过率虚高。

**quick 双次运行**：quick 模式强制运行 2 次取均值，两次差距 > 15% 时报告标红「结果不稳定」，发布决策自动降为 CONDITIONAL PASS。

**触发率置信度门槛**：触发率 AI 估算置信度 low、TP 估算 < 70% 或 TN 有误触发时，S/A 级发布决策强制降为 CONDITIONAL PASS，不允许静默放行。

---

## 目录结构

```
SkillSentry/
├── SKILL.md                    # 主定义文件（AI 执行规程）
├── README.md                   # 本文件
├── agents/
│   ├── grader.md               # 独立评审 Agent（支持3种 Skill 类型 + 断言强度分级）
│   ├── comparator.md           # 盲测对比 Agent
│   └── analyzer.md             # 根因分析 Agent
├── references/
│   ├── eval-dimensions.md      # 9 层测评维度详解
│   ├── admission-criteria.md   # S/A/B/C 发布准入阈值表（含断言分级规则）
│   ├── case-matrix-templates.md # 7 类用例 + 断言写法模板
│   ├── report-template.md      # 12 章 HTML 报告模板
│   ├── custom-cases-template.md # 自定义用例填写模板
│   └── skill-creator-capability-notes.md # 与 skill-creator 的能力关系说明
├── scripts/
│   └── generate_html_report.py # HTML 报告生成脚本
├── inputs/                     # 各 Skill 测评素材（测评启动时自动创建对应子目录并告知路径）
│   └── <skill-name>/           # SkillSentry 自动创建，放入 PDF、图片、.cases.md 等测试素材
└── sessions/                   # 测评结果（自动生成，永不覆盖）
    └── <skill-name>/<date>_NNN/
```

---

## 模型路由（可选，锦上添花）

SkillSentry 默认使用单一模型完成所有角色（执行、评审、对比）。这在绝大多数场景下已经足够可信，原因如下：

**为什么单模型已经足够？**

1. **上下文天然隔离**：OpenCode 的每个 subagent 都运行在全新的、独立的上下文中，不继承任何父级对话历史（来源：[OpenCode Agents 文档](https://opencode.ai/docs/agents/)）。Grader 启动时完全不知道 transcript 是谁生成的，「自我评审」这件事在上下文层面就已经不存在。
2. **核心断言是事实判断，不是风格判断**：SkillSentry 的准入判断依赖 `exact_match` 精确断言（如「docStatus 字段值是否等于 10」）。这类判断没有风格偏好空间，无论哪个模型来评审，结论是一样的。
3. **Self-Preference Bias 的适用场景不符**：学术研究（Zheng et al. 2023, MT-Bench, arXiv:2306.05685）揭示的模型自我偏好，主要出现在「开放式内容质量评分」场景，而不是结构化事实校验场景。

**异构模型有没有任何价值？**

有，但很有限，仅在一个场景有微弱收益：**Comparator（盲测对比）对纯文本生成型 Skill 的主观质量评分**。这类断言是 semantic 级别，确实存在风格偏好空间。但 Comparator 的结论在报告里属于参考性指标，不是发布决策的硬性依据。

**结论：不配置也没问题，配了也没坏处。**

如果你有多厂商 API Key 且希望追求极致的评审独立性，可以按以下方式配置。配置后 Grader subagent 会使用你指定的模型，其余逻辑完全不变。

### 配置方式（仅供参考）

**Step 1：添加第二个 Provider 的 API Key**

在 OpenCode TUI 里执行 `/connect`，选择对应 Provider，输入 API Key。Key 安全存储在 `~/.local/share/opencode/auth.json`，不会出现在任何配置文件里：

```
/connect
```

**Step 2：在 `opencode.json` 里定义专用 Agent**

```json
{
  "$schema": "https://opencode.ai/config.json",
  "agent": {
    "skillsentry-grader": {
      "description": "SkillSentry 评审层：独立审计 transcript，输出 grading.json",
      "mode": "subagent",
      "model": "openai/gpt-4o",
      "hidden": true,
      "temperature": 0.1,
      "permission": {
        "edit": "deny",
        "bash": "deny"
      }
    }
  }
}
```

> `opencode.json` 只写模型和权限配置，不写任何 Key，可以安全提交到 git。

---

| 局限 | 说明 |
|------|------|
| 触发率精确测量 | 当前为 AI 模拟估算；精确测量需 claude CLI + skill-creator `run_eval.py` |
| description 自动优化 | 依赖触发率精确测量，待后续集成 |
| 实时 live report | 当前报告在测评完成后生成 |

---

*Last Updated: 2026-03-26*
