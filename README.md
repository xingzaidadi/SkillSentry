# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

---

## 5 分钟安装

**前提**：已安装 [Claude Code](https://claude.ai/code)。

**第一步：下载文件**

```bash
# 克隆或下载整个 SkillSentry 仓库
git clone https://github.com/xingzaidadi/SkillSentry.git
```

**第二步：把 6 个目录放到 Claude Code 的 skills 文件夹**

```bash
# macOS / Linux
SKILLS_DIR="$HOME/.claude/skills"

cp -r SkillSentry/         "$SKILLS_DIR/"
cp -r sentry-lint/         "$SKILLS_DIR/"
cp -r sentry-trigger/      "$SKILLS_DIR/"
cp -r sentry-cases/        "$SKILLS_DIR/"
cp -r sentry-executor/     "$SKILLS_DIR/"
cp -r sentry-report/       "$SKILLS_DIR/"
```

```powershell
# Windows（PowerShell）
$skills = "$env:USERPROFILE\.claude\skills"

foreach ($t in @("SkillSentry","sentry-lint","sentry-trigger","sentry-cases","sentry-executor","sentry-report")) {
    Copy-Item -Recurse -Force $t "$skills\"
}
```

安装完毕。`~/.claude/skills/` 下应该多出这 6 个目录。

---

## 第一次使用（30 秒）

确保你要测的 Skill 放在 `~/.claude/skills/<名字>/SKILL.md`，然后打开 Claude Code，直接说：

```
测评 <你的Skill名字>
```

例如：

```
测评 em-reimbursement-v3
```

**系统会自动**：
1. 找到 Skill 文件
2. 检测上次测评状态，推荐最合适的工作流
3. 等你确认（或 30 秒后自动开始）
4. 执行测评，输出报告

**不需要你选模式**。系统根据当前状态自动推荐：

| 你的情况 | 系统推荐 | 时间 |
|---------|---------|------|
| 第一次测这个 Skill | quick（完整流程） | ~15-20 分钟 |
| 改了几行规则，验证没崩 | smoke（快速冒烟） | ~5-7 分钟 |
| 规则没变，用已有用例复跑 | regression（直接跑） | ~5-10 分钟 |

收到推荐后，直接回「开始」，或说「full」「quick」「smoke」换一个。

---

## 常用快捷调用

不想跑完整流程？直接说单工具：

| 说这个 | 做这个 | 时间 |
|--------|--------|------|
| `检查结构 <Skill名>` | 静态检查 HiL、复杂度、冗余规则 | ~30 秒 |
| `测触发率 <Skill名>` | 验证 description 触发是否准确 | ~2 分钟 |
| `设计用例 <Skill名>` | 只出 evals.json，不执行 | ~5-10 分钟 |
| `出报告` | 基于已有结果生成报告 | ~1 分钟 |

---

## 放入自己的测试素材（可选）

测评启动后，系统会自动创建：

```
~/.claude/skills/SkillSentry/inputs/<Skill名>/
```

把以下文件放进去，系统会自动识别并纳入测评：

| 文件类型 | 用途 |
|---------|------|
| `*.cases.md` | 自定义测试用例（格式见 `references/custom-cases-template.md`） |
| `*.pdf` / `*.png` | 测试素材（发票、截图等），供测试用例引用 |

---

## 工作流一览

| 工作流 | 工具链 | 时间 | 适用场景 |
|--------|--------|------|---------|
| smoke | cases(4-5个) → executor(1次) → grader → report | 5-7 分钟 | 改了规则，快速确认没崩 |
| quick | cases → executor(2次) → grader → report | 15-20 分钟 | 迭代完成，准备提测 |
| regression | executor(已有用例) → grader → report | 5-10 分钟 | 规则没变，复跑基准 |
| standard | cases → executor(3次) → grader → comparator → report | 30-45 分钟 | 重要迭代正式提测 |
| full | lint → trigger → cases → executor(3次) → grader → comparator → analyzer → report | 45 分钟+ | 正式发布前全量验证 |

---

## 报告怎么看

测评完成后输出：

```
发布决策：PASS S级 / CONDITIONAL PASS / FAIL

精确通过率：92%（准入依据）
语义通过率：88%（参考）
P95 响应时间：8.2s
```

**只看精确通过率**——存在性断言（如「输出非空」）不计入准入，避免虚高。

| 等级 | 精确通过率 | 含义 |
|------|----------|------|
| S | ≥ 95% | 可直接发布 |
| A | ≥ 90% | 可发布 |
| B | ≥ 80% | 建议修复后发布 |
| C | ≥ 70% | 需修复 |
| FAIL | < 70% | 不可发布 |

完整报告保存为 HTML，路径在输出末尾提示。

---

## 目录结构

```
SkillSentry/
├── SKILL.md                    # 主编排器（AI 执行规程）
├── README.md                   # 本文件
├── agents/
│   ├── grader.md               # 独立评审 Agent
│   ├── comparator.md           # 盲测对比 Agent
│   └── analyzer.md             # 根因分析 Agent
├── references/
│   ├── eval-dimensions.md      # 测评维度详解
│   ├── admission-criteria.md   # 发布准入阈值
│   ├── case-matrix-templates.md
│   ├── report-template.md
│   ├── custom-cases-template.md
│   └── execution-phases.md     # 工具间数据接口定义
├── inputs/                     # 测评素材（测评启动时自动创建子目录）
└── sessions/                   # 测评结果（自动生成，永不覆盖）
```

独立工具目录（安装在同级）：

```
~/.claude/skills/
├── sentry-lint/      # 静态结构检查
├── sentry-trigger/   # 触发率评估
├── sentry-cases/     # 用例设计
├── sentry-executor/  # 用例执行
└── sentry-report/    # 报告生成
```

---

## 常见问题

**Q：测评的 Skill 必须有 MCP 工具吗？**
A：不是。`sentry-lint` 和 `sentry-trigger` 纯静态分析，不需要任何工具连接。`sentry-executor` 执行时会调用 Skill 定义的工具，Skill 没有工具就测文本生成能力。

**Q：第一次跑要多久？**
A：quick 模式约 15-20 分钟。之后如果 SKILL.md 没有改动，regression 模式只需 5-10 分钟。

**Q：能测自己写的任何 Skill 吗？**
A：能，只要有 `SKILL.md` 文件。SkillSentry 会自动识别 Skill 类型（mcp_based / text_generation / code_execution）并切换对应执行模式。

**Q：测评结果存在哪里？**
A：`SkillSentry/sessions/<Skill名>/<日期>_<序号>/`，永不覆盖，可以对比不同版本的测评结果。

---

*Last Updated: 2026-04-09*
