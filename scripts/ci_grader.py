#!/usr/bin/env python3
"""
SkillSentry CI Grader — 用 Anthropic SDK 直调 LLM 做断言评审

不依赖 claude CLI，纯 API 调用，适合 CI 环境。
产出：eval-N/with_skill/outputs/grading.json
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import anthropic
except ImportError:
    anthropic = None


def call_llm(prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 4000) -> str | None:
    """通用 LLM 调用（Anthropic SDK），供 sentry_ci.py 的 check/cases 步骤复用"""
    if anthropic is None:
        print("  ❌ anthropic SDK 未安装，请 pip install anthropic", file=sys.stderr)
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ❌ ANTHROPIC_API_KEY 环境变量未设置", file=sys.stderr)
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        print(f"  ❌ LLM 调用失败: {e}", file=sys.stderr)
        return None


def build_grading_prompt(eval_config: dict, transcript: str, response_text: str) -> str:
    """构造单个 eval 的评审 prompt"""
    assertions = eval_config.get("assertions", [])
    name = eval_config.get("name", "unknown")

    assertions_text = json.dumps(assertions, ensure_ascii=False, indent=2)

    return f"""你是 SkillSentry 的断言评审模块。请逐条评审以下断言是否通过。

## 被测用例
用例名：{name}

## Skill 响应内容（response.md）
```
{response_text}
```

## 完整交互记录（transcript.md）
```
{transcript}
```

## 待评审断言
```json
{assertions_text}
```

## 评审规则
- exact_match：response 中必须包含 expected 的精确文本（允许前后有空白）
- semantic：response 的语义必须符合 expected 描述的含义（不要求精确措辞）
- existence：response 中必须存在 expected 描述的内容或元素

