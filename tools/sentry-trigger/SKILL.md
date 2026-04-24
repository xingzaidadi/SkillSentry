---
name: sentry-trigger
description: >
  对 AI Skill 的触发率做 AI 模拟评估，判断 description 写得好不好、能不能被正确触发。
  触发场景：说"测试触发率"、"检查这个skill会不会被误触发"、"trigger rate"、
  "description写得好不好"、"这个skill触发准不准"、"会不会该触发时没触发"。
  不触发场景：要运行功能测试用例、要做完整测评、要看SKILL.md结构。
---

# sentry-trigger · Skill 触发率 AI 模拟评估

对目标 Skill 的 `description` 字段做 AI 模拟触发测试，输出 TP/TN 估算和置信度。约 2 分钟完成。

**一句话价值**：不需要真实用户数据，AI 自模拟 10 条对话场景，快速诊断 description 是否精准。

---

## 输入

优先级：
1. 用户提供了具体路径 → 读取该路径的 SKILL.md
2. 用户只说了名字 → 查找 `~/.claude/skills/<名字>/SKILL.md`
3. 用户说「检查这个」→ 当前工作目录下的 SKILL.md

---

## 执行流程

### Step 1：提取 description 语义

读取 SKILL.md 中 frontmatter 的 `description` 字段，识别：
- **触发意图**：什么用户行为/语言应该激活这个 Skill
- **不触发意图**：什么场景明确排除
- **边界场景**：描述中语义模糊的部分

### Step 2：生成 10 条测试 prompt

按以下分布生成，不重复：

| 类型 | 数量 | 要求 |
|------|------|------|
| TP（应触发） | 5 条 | 覆盖不同表达方式，包含核心意图 |
| TN（不应触发） | 3 条 | 相关但不符合触发条件的场景 |
| 边界（uncertain） | 2 条 | 在触发/不触发边界上模糊的场景 |

生成标准：
- TP 应覆盖 description 中列举的多种触发词（不只用一种表达）
- TN 应是「容易混淆的相近场景」，不是「显然无关」的场景
- 每条 prompt 写成用户真实可能说的自然语言

### Step 3：AI 自评每条 prompt

对每条 prompt，以一个「不知道有哪些 Skill 可用」的 Claude 模型的视角判断：

```
给定这条 description：
[description 内容]

用户说：「[prompt]」

问题：这个 description 是否会让模型选择激活此 Skill？
打分：0（绝对不触发）/ 0.5（不确定）/ 1（大概率触发）
理由：[1-2 句]
```

### Step 4：汇总统计

```
TP 触发率 = TP 中打分 ≥ 0.7 的条数 / 5
TN 不触发率 = TN 中打分 ≤ 0.3 的条数 / 3
边界：标注每条的实际判断

整体置信度判断：
- high：所有判断都很确定（无 0.5 分）
- medium：1-2 条判断不确定
- low：≥3 条判断不确定
```

### Step 5：输出 trigger_eval.json

保存到 `inputs/<Skill名称>/trigger_eval.json`（inputs 目录不存在则创建）：

```json
{
  "evaluated_at": "<ISO时间>",
  "skill_name": "<名称>",
  "tp_rate": 0.80,
  "tn_rate": 1.00,
  "uncertain_count": 1,
  "confidence": "medium",
  "prompts": [
    {
      "id": 1,
      "type": "TP",
      "prompt": "帮我报销这张发票",
      "score": 1.0,
      "reason": "包含核心触发词「报销」，description 有明确覆盖"
    }
  ],
  "recommendation": "TP 触发率 80%，达标（≥70%）。建议优化：[具体建议]"
}
```

---

## 输出格式（控制台）

```
## sentry-trigger 报告：<Skill名称>

TP 触发率：[X]%（[N]/5 条应触发场景正确触发）
TN 不触发率：[X]%（[N]/3 条不应触发场景正确排除）
边界情况：[N] 条 uncertain
整体置信度：[high/medium/low]

详细结果：
[每条 prompt 的判断，标注 TP/TN/边界 + 得分 + 理由]

⚠️ 免责声明：此为 AI 模拟估算，精确数据需真实用户对话统计。

结论：[达标/需优化] + [具体改进建议]
```

---

## 发布建议阈值（参考）

| TP 触发率 | 建议 |
|----------|------|
| ≥ 80% | 正常上线 |
| 70-80% | 优化 description 后重测 |
| < 70% | 暂缓发布，description 需重写 |

有 TN 误触发（TN 中 score ≥ 0.7）时，额外标注 ⚠️。

---

## 准则

- 不执行任何 MCP 工具或 Bash
- 10 条 prompt 必须全部生成和评估，不得减少
- score = 0.5 时不算 TP 或 TN，计入 uncertain
- 置信度 low 时在报告中标注「建议精确测量」

---

## 读取证明（主编排器校验用）

输出的最后一行必须包含以下格式的校验标记：

```
[sentry-proof] skill=<本工具名> steps=<本次执行的步骤数> ts=<ISO时间>
```

主编排器通过检查此标记确认子工具确实读取并执行了 SKILL.md，而非凭记忆发挥。
缺少此标记 → 主编排器判定为「未按 SKILL.md 执行」，要求重跑。
