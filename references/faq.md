# faq.md — 常见问题处理

> SkillSentry 运行过程中遇到异常情况时按需读取，无需全量加载。

## 目录

**运行配置类**
- [session 目录命名冲突](#session-目录命名冲突)
- [被测 Skill 需要物理素材但扫描到 0 个文件](#被测-skill-需要物理素材但扫描到-0-个文件)
- [cases.cache.json 什么时候应该手动清除](#casescachejson-什么时候应该手动清除)
- [被测 Skill 依赖另一个 Skill，怎么处理](#被测-skill-依赖另一个-skill怎么处理)

**结果解读类**
- [被测 Skill 是纯文本生成型，Grader 怎么判断](#被测-skill-是纯文本生成型grader-怎么判断)
- [触发率 AI 模拟置信度 low，怎么办](#触发率-ai-模拟置信度-low怎么办)
- [timing_with.json / timing_without.json 数据缺失怎么办](#timing_withjson--timing_withoutjson-数据缺失怎么办)
- [效率诊断显示 Token 消耗过高，但通过率达标，还能发布吗](#效率诊断显示-token-消耗过高但通过率达标还能发布吗)
- [两次 quick 运行结果差距超过 15%，该怎么办](#两次-quick-运行结果差距超过-15该怎么办)
- [Grader 评审结果和预期差异很大，怎么排查](#grader-评审结果和预期差异很大怎么排查)

**安全合规类**
- [被测 Skill 涉及不可逆操作，但没有用户确认步骤](#被测-skill-涉及不可逆操作但没有用户确认步骤)
- [单元测试和 E2E 有什么区别](#单元测试和-e2e-有什么区别)

**工程维护类**
- [修改 sentry-* 工具时应该改哪个文件](#修改-sentry--工具时应该改哪个文件)

**OpenClaw / 飞书类**
- [OpenClaw/飞书场景：用户长时间没有回复确认怎么办](#openclaw飞书场景用户长时间没有回复确认怎么办)
- [OpenClaw/飞书场景：报告 HTML 文件怎么让用户看到](#openclaw飞书场景报告-html-文件怎么让用户看到)
- [OpenClaw/飞书场景：如何判断是否在 OpenClaw 环境中运行](#openclaw飞书场景如何判断是否在-openclaw-环境中运行)

**部署 / 版本升级类**
- [部署新版 SkillSentry 后，交互卡片不出现](#部署新版-skillsentry-后交互卡片不出现agent-用纯文本列表代替)
- [手动覆盖 skill 文件后，agent 仍使用旧版 skill description](#手动覆盖-skill-文件后agent-仍使用旧版-skill-description)
- [测评完 Skill A 后测评 Skill B，agent 沿用 Skill A 的执行模式](#测评完-skill-a-后测评-skill-bagent-沿用-skill-a-的执行模式)
- [旧记忆清理 vs 保留的平衡](#旧记忆清理-vs-保留的平衡)
- [纯 prompt 层方案的天花板](#纯-prompt-层方案的天花板agent-理论上仍可忽略-skillmd)

---

**session 目录命名冲突**
→ 检查 `sessions/<被测Skill名称>/` 下当天已有哪些目录，取最大序号 +1。
例：已有 `_001` 和 `_002` → 新建 `2026-03-30_003`。

---

**用户问「单元测试和 E2E 有什么区别」**
→ 单元测试隔离验证单条规则；E2E 模拟真实旅程，验证多规则组合时的状态维护。

---

**被测 Skill 需要物理素材但扫描到 0 个文件**
→ 提示用户将文件放入 `skill-eval-测评/inputs/<被测Skill名称>/`，并给出具体路径。

---

**被测 Skill 是纯文本生成型，Grader 怎么判断？**
→ 使用 `agents/grader.md` 中的「纯文本评审规范」，重点验证输出内容是否覆盖 SKILL.md 核心要素、格式是否合规、禁止行为是否出现。evidence 改为引用 `response.md` 原文段落。

---

**触发率 AI 模拟置信度 low，怎么办？**
→ 通常是 description 写得不够清晰。检查：① 是否明确说了「何时触发」；② 是否包含典型场景举例；③ 是否区分了应触发和不应触发的情况。修改后重新运行阶段一触发率测评。

---

**timing_with.json / timing_without.json 数据缺失怎么办？**
→ timing 数据需在 subagent 执行完成时立即采集。缺失时报告中对应字段填 `N/A`，不影响通过率计算。建议下次测评确保 subagent 结束时写入 `timing_with.json` / `timing_without.json`。

---

**被测 Skill 涉及不可逆操作，但没有用户确认步骤**
→ 标记 HiL-1 为 ⚠️ 警告，在改进建议中注明缺少 Human-in-the-Loop 确认节点。不升级为 ❌ 严重（除非 S 级且已发生过误触发事故）。

---

**效率诊断显示 Token 消耗过高，但通过率达标，还能发布吗？**
→ 可以发布（效率维度是 P2，不阻止发布），但报告必须输出效率警告，改进建议里标注「建议下一迭代优化 Token 效率」。

---

**OpenClaw/飞书场景：用户长时间没有回复确认怎么办？**
→ 见 `references/feishu-templates.md` 超时提醒章节。超过 10 分钟自动按 quick 模式默认参数执行。

---

**OpenClaw/飞书场景：报告 HTML 文件怎么让用户看到？**
→ 优先发送报告路径。如有内网 HTTP 服务，附可访问 URL。否则在飞书直接发送摘要卡片（见 feishu-templates.md 【5/5】），摘要已覆盖 90% 发布决策所需信息。

---

**OpenClaw/飞书场景：如何判断是否在 OpenClaw 环境中运行？**
→ 触发消息包含飞书消息格式元数据（sender_id、chat_id），或用户明确说「我在飞书里」，则判定为 openclaw 模式。无法判断时默认 opencode 模式，不影响核心测评逻辑。

---

**修改 sentry-* 工具时应该改哪个文件？**
→ 权威源在 `skill-eval-测评/tools/sentry-*/SKILL.md`，`~/.claude/skills/sentry-*/SKILL.md` 是部署副本。
  正确流程：先改 `tools/sentry-*/SKILL.md`，再运行 `install.sh`（Linux/Mac）或 `install.ps1`（Windows）同步部署。
  直接改部署副本会在下次 install 时被覆盖回旧版本。

---

**Grader 评审结果和预期差异很大，怎么排查？**
→ 先确认 `skill_type` 传入正确（mcp_based / text_generation / code_execution），不同类型评审标准差异大。
  其次检查 transcript 的 `[tool_calls]` 区块是否有原始 JSON 返回值，若只有 AI 自然语言描述会导致大量 `fabrication_risk: high`，评审结果偏严。
  最后检查断言的 `precision` 字段——semantic 断言本身有主观空间，差异大属正常。

---

**两次 quick 运行结果差距超过 15%，该怎么办？**
→ 这是模型随机性导致的不稳定信号。sentry-report 会自动标红「⚠️ 结果不稳定」。
  处理方式：将模式升级为 standard（3 次取均值），差距通常会收窄到 <10%。
  若 standard 仍不稳定，说明 Skill 本身存在歧义规则，需排查 SKILL.md 中逻辑分支不清晰的部分。

---

**cases.cache.json 什么时候应该手动清除？**
→ 以下情况建议手动删除 `inputs/<Skill名>/cases.cache.json` 强制重新设计用例：
  1. SKILL.md 主流程结构性重写（而非只改规则细节）
  2. 发现缓存用例覆盖了已废弃的业务路径
  3. 升级测评模式（如从 quick 升到 full）且想获得更多 full 级用例

---

**被测 Skill 依赖另一个 Skill，怎么处理？**
→ SkillSentry 测的是单个 Skill 的执行质量，不支持多 Skill 联动测评。
  处理方式：先分别测评各 Skill，确认各自达标后，再设计 E2E 用例测联动场景。
  E2E 用例的 prompt 应模拟真实用户对话（不提 Skill 名），让系统自然触发调用链。

---

**部署新版 SkillSentry 后，交互卡片不出现（agent 用纯文本列表代替）**
→ 三层根因叠加：
  1. **memory 覆写**：旧版 SkillSentry 的 memory 记录包含「用文本列表列 skill」的行为模式，agent 直接照搬，跳过读 SKILL.md
  2. **manifest 缓存**：手动覆盖文件时 gateway 未重启，`skill_manifest.json` 中的 contentHash 仍是旧的，agent 看到的 description 是旧版
  3. **嵌套指令**：SKILL.md 内部的 Step 0 也依赖 agent 先读 SKILL.md 才能生效
  解决方案：
  - SKILL.md 顶部加「行为优先级」规则（SKILL.md > memory）
  - description 中加「旧记忆警告」（始终可见，不需要读 SKILL.md）
  - 部署后运行 `install.sh --restart` 更新 manifest
  详见 `TROUBLESHOOTING.md`

---

**手动覆盖 skill 文件后，agent 仍使用旧版 skill description**
→ `skill_manifest.json` 缓存了每个 skill 的 `contentHash`。gateway 运行时手动覆盖文件，gateway 不会自动重新扫描。
  解决方案：拷完文件后重启 gateway
  ```bash
  openclaw gateway restart
  ```
  或使用 `install.sh --restart` 自动检测并重启。

---

**测评完 Skill A 后测评 Skill B，agent 沿用 Skill A 的执行模式**
→ memory 中 Skill A 的执行记录影响了 Skill B 的执行。
  解决方案：
  - 行为优先级规则：每次触发都是独立执行
  - session.json 自动重置：检测到 skill 变更时清空 session 状态
  - description 明确声明：「每次触发都是独立执行，不因之前测评过其他 Skill 就跳过读 SKILL.md」

---

**旧记忆清理 vs 保留的平衡**
→ memory 中的 session 历史、执行结果、用例数据都是有价值的资产，不应删除。
  正确做法：不删除任何 memory 文件，通过「SKILL.md > memory」的优先级规则解决行为冲突。
  memory 保留作为历史记录，但不影响当前执行行为。

---

**纯 prompt 层方案的天花板：agent 理论上仍可忽略 SKILL.md**
→ LLM 的 compliance 是概率性的，不是确定性的。当前方案把概率拉到最高，但不是 100%。
  防线层级：
  - L0: description 旧记忆警告（始终可见，不需要读 SKILL.md）→ 最有效
  - L1: description 强制执行规则（始终可见）
  - L2: SKILL.md 行为优先级规则（需要读文件）
  - L3: Step 0.1 环境对齐检查（需要读文件）
  唯一 100% 方案：改 OpenClaw 源码（skill 加载时代码层面强制注入规则）。

---

*Last Updated: 2026-04-29*