## 输出格式
请以 JSON 格式返回评审结果（直接返回 JSON，不要 markdown 包裹）：
{{
  "assertions": [
    {{
      "name": "断言名",
      "type": "exact_match|semantic|existence",
      "expected": "断言期望",
      "pass": true,
      "evidence": "引用 response 中的具体文本作为证据（50字以内）"
    }}
  ],
  "summary": {{
    "pass": 通过数,
    "fail": 失败数,
    "total": 总数
  }}
}}"""


def grade_single_eval(
    eval_config: dict,
    session_dir: Path,
    model: str = "claude-sonnet-4-6",
    verbose: bool = False,
) -> dict | None:
    """评审单个 eval，返回 grading 数据"""
    eval_id = eval_config.get("id", "eval-1")
    name = eval_config.get("name", "unknown")
    assertions = eval_config.get("assertions", [])

    if not assertions:
        if verbose:
            print(f"  ⏭️ {eval_id} ({name}): 无断言，跳过", file=sys.stderr)
        return None

    # 读取 response.md 和 transcript.md
    output_dir = session_dir / eval_id / "with_skill" / "outputs"
    response_file = output_dir / "response.md"
    transcript_file = output_dir / "transcript.md"

    if not response_file.exists():
        if verbose:
            print(f"  ⏭️ {eval_id}: response.md 不存在，跳过", file=sys.stderr)
        return None

    response_text = response_file.read_text(encoding="utf-8")
    transcript = transcript_file.read_text(encoding="utf-8") if transcript_file.exists() else response_text

    # 检查执行是否失败
    if response_text.startswith("[EXECUTION FAILED]") or response_text.startswith("[TIMEOUT"):
        if verbose:
            print(f"  ⏭️ {eval_id}: 执行失败，标记全部断言为 fail", file=sys.stderr)
        return {
            "eval_id": eval_id,
            "runs": {
                "run-1": {
                    "pass": False,
                    "assertions": [
                        {
                            "id": a.get("name", f"A{i+1}"),
                            "type": a.get("type", "semantic"),
                            "expect": a.get("expected", ""),
                            "pass": False,
                            "evidence": "执行失败，无有效响应",
                        }
                        for i, a in enumerate(assertions)
                    ],
                }
            },
            "summary": {
                "pass": 0,
                "fail": len(assertions),
                "total": len(assertions),
                "precision_breakdown": {
                    "exact_match": {"pass": 0, "total": sum(1 for a in assertions if a.get("type") == "exact_match")},
                    "semantic": {"pass": 0, "total": sum(1 for a in assertions if a.get("type") == "semantic")},
                },
                "authoritative_pass_rate": 0.0,
            },
        }

    # 调用 LLM 评审
    prompt = build_grading_prompt(eval_config, transcript, response_text)
    result = call_llm(prompt, model=model, max_tokens=2000)

    if not result:
        if verbose:
            print(f"  ❌ {eval_id}: LLM 评审调用失败", file=sys.stderr)
        return None

    # 解析 JSON 结果
    try:
        json_match = re.search(r"\{[\s\S]*\}", result)
        if not json_match:
            if verbose:
                print(f"  ❌ {eval_id}: 评审结果无 JSON", file=sys.stderr)
            return None

        grading_data = json.loads(json_match.group())
        graded_assertions = grading_data.get("assertions", [])
        summary = grading_data.get("summary", {})

        # 计算 precision_breakdown
        exact_pass = sum(1 for a in graded_assertions if a.get("type") == "exact_match" and a.get("pass"))
        exact_total = sum(1 for a in graded_assertions if a.get("type") == "exact_match")
        sem_pass = sum(1 for a in graded_assertions if a.get("type") == "semantic" and a.get("pass"))
        sem_total = sum(1 for a in graded_assertions if a.get("type") == "semantic")

        total_pass = summary.get("pass", sum(1 for a in graded_assertions if a.get("pass")))
        total_fail = summary.get("fail", sum(1 for a in graded_assertions if not a.get("pass")))
        total_count = summary.get("total", len(graded_assertions))

        # 构造标准格式 grading.json
        grading = {
            "eval_id": eval_id,
            "runs": {
                "run-1": {
                    "pass": total_fail == 0,
                    "assertions": [
                        {
                            "id": a.get("name", f"A{i+1}"),
                            "type": a.get("type", "semantic"),
                            "expect": a.get("expected", ""),
                            "pass": a.get("pass", False),
                            "evidence": a.get("evidence", ""),
                        }
                        for i, a in enumerate(graded_assertions)
                    ],
                }
            },
            "summary": {
                "pass": total_pass,
                "fail": total_fail,
                "total": total_count,
                "precision_breakdown": {
                    "exact_match": {"pass": exact_pass, "total": exact_total},
                    "semantic": {"pass": sem_pass, "total": sem_total},
                },
                "authoritative_pass_rate": exact_pass / exact_total if exact_total > 0 else (total_pass / total_count if total_count > 0 else 0.0),
            },
        }

        if verbose:
            print(f"  ✅ {eval_id} ({name}): {total_pass}/{total_count} 断言通过", file=sys.stderr)

        return grading

    except json.JSONDecodeError as e:
        if verbose:
            print(f"  ❌ {eval_id}: JSON 解析失败: {e}", file=sys.stderr)
        return None


def grade_all_evals(
    evals_file: Path,
    session_dir: Path,
    model: str = "claude-sonnet-4-6",
    verbose: bool = False,
) -> bool:
    """评审所有 evals，写入 grading.json，返回是否有至少 1 个成功"""
    with open(evals_file, encoding="utf-8") as f:
        evals = json.load(f)

    if not evals:
        print("  ⚠️ evals.json 为空", file=sys.stderr)
        return False

    print(f"  🔍 评审 {len(evals)} 个用例 (model={model})", file=sys.stderr)

    success_count = 0

    for eval_config in evals:
        eval_id = eval_config.get("id", "eval-unknown")
        grading = grade_single_eval(eval_config, session_dir, model=model, verbose=verbose)

        if grading:
            # 写入 grading.json
            output_dir = session_dir / eval_id / "with_skill" / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)
            grading_file = session_dir / eval_id / "grading.json"
            with open(grading_file, "w", encoding="utf-8") as f:
                json.dump(grading, f, ensure_ascii=False, indent=2)
            success_count += 1

    print(f"  📊 评审完成: {success_count}/{len(evals)} 成功", file=sys.stderr)
    return success_count > 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SkillSentry CI Grader")
    parser.add_argument("--evals", required=True, help="evals.json 路径")
    parser.add_argument("--session-dir", required=True, help="session 目录")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    success = grade_all_evals(
        evals_file=Path(args.evals),
        session_dir=Path(args.session_dir),
        model=args.model,
        verbose=args.verbose,
    )
    sys.exit(0 if success else 1)
