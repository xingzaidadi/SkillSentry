---
name: SkillSentry
description: >
  SkillSentry — AI Skill 质量测评系统。
  触发场景：说"测评/测试/验证/评估某个Skill"、"这个skill好不好用"、"能不能上线"、"帮我跑eval"、"Skill质量怎么样"、"上线前先测一下"、"发布前检查"。
  不触发场景：讨论Skill设计思路、修改Skill内容、优化SKILL.md的description、写新的SKILL.md、讨论测评方法论、问「触发场景写得好不好」、泛泛聊AI话题。
---

# SkillSentry · AI Skill 质量守门人

极简调度器：找 Skill → 选模式 → 按顺序调子工具 → 每步等用户确认。

## 子工具

| 工具 | 职责 |
|------|------|
| `sentry-lint` | 静态结构检查 |
| `sentry-trigger` | 触发率模拟评估 |
| `sentry-cases` | 测试用例设计 |
| `sentry-executor` | 用例执行 |
| `sentry-grader` | 断言评审 |
| `sentry-report` | 报告 + 发布决策 + HiL 确认 |

**触发优先级**：主编排器 > 子工具。用户说「测评 xxx」→ 主编排器响应。说「帮我 lint xxx」→ 直接调子工具。
**追问规则**：能推断的不问，最多追问 1 轮。默认 quick 模式。
**飞书同步**：用例和结果自动同步到飞书多维表格（通过 sentry-sync）。executor 执行前 PULL，report 完成后 PUSH。

---

## Step 1：找 Skill + 初始化

1. 找 SKILL.md：用户给路径 → 直接用；给名字 → `~/.openclaw/skills/<名字>/` 或 `~/.config/opencode/skills/<名字>/`
2. 找不到 → 「❌ 找不到 Skill：{name}。已搜索：{paths}。请确认拼写或提供完整路径。」
3. 创建工作目录：`sessions/<skill_name>/<YYYY-MM-DD>_<NNN>/`
4. 写 `session.json`（workspace_dir / inputs_dir / skill_name / skill_path / skill_type / mode / created_at / last_step）
5. 所有路径必须是绝对路径

检测 skill_type：含 MCP 工具引用 → mcp_based；含 exec/bash → code_execution；其他 → text_generation。

**MCP 预检（仅 mcp_based）**：
1. 从 SKILL.md 提取引用的 MCP Server 名称
2. 运行 `mcporter list` 检查哪些已配置且健康
3. 对比结果：
   - 全部可用 → 「✅ MCP 预检通过：{N} 个 Server 全部健康」
   - 部分缺失 → 「⚠️ {name} 未配置。继续（结果不完整）/ 中止？」
   - 全部不可用 → 「❌ 所有 MCP Server 不可用，无法测评。请先配置 MCP。」

输出：「✅ Step 1 完成 | {skill_name} | {skill_type} | MCP {N}/{M} 可用 | 工作目录已创建」

---

## Step 2：选模式

| 模式 | 步骤 | 预计时间 |
|------|------|---------|
| smoke | lint → cases(5个) → executor(1次) → grader → report | ~5min |
| quick | lint → cases → executor(2次) → grader → report | ~10min |
| standard | lint → trigger → cases → executor(3次) → grader → comparator → report | ~30min |
| full | lint → trigger → cases → executor(3次) → grader → comparator → analyzer → report | ~45min |

默认 quick。用户说「冒烟」→ smoke；「提测前」→ standard；「正式发布前」→ full。

输出：「📋 模式：{mode} | 步骤：{步骤列表} | 预计 {时间}」
等用户确认（60s 无回复自动继续）。

---

## Step 3：执行循环（核心）

**对当前模式的每个步骤，依次执行：**

```
1. 读取该子工具的 SKILL.md（如 sentry-lint/SKILL.md）
2. 按子工具 SKILL.md 的指令执行（子工具自己决定怎么做）
3. 输出进度回执：
   ✅ {步骤名} 完成 | ⏱ {耗时} | 进度 [{进度条}] {N}/{总数}
   {1-2 行关键数据}
4. 【检查点】输出三段式回执：
   ① 结果小结：刚才发现了什么，有什么问题，是否影响继续
   ② 下一步预告：接下来要做什么，大约要多久
   ③ 用户选项：继续 / 跳过 / 中止 / 重跑 / 切换模式
   （60s 无回复 → 自动继续）
5. 更新 session.json 的 last_step
```

**强制规则**：
- 每个步骤完成后**必须停下来**输出进度并等待，不能连续执行多个步骤
- 子工具通过 session.json 获取路径和参数，不靠 AI 记忆传递
- 子工具的实现细节在各自 SKILL.md 里，主编排器不重复

---

## Pipeline 准出标准

| 步骤 | 准出条件 | 未通过处理 |
|------|---------|----------|
| lint | 无 P0 红线 | 暂停，提示先修复 |
| trigger | TP ≥ 70% | 警告 + 建议优化 description |
| cases | 用例数 ≥ 3 | 警告「覆盖不足」 |
| executor | ≥ 1 个有 transcript | 全失败 → 终止，报告环境问题 |
| grader | ≥ 1 个有 grading | 全超时 → 标注「评审缺失」 |
| report | HTML 生成成功 | 失败 → 纯文本摘要替代 |

---

## 异常话术

| 场景 | 输出 |
|------|------|
| SKILL.md 找不到 | ❌ 找不到 Skill：{name}。已搜索：{paths}。 |
| evals.json 为空 | ⚠️ 无用例可执行。请先运行 sentry-cases。 |
| subagent 超时 | ⚠️ eval-{N} 超时（{X}s），降级到主会话直跑。 |
| Grader 超时 | ⚠️ Grader 超时，eval-{N} 评审缺失。 |
| MCP 不可用 | ⚠️ {tool} 不可用。继续（结果不准）/ 中止？ |
| session.json 缺失 | ❌ session.json 未找到，请从 Step 1 重新开始。 |

---

## 单工具快速调用

用户明确指定子工具时，跳过编排流程，直接调用：

| 用户说 | 直接调用 |
|--------|---------|
| 帮我 lint xxx | sentry-lint |
| 跑测试用例 | sentry-executor |
| 出报告 | sentry-report |
| 帮我评审 | sentry-grader |

---

## 安全约束

with_skill 和 without_skill 必须使用完全独立的工作目录，互不可读。

---

## 飞书同步（sentry-sync）

| 时机 | 操作 | 说明 |
|------|------|------|
| executor 执行前 | PULL | 从飞书拉取 active 用例合并到 evals.json |
| report 完成后 | PUSH 结果 | 写入运行记录（等级/通过率/Δ） |
| report 完成后 | PUSH 新用例 | 推送 AI 生成的用例到飞书待 Review |

前提：`~/.openclaw/skills/SkillSentry/config.json` 存在。不存在则跳过同步。

---

*v5.0 · 极简调度器重构 · 2026-04-24*
