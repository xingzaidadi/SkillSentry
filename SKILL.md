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

### 特殊命令

| 用户说 | 动作 |
|--------|------|
| 「验证安装」「验证 SkillSentry」 | 检查所有 sentry-* 工具是否存在，逐一列出 ✅/❌ |

### 素材自动存档

用户发文件 + 说「存到 xxx 测评素材」「给 xxx 测评用的」时：
1. 提取 Skill 名称
2. 保存到 `inputs/<skill名>/`（保留原始文件名）
3. 回执：「✅ 已存入 inputs/<skill名>/<文件名>」

---

## Step 1：找 Skill + 初始化

1. 找 SKILL.md：用户给路径 → 直接用；给名字 → `~/.openclaw/skills/<名字>/` 或 `~/.config/opencode/skills/<名字>/`
2. 找不到 → 「❌ 找不到 Skill：{name}。已搜索：{paths}。请确认拼写或提供完整路径。」
3. 检查 config.json：不存在时询问「是否要启用飞书同步？启用可在飞书多维表格中管理用例和查看报告」
   - 用户说是 → 自动创建 Bitable + 写入 config.json
   - 用户说否 → 跳过，纯本地模式
   - 已存在 → 跳过
4. 创建工作目录：`sessions/<skill_name>/<YYYY-MM-DD>_<NNN>/`
5. 写 `session.json`（workspace_dir / inputs_dir / skill_name / skill_path / skill_type / mode / created_at / last_step）
6. 所有路径必须是绝对路径
7. 检测运行环境：来自飞书/Telegram → runtime="openclaw"；其他 → runtime="cli"。写入 session.json。

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

**自动模式**：用户说「自动」「全自动」「--ci」时：
- 检查点：**不等确认，但每步必须输出关键数据**（不停但要说，不能只说「完成」，必须包含具体结果）
- 测试数据：有缓存→复用（**展示复用了哪些数据**）；无缓存→自动查→查到用→没查到→**暂停自动，问用户要数据**（唯一打断自动的场景）
- 读取证明：仍然强制校验（跳过检查点 ≠ 跳过读取验证）
- HiL 确认：**不跳过**（发布决策必须人工确认）

示例：「测评 em-reimbursement-v3 standard 自动」→ standard 模式 + 自动执行

输出：「📋 模式：{mode} | 步骤：{步骤列表} | 预计 {时间} | 自动模式：{是/否}」
非自动模式：等用户确认（60s 无回复自动继续）。
自动模式：直接开始，不等确认。

---

## Step 3：执行循环（核心）

### 缓存复用规则

每步执行前检查是否有可复用的缓存：
- SKILL.md hash 一致 + 产物文件存在 → **复用**，输出「⚡ 缓存命中（上次 xxx）」+ 展示复用了什么数据
- SKILL.md hash 不一致 → **不复用**，重新执行
- 用户说「重跑 xxx」「清缓存」 → **不复用**

复用时必须明确展示：复用了哪些数据（用例数/测试单号/transcript数），并提示「如需重跑 → 说『重跑 xxx』」。

**对当前模式的每个步骤，依次执行：**

```
1. **强制读取**该子工具的 SKILL.md（用 read 工具，不能凭记忆）
2. 按子工具 SKILL.md 的指令执行（子工具自己决定怎么做）
   ⛔ 禁止凭记忆执行子工具逻辑。必须先 read 再执行。上下文再长也不能跳过读取。
   
   **读取证明校验**（所有模式强制，含全自动）：子工具执行完后，检查输出是否包含 `[sentry-proof]` 标记。
   - 有 → 继续下一步
   - 没有 → 判定为「未按 SKILL.md 执行」，重新读取并执行该子工具
   ⛔ 全自动模式也不能跳过此校验。跳过检查点 ≠ 跳过读取验证。
   
   **代码级验证**（不靠 AI 自律）：子工具输出后，用 exec 调 `scripts/verify_proof.py` 检查：
   ```
   echo "<子工具输出>" | python3 scripts/verify_proof.py
   返回码 0 → 继续
   返回码 1 → 强制重新读取并执行
   ```
3. 输出进度回执（包含全局进度列表）：
   ✅ {子工具名} 完成 | ⏱ {耗时}
   {1-2 行关键数据}
   
   全局进度：
   sentry-lint（静态检查）      ✅ 完成
   sentry-trigger（触发率）    ✅ 完成
   sentry-cases（用例设计）     🔄 执行中
   sentry-executor（用例执行）  ⏳ 待执行
   sentry-grader（断言评审）    ⏳ 待执行
   comparator（盲测对比）       ⏳ 待执行
   analyzer（根因分析）         ⏳ 待执行
   sentry-report（报告生成）    ⏳ 待执行
   
   格式：英文工具名 + 中文说明 + 状态。跳过的步骤标注「— 跳过」。
   
   注意：用子工具名（如 sentry-lint）作为步骤标题，不用 Step N
4. 【检查点】输出三段式回执：
   ① 结果小结：刚才发现了什么，有什么问题，是否影响继续
   ② 下一步预告：接下来要做什么，大约要多久
   ③ 用户选项：继续 / 跳过 / 中止 / 重跑 / 切换模式
   （60s 无回复 → 自动继续）
5. 更新 session.json 的 last_step
```

**强制规则**：每步必须停下来输出进度 | 子工具通过 session.json 获取参数 | 实现细节在各自 SKILL.md 里

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

### 异常话术 + 单工具

**异常**：SKILL.md找不到→❌列路径 | evals为空→⚠️先跑cases | 超时→⚠️降级直跑 | MCP不可用→⚠️问继续/中止 | session.json缺失→❌重新Step1
**单工具**：「lint xxx」→sentry-lint | 「跑用例」→sentry-executor | 「出报告」→sentry-report | 「评审」→sentry-grader


---

### 安全约束

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

*v5.5 · 极简调度器 · 2026-04-24*
