# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

支持平台：**Claude Code** · **OpenCode**

---

## 安装（2 步）

**第一步：克隆仓库**

```bash
git clone https://github.com/xingzaidadi/SkillSentry.git
cd SkillSentry
```

**第二步：运行安装脚本**

```bash
# macOS / Linux / WSL
bash install.sh
```

```powershell
# Windows PowerShell
.\install.ps1
```

脚本会自动检测你安装了 Claude Code 还是 OpenCode（或两者都有），并把所有文件部署到正确位置。安装完成后输出验证结果：

```
📦 安装到 Claude Code（~/.claude/skills）
  ✅ SkillSentry
  ✅ sentry-lint
  ✅ sentry-trigger
  ✅ sentry-cases
  ✅ sentry-executor
  ✅ sentry-report

🎉 安装完成！
```

**验证安装是否生效**（安装后可随时运行）：

```
验证 SkillSentry 安装
```

在 Claude Code / OpenCode 中说这句话，系统会列出找到的所有工具。

---

## 第一次使用

确保你要测的 Skill 放在正确位置：

| 平台 | 路径 |
|------|------|
| Claude Code | `~/.claude/skills/<Skill名>/SKILL.md` |
| OpenCode | `~/.config/opencode/skills/<Skill名>/SKILL.md` |

然后直接说：

```
测评 <你的Skill名>
```

**不需要你选模式**——系统根据状态自动推荐：

| 你的情况 | 推荐工作流 | 时间 |
|---------|-----------|------|
| 第一次测这个 Skill | quick（完整流程） | ~15-20 分钟 |
| 改了规则，验证没崩 | smoke（快速冒烟） | ~5-7 分钟 |
| 规则没变，复跑基准 | regression（直接跑） | ~5-10 分钟 |

收到推荐后，回「开始」确认，或直接说「full」「quick」「smoke」换一个。

> **Token 消耗参考**：quick 模式约 5-10 万 token；smoke 约 1-2 万 token；regression 约 3-5 万 token。

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

测评启动后，系统会自动创建并告知路径：

```
~/.claude/skills/SkillSentry/inputs/<Skill名>/
```

把以下文件放进去，系统自动识别纳入测评：

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

```
发布决策：PASS S级 / CONDITIONAL PASS / FAIL

精确通过率：92%（准入依据）
语义通过率：88%（参考）
P95 响应时间：8.2s
```

| 等级 | 精确通过率 | 含义 |
|------|----------|------|
| S | ≥ 95% | 可直接发布 |
| A | ≥ 90% | 可发布 |
| B | ≥ 80% | 建议修复后发布 |
| C | ≥ 70% | 需修复 |
| FAIL | < 70% | 不可发布 |

完整报告保存为 HTML：
- **macOS / Linux**：`~/.claude/skills/SkillSentry/sessions/<Skill名>/<日期>/report.html`
- **Windows**：`C:\Users\<你的用户名>\.claude\skills\SkillSentry\sessions\<Skill名>\<日期>\report.html`

---

## 目录结构

```
SkillSentry/                   ← 克隆这一个仓库即可
├── SKILL.md                   # 主编排器
├── README.md
├── install.sh                 # macOS/Linux 安装脚本
├── install.ps1                # Windows 安装脚本
├── tools/                     # 各 sentry-* 工具源文件（安装脚本从这里部署）
│   ├── sentry-lint/SKILL.md
│   ├── sentry-trigger/SKILL.md
│   ├── sentry-cases/SKILL.md
│   ├── sentry-executor/SKILL.md
│   └── sentry-report/SKILL.md
├── agents/
│   ├── grader.md
│   ├── comparator.md
│   └── analyzer.md
├── references/
│   ├── eval-dimensions.md
│   ├── admission-criteria.md
│   ├── case-matrix-templates.md
│   ├── report-template.md
│   ├── custom-cases-template.md
│   └── execution-phases.md
├── inputs/                    # 测评素材（测评启动时自动创建子目录）
└── sessions/                  # 测评结果（自动生成，永不覆盖）
```

---

## 常见问题

**Q：测评的 Skill 必须有 MCP 工具吗？**
A：不是。`sentry-lint` 和 `sentry-trigger` 纯静态分析，不需要任何工具连接。执行测试时，如果被测 Skill 依赖 MCP 工具，系统会在执行前检查工具是否可用；不可用时提示你而不是静默跑出假结果。

**Q：第一次跑要多久？**
A：quick 模式约 15-20 分钟。之后规则和用例有缓存，regression 模式只需 5-10 分钟。

**Q：能测自己写的任何 Skill 吗？**
A：能，只要有 `SKILL.md` 文件。SkillSentry 会自动识别 Skill 类型（mcp_based / text_generation / code_execution）并切换对应执行模式。

**Q：测评过程中断了怎么办？**
A：已完成的用例 transcript 保存在 sessions/ 目录中。重新说「测评 xxx」，系统会检测已有结果，提示你「已有 N 个用例完成，是否跳过直接进入评分」。

**Q：测评结果存在哪里？**
A：`SkillSentry/sessions/<Skill名>/<日期>_<序号>/`，永不覆盖，可以对比不同版本。

**Q：Claude Code 和 OpenCode 可以共用同一份测评结果吗？**
A：不能直接共用，两个平台的 sessions/ 目录是独立的。但 inputs/<Skill名>/ 里的自定义用例两者都会读取（如果 inputs 目录在同一路径下）。

---

*Last Updated: 2026-04-09*
