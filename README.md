# SkillSentry · AI Skill 质量守门人

> 让每一个上线的 Skill 都经过可追溯、可信赖的真实验证——而不是凭感觉说「应该没问题」。

支持平台：**Claude Code** · **OpenCode** · **OpenClaw（飞书）**

---

## 三句话速查

```
# 姿势 1：最常用，系统自动推荐工作流
测评 <Skill名>

# 姿势 2：只做某一步
check <Skill名>         →  静态检查 + 触发率（~3 分钟）
lint <Skill名>           →  30 秒静态检查
测触发率 <Skill名>       →  2 分钟验证 description
设计用例 <Skill名>       →  5-10 分钟出 evals.json，不执行
出报告                   →  1 分钟，基于已有结果

# 姿势 3：指定深度
smoke 测评 <Skill名>     →  5-7 分钟，改了规则先跑这个
quick 测评 <Skill名>     →  15-20 分钟，提测前用
full 测评 <Skill名>      →  45 分钟+，正式发布前用
```

---

## 安装（2 步）

**第一步：获取代码**

```bash
# 方式一：克隆仓库
git clone https://github.com/xingzaidadi/SkillSentry.git
cd SkillSentry

# 方式二：下载 tar.gz 并解压
tar xzf SkillSentry-v7.0.tar.gz
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

脚本自动检测平台（Claude Code / OpenCode / OpenClaw），部署到正确位置：

```
📦 安装到 OpenClaw（~/.openclaw/skills）
  ✅ SkillSentry（主编排 v7.0）
  ✅ sentry-check
  ✅ sentry-cases
  ✅ sentry-executor
  ✅ sentry-grader
  ✅ sentry-report
  📦 sentry-openclaw（归档 stub）
  📦 sentry-sync（归档 stub）
  📦 sentry-lint（归档 stub）
  📦 sentry-trigger（归档 stub）
  ✅ workspace 运行时目录已创建

🎉 安装完成！
```

**验证安装**：

```
验证 SkillSentry 安装
```

---

## 第一次使用

确保你要测的 Skill 放在正确位置：

| 平台 | 路径 |
|------|------|
| Claude Code | `~/.claude/skills/<Skill名>/SKILL.md` |
| OpenCode | `~/.config/opencode/skills/<Skill名>/SKILL.md` |
| OpenClaw | `~/.openclaw/skills/<Skill名>/SKILL.md` |

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

> **Token 消耗参考**：quick 约 5-10 万 token；smoke 约 1-2 万 token；regression 约 3-5 万 token。

---

## 工具组成（v7.0）

| 工具 | 职责 | 独立可用 |
|------|------|---------|
| **SkillSentry** | 主编排 + 平台适配 + 飞书同步 | — |
| **sentry-check** | 静态检查（L1-L5）+ 触发率（TP/TN） | ✅ |
| **sentry-cases** | 测试用例设计，输出 evals.json | ✅ |
| **sentry-executor** | 用例并行执行，输出 transcript | ✅ |
| **sentry-grader** | 断言评审，输出 grading.json | ✅ |
| **sentry-report** | 报告生成 + 发布决策 + HiL 确认 | ✅ |

> v7.0 变更：sentry-lint + sentry-trigger 合并为 **sentry-check**；sentry-openclaw + sentry-sync 内联进主编排。旧工具保留归档 stub 保证向后兼容。

---

## 工作流一览

| 工作流 | 工具链 | 时间 | 适用场景 |
|--------|--------|------|---------|
| smoke | cases(4-5个) → executor(1次) → grader → report | 5-7 分钟 | 改了规则，快速确认没崩 |
| quick | check → cases → executor(2次) → grader → report | 15-20 分钟 | 迭代完成，准备提测 |
| regression | executor(已有用例) → grader → report | 5-10 分钟 | 规则没变，复跑基准 |
| standard | check → cases → executor(3次) → grader → comparator → report | 30-45 分钟 | 重要迭代正式提测 |
| full | check → cases → executor(3次) → grader → comparator → analyzer → report | 45 分钟+ | 正式发布前全量验证 |

---

## 飞书同步（OpenClaw 专属）

配置 `config.json`（参考 `config.example.json`）后自动启用：

- **PULL**：执行前从飞书拉取 active 用例
- **PUSH-CASES**：新用例推送到飞书（pending_review）
- **PUSH-RESULTS**：评审结果回写到用例记录
- **PUSH-RUN**：运行记录写入飞书

不配置 = 纯本地模式，不影响核心测评流程。

---

## 报告怎么看

| 等级 | 精确通过率 | 含义 |
|------|----------|------|
| S | ≥ 95% | 可直接发布 |
| A | ≥ 90% | 可发布 |
| B | ≥ 80% | 建议修复后发布 |
| C | ≥ 70% | 需修复 |
| FAIL | < 70% | 不可发布 |

---

## 目录结构（打包格式）

```
SkillSentry/
├── SKILL.md                   # 主编排（v7.0）
├── README.md
├── config.example.json        # 飞书同步配置模板
├── install.sh / install.ps1   # 安装脚本
├── tools/                     # 子工具（install.sh 展开到 skills/ 并列目录）
│   ├── sentry-check/SKILL.md      ← v7.0 新增（lint + trigger 合并）
│   ├── sentry-cases/SKILL.md
│   ├── sentry-executor/SKILL.md
│   ├── sentry-grader/SKILL.md
│   ├── sentry-report/SKILL.md
│   ├── sentry-openclaw/SKILL.md   ← 归档 stub
│   ├── sentry-sync/SKILL.md       ← 归档 stub
│   ├── sentry-lint/SKILL.md       ← 归档 stub
│   └── sentry-trigger/SKILL.md    ← 归档 stub
├── agents/
│   ├── grader.md
│   ├── comparator.md
│   └── analyzer.md
├── scripts/                   # Python 脚本
│   ├── validate_step.py       # OpenClaw 步骤校验
│   ├── verify_proof.py        # CLI 读取证明校验
│   ├── generate_html_report.py
│   └── ...
├── references/                # 参考文档
│   ├── feishu-templates.md
│   ├── report-template.md
│   ├── execution-phases.md
│   └── ...
└── inputs/                    # 测评素材（按 Skill 名隔离）
```

---

## 常见问题

**Q：测评的 Skill 必须有 MCP 工具吗？**
A：不是。`sentry-check` 纯静态分析，不需要工具连接。执行测试时，如果被测 Skill 依赖 MCP 工具，系统会在执行前检查可用性。

**Q：第一次跑要多久？**
A：quick 模式约 15-20 分钟。之后有缓存，regression 只需 5-10 分钟。

**Q：能测自己写的任何 Skill 吗？**
A：能，只要有 `SKILL.md`。自动识别类型（mcp_based / text_generation / code_execution）。

**Q：测评中断了怎么办？**
A：已完成的 transcript 保存在 sessions/。重新说「测评 xxx」，系统检测已有结果，提示跳过。

**Q：sentry-lint / sentry-trigger 还能用吗？**
A：说 `lint xxx` 或 `测触发率 xxx` 会自动路由到 `sentry-check`。旧工具保留归档 stub 保证兼容。

---

*v7.0 · 2026-04-27*
