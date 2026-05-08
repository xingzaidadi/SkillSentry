# 步骤输出格式参考

## 规则

1. 所有面向用户的步骤输出，必须通过 `message` 工具发送
2. 使用 `msg_type="text"`，内容用 markdown 格式化
3. 禁止直接回复文本代替 message 工具调用

## 模板

```python
message(
    action=send,
    msg_type="text",
    message=(
        f"✅ Step {step_name} 完成\n"
        f"• 被测 Skill：{name}\n"
        f"• 类型：{type}\n"
        f"• 结果：{result}"
    )
)
```

## 多行表格

```python
message(
    action=send,
    msg_type="text",
    message=(
        "| Eval | 用例 | 结果 |\n"
        "|------|------|------|\n"
        "| E001 | xxx | ✅ |\n"
        "| E002 | xxx | ✅ |"
    )
)
```
