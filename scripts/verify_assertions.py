#!/usr/bin/env python3
"""
verify_assertions.py — SkillSentry 量化断言脚本验证工具

用途：对 exact_match 类断言做确定性验证，结果 0/1，
      完全绕过 Grader AI 的主观判断，消除「AI 评审 AI」的可信度问题。

依据：
  - OpenCode Tools 文档 (https://opencode.ai/docs/tools/)：bash 工具支持执行脚本
  - MCP 官方架构文档 (modelcontextprotocol.io)：tool_calls 原始 JSON-RPC 格式说明

用法：
  python3 verify_assertions.py \
    --transcript with_skill/outputs/transcript.md \
    --response   with_skill/outputs/response.md \
    --assertions assertions.json \
    --output     grading_script.json

assertions.json 格式（支持的类型）：
[
  {"id":"A1","type":"tool_call_count",      "tool":"saveExpenseDoc_test","expected_count":1},
  {"id":"A2","type":"args_field",           "tool":"saveExpenseDoc_test","field":"docStatus","expected":"10"},
  {"id":"A3","type":"response_not_contains","pattern":"{fdId}"},
  {"id":"A4","type":"response_word_count",  "max":200},
  {"id":"A5","type":"response_contains",    "keyword":"报销金额"},
  {"id":"A6","type":"response_has_heading", "level":2}
]
"""

import sys
import json
import re
import argparse
import datetime
from pathlib import Path


def load_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def extract_tool_calls(transcript: str) -> list:
    """
    从 transcript 的 [tool_calls] 区块提取工具调用记录。
    区分真实 JSON 返回值和 AI 自然语言描述的返回值。
    """
    # 提取 [tool_calls] 区块内容
    tool_call_section = re.search(
        r'\[tool_calls\](.*?)(\[agent_notes\]|\Z)', transcript, re.DOTALL
    )
    section = tool_call_section.group(1) if tool_call_section else transcript

    # 匹配每个工具调用块
    pattern = re.compile(
        r'Tool:\s*(\S+)\s*\n'
        r'Args:\s*(\{.*?\})\s*\n'
        r'Return:\s*(.*?)\s*\n'
        r'Status:\s*(\w+)',
        re.DOTALL
    )

    calls = []
    for m in pattern.finditer(section):
        tool_name = m.group(1).strip()
        args_raw  = m.group(2).strip()
        return_raw = m.group(3).strip()
        status    = m.group(4).strip()

        call = {"tool": tool_name, "status": status}

        # 尝试解析 Args JSON
        try:
            call["args"] = json.loads(args_raw)
        except json.JSONDecodeError:
            call["args_raw"] = args_raw
            call["fabrication_risk"] = "high"

        # 尝试解析 Return JSON
        try:
            call["return"] = json.loads(return_raw)
        except json.JSONDecodeError:
            # Return 值不是合法 JSON，说明是 AI 自然语言描述
            call["return_raw"] = return_raw
            call["fabrication_risk"] = "high"
            call["fabrication_note"] = (
                "Return 值非合法 JSON，疑似 AI 自然语言描述而非系统原始返回。"
                "依据：MCP JSON-RPC 2.0 协议要求 tools/call 响应必须是结构化 JSON。"
            )

        calls.append(call)

    return calls


