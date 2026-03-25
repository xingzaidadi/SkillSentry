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
| **外部用例导入** | 在 `inputs/<Skill名>/` 下放 `.cases.md`，自动识别为「黄金用例」优先测试 |
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
2. 运行触发率 AI 模拟预评估
3. 扫描 `inputs/<Skill名>/` 下的素材和自定义用例
4. 引导你选择测评模式（quick / standard / full）
5. 执行测评，生成 HTML 报告，给出发布决策

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
├── SkillSentry_快速上手指南.md   # 详细操作手册
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
├── inputs/                     # 各 Skill 测评素材（一 Skill 一文件夹）
│   └── <skill-name>/           # 放 PDF、图片、.cases.md 等
└── sessions/                   # 测评结果（自动生成，永不覆盖）
    └── <skill-name>/<date>_NNN/
```

---

## 模型路由（可选增强）

默认情况下，SkillSentry 的 Executor（执行层）和 Grader（评审层）使用同一个模型。如果希望提升评审独立性，可以配置异构模型路由，让两个角色使用不同厂商的模型。

**效果**：执行用 Claude，评审用 GPT-4o → 消除同模型自我评审偏差，评审结论更客观。

### 配置步骤

**Step 1：添加第二个 Provider 的 API Key**

OpenCode 的 API Key 通过 `/connect` 命令添加，**统一存储在 `~/.local/share/opencode/auth.json`**，不会出现在任何配置文件里，提交 git 也不会泄漏。

在 OpenCode TUI 里执行：
```
/connect
```

选择对应 Provider（如 OpenAI），输入 API Key，回车确认：
```
┌ Select provider
│
│  ● OpenAI
│  ● Anthropic
│  ● ...
└

┌ API key
│
└ sk-...（粘贴你的 OpenAI API Key）
```

Key 保存成功后，`auth.json` 内容类似：
```json
{
  "anthropic": { "api_key": "sk-ant-..." },
  "openai":    { "api_key": "sk-..."     }
}
```

此文件在你的本地机器上，**不要手动编辑，不要提交到 git**。

**Step 2：在 `opencode.json` 里定义两个专用 Agent**

`opencode.json` 只写模型和权限配置，**不写任何 Key**：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "agent": {
    "skillsentry-executor": {
      "description": "SkillSentry 执行层：真实运行被测 Skill，记录 transcript",
      "mode": "subagent",
      "model": "anthropic/claude-sonnet-4-20250514",
      "hidden": true,
      "permission": {
        "edit": "allow",
        "bash": "allow"
      }
    },
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

> **`opencode.json` 放在哪里？**
> - 全局生效：`~/.config/opencode/opencode.json`（推荐，对所有项目生效）
> - 仅项目生效：项目根目录下的 `opencode.json`

**Step 3：验证配置生效**

下次触发 SkillSentry 时，启动阶段会自动输出：
```
🔧 测评环境 · 模型配置
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
执行层 (Executor)  ：anthropic/claude-sonnet-4-20250514
评审层 (Grader)    ：openai/gpt-4o  ← 异构模型 ✅
对比层 (Comparator)：anthropic/claude-sonnet-4-20250514
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
模式：双模型交叉评审（执行与评审使用不同厂商模型，评审独立性更高）
```

如果看到「单模型模式」提示，说明 Step 2 的配置未生效，检查 `opencode.json` 路径和 agent 名称是否完全一致（`skillsentry-executor` / `skillsentry-grader`）。

### 常见问题

**Q：不配置的话能不能正常使用？**
可以。未配置时自动降级为单模型模式，全程使用当前默认模型，功能完整，只是 Grader 和 Executor 同模型。

**Q：用哪个模型做 Grader 效果最好？**
推荐和 Executor 使用不同厂商的模型。Executor 用 Claude → Grader 用 GPT-4o 或 DeepSeek；Executor 用 GPT-4o → Grader 用 Claude。核心原则是不同厂商，消除系统性偏差。

**Q：auth.json 在哪里，怎么确认 Key 加进去了？**
路径：`~/.local/share/opencode/auth.json`。可以用下面的命令确认：
```bash
cat ~/.local/share/opencode/auth.json
```
看到对应 provider 有 `api_key` 字段即表示添加成功。

---

| 局限 | 说明 |
|------|------|
| 触发率精确测量 | 当前为 AI 模拟估算；精确测量需 claude CLI + skill-creator `run_eval.py` |
| description 自动优化 | 依赖触发率精确测量，待后续集成 |
| 实时 live report | 当前报告在测评完成后生成 |

---

*Last Updated: 2026-03-24*
