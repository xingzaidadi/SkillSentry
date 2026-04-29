# SkillSentry 部署检查清单

将 SkillSentry 部署到新的 OpenClaw 实例时，按此清单操作。

---

## 一键安装（推荐）

```bash
# 复制整个目录到目标机器
scp -r skill-eval-测评/ target:~/.openclaw/skills/

# 在目标机器上执行安装检查
ssh target 'bash ~/.openclaw/skills/skill-eval-测评/install.sh'
```

`install.sh` 会自动完成：
1. 验证文件完整性
2. 检查版本号
3. 验证行为优先级指令（SKILL.md > memory）
4. 验证交互卡片指令
5. 检测 memory 中的旧版行为模式（仅供参考，不删除）

## 手动部署

如果不想用 install.sh：

```bash
cp -r skill-eval-测评/ ~/.openclaw/skills/
```

## 验证安装

部署后，发送以下消息测试：

1. `验证 SkillSentry` → 应列出所有子工具状态
2. `测评 xxx`（任选一个 skill）→ 应弹出飞书交互卡片（下拉选择），而非纯文本列表

如果仍然出现纯文本列表：
1. 检查 SKILL.md 是否包含 `⛔ 版本锁定 & 行为优先级` 段落
2. 检查 `feishu_ask_user_question` 工具是否可用

## 行为优先级规则

本 Skill 的核心原则：**SKILL.md > memory**

- memory 文件保留不动（session 历史、执行结果都是有价值的资产）
- 当 memory 中的旧行为模式与 SKILL.md 冲突时，以 SKILL.md 为准
- 不需要清理旧记忆，只需要 SKILL.md 的指令足够明确

## 版本同步

更新 SkillSentry 后，记得同步到所有实例。每个实例的 `SKILL.md` 中的版本号应一致。
