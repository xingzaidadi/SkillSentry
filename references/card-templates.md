# 飞书卡片格式参考（OpenClaw 主会话专用）

> 本文件是 SkillSentry 主会话发送飞书卡片时的格式参考。
> 被测 Skill 的 SKILL.md 不需要读取本文件。

## 规则

1. 所有面向用户的步骤输出，必须通过 `message` 工具发送 interactive 类型卡片
2. 每次调用 `message` 工具时，**必须**传 `msg_type="interactive"`
3. `message` 参数的值**必须**是以下模板之一（直接复制，替换 `{变量}`）
4. 禁止用 `message(action=send, message="纯文本")` 这种无 msg_type 的调用
5. 禁止直接回复文本代替 message 工具调用

## 模板 1：Step 完成通知卡片

```python
import json
card = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "header": {
        "title": {"tag": "plain_text", "content": f"🦞 SkillSentry · Step {step_name} 完成"},
        "template": "green"  # blue=进行中 / green=成功 / red=失败 / orange=警告
    },
    "body": {
        "elements": [{
            "tag": "markdown",
            "content": markdown_content  # 你的步骤结果摘要
        }]
    }
}
message(action=send, msg_type="interactive", message=json.dumps(card, ensure_ascii=False))
```

## 模板 2：用例设计展示卡片（sentry-cases 输出用）

```python
import json
card = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "header": {
        "title": {"tag": "plain_text", "content": "📋 用例设计完成 · smoke 模式"},
        "template": "blue"
    },
    "body": {
        "elements": [{
            "tag": "markdown",
            "content": (
                f"共 **{total}** 个用例，**{assertions}** 条断言\n\n"
                "| # | 类型 | 用例名 | 断言数 |\n"
                "|---|------|-------|--------|\n"
                + rows  # 每行: | E001 | happy_path | xxx | 3 |
            )
        }]
    }
}
message(action=send, msg_type="interactive", message=json.dumps(card, ensure_ascii=False))
```

## 模板 3：Grader 结果卡片

```python
import json
card = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "header": {
        "title": {"tag": "plain_text", "content": f"📊 Grader 评审 · {skill_name}"},
        "template": "green" if pass_rate >= 0.7 else "red"
    },
    "body": {
        "elements": [{
            "tag": "markdown",
            "content": (
                f"**通过率**: {pass_rate:.0%} ({passed}/{total})\n\n"
                "| Eval | 用例 | 结果 | 详情 |\n"
                "|------|------|------|------|\n"
                + rows
            )
        }]
    }
}
message(action=send, msg_type="interactive", message=json.dumps(card, ensure_ascii=False))
```

## 模板 4：进度通知卡片（executor 等待中）

```python
import json
card = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "header": {
        "title": {"tag": "plain_text", "content": f"🦞 SkillSentry · Step {step_name} 执行中"},
        "template": "blue"
    },
    "body": {
        "elements": [{
            "tag": "markdown",
            "content": progress_content  # 进度表格等
        }]
    }
}
message(action=send, msg_type="interactive", message=json.dumps(card, ensure_ascii=False))
```