def verify(assertion: dict, transcript: str, response: str, tool_calls: list) -> dict:
    """对单条断言执行脚本验证，返回确定性结果。"""
    a_type = assertion.get("type", "")
    result = {
        "id": assertion["id"],
        "type": a_type,
        "method": "script",  # 标注为脚本验证，与 method:grader 明确区分
        "passed": False,
        "evidence": "",
        "fabrication_risk": "low"
    }

    # ── 工具调用次数验证 ───────────────────────────────────────────────
    if a_type == "tool_call_count":
        tool = assertion["tool"]
        expected = assertion["expected_count"]
        # 只在 [tool_calls] 区块统计，避免 [agent_notes] 中的提及干扰
        tool_call_section = re.search(
            r'\[tool_calls\](.*?)(\[agent_notes\]|\Z)', transcript, re.DOTALL
        )
        section_text = tool_call_section.group(1) if tool_call_section else transcript
        actual = len(re.findall(rf'Tool:\s*{re.escape(tool)}', section_text))
        result["passed"] = (actual == expected)
        result["evidence"] = (
            f"[tool_calls] 区块中 Tool: {tool} 出现 {actual} 次，期望 {expected} 次"
        )

    # ── 工具调用入参字段验证 ──────────────────────────────────────────
    elif a_type == "args_field":
        tool = assertion["tool"]
        field = assertion["field"]
        expected_val = str(assertion["expected"])
        found = False
        for call in tool_calls:
            if call.get("tool") != tool:
                continue
            if "fabrication_risk" in call:
                result["passed"] = False
                result["fabrication_risk"] = "high"
                result["evidence"] = (
                    f"{tool} 的 Args/Return 为 AI 自然语言描述，非系统原始 JSON，"
                    f"字段 {field} 无法验证。"
                )
                found = True
                break
            if "args" in call:
                actual_val = str(call["args"].get(field, "__missing__"))
                result["passed"] = (actual_val == expected_val)
                result["evidence"] = (
                    f"transcript [tool_calls] {tool} Args.{field} = {actual_val!r}，"
                    f"期望 {expected_val!r}"
                )
                found = True
                break
        if not found:
            result["passed"] = False
            result["evidence"] = f"transcript [tool_calls] 中未找到 {tool} 的调用记录"

    # ── response 不包含指定字符串 ─────────────────────────────────────
    elif a_type == "response_not_contains":
        pattern = assertion["pattern"]
        found_in_response = pattern in response
        result["passed"] = not found_in_response
        if not found_in_response:
            result["evidence"] = f"全文检索 response.md，未发现 {pattern!r}"
        else:
            pos = response.find(pattern)
            result["evidence"] = (
                f"全文检索 response.md，在第 {pos} 字符处发现 {pattern!r}"
            )

    # ── response 包含指定关键词 ───────────────────────────────────────
    elif a_type == "response_contains":
        keyword = assertion["keyword"]
        found_in_response = keyword in response
        result["passed"] = found_in_response
        result["evidence"] = (
            f"全文检索 response.md，{'找到' if found_in_response else '未找到'} {keyword!r}"
        )

    # ── response 字数限制 ────────────────────────────────────────────
    elif a_type == "response_word_count":
        max_count = assertion["max"]
        chinese = len(re.findall(r'[\u4e00-\u9fff]', response))
        english = len(re.findall(r'[a-zA-Z]+', response))
        total = chinese + english
        result["passed"] = (total <= max_count)
        result["evidence"] = (
            f"字数统计：中文字符 {chinese} + 英文单词 {english} = {total}，上限 {max_count}"
        )

    # ── response 标题结构检测 ─────────────────────────────────────────
    elif a_type == "response_has_heading":
        level = assertion.get("level", 2)
        prefix = "#" * level + " "
        found_heading = bool(re.search(
            r'^' + re.escape(prefix), response, re.MULTILINE
        ))
        result["passed"] = found_heading
        result["evidence"] = (
            f"{'找到' if found_heading else '未找到'} H{level} 标题（{prefix}...）"
        )

    else:
        result["evidence"] = f"未知断言类型 {a_type!r}，跳过验证"

    return result


def main():
    parser = argparse.ArgumentParser(
        description="SkillSentry 量化断言脚本验证 - 结果 0/1，不依赖 AI 判断"
    )
    parser.add_argument("--transcript", required=True, help="transcript.md 路径")
    parser.add_argument("--response",   required=True, help="response.md 路径")
    parser.add_argument("--assertions", required=True, help="断言定义 JSON 文件路径")
    parser.add_argument("--output",     required=True, help="输出 grading_script.json 路径")
    args = parser.parse_args()

    transcript = load_file(args.transcript)
    response   = load_file(args.response)

    if not transcript:
        print(f"ERROR: transcript 文件不存在或为空: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    assertions_raw = json.loads(Path(args.assertions).read_text(encoding="utf-8"))
    tool_calls     = extract_tool_calls(transcript)

    results = []
    for assertion in assertions_raw:
        results.append(verify(assertion, transcript, response, tool_calls))

    passed     = sum(1 for r in results if r["passed"])
    total      = len(results)
    high_risk  = [r for r in results if r.get("fabrication_risk") == "high"]

    output = {
        "verified_at": datetime.datetime.now().isoformat(),
        "method": "script",
        "transcript_path": args.transcript,
        "response_path":   args.response,
        "tool_calls_extracted": len(tool_calls),
        "tool_calls_high_risk": len([c for c in tool_calls if c.get("fabrication_risk") == "high"]),
        "assertions": results,
        "summary": {
            "passed": passed,
            "total":  total,
            "pass_rate": round(passed / total, 2) if total else 0,
            "high_fabrication_risk_assertions": len(high_risk),
            "note": (
                "method=script 为确定性验证，结果 0/1，不依赖 AI 主观判断。"
                "high_fabrication_risk 表示 transcript 中存在非 JSON 格式的 Return 值，"
                "疑似 AI 自然语言描述而非系统原始返回。"
            )
        }
    }

    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"验证完成：{passed}/{total} 通过")
    if high_risk:
        print(f"⚠️  {len(high_risk)} 条断言的 evidence 存在编造风险（Return 值非原始 JSON）")
    print(f"结果已写入：{args.output}")


if __name__ == "__main__":
    main()
