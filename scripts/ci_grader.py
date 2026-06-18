#!/usr/bin/env python3
"""
SkillSentry CI Grader — 用 Anthropic SDK 直调 LLM 做断言评审

不依赖 claude CLI，纯 API 调用，适合 CI 环境。
产出：eval-N/with_skill/outputs/grading.json
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import anthropic
except ImportError:
    anthropic = None


def _claude_fallback_enabled() -> bool:
    return os.environ.get("SKILLSENTRY_CI_LLM_FALLBACK", "").lower() == "claude"


def _call_claude_cli(prompt: str, model: str = "sonnet", max_tokens: int = 4000) -> str | None:
    """Optional local fallback for CI smoke validation when SDK calls are unavailable."""
    if not _claude_fallback_enabled():
        return None
    claude_cmd = shutil.which("claude.cmd") or shutil.which("claude")
    if not claude_cmd:
        print("  ❌ SKILLSENTRY_CI_LLM_FALLBACK=claude but claude CLI was not found", file=sys.stderr)
        return None

    cli_model = os.environ.get("SKILLSENTRY_CI_CLAUDE_MODEL", model or "sonnet")
    if cli_model == "claude-sonnet-4-6":
        cli_model = "sonnet"

    cmd = [
        claude_cmd,
        "--output-format",
        "text",
        "-p",
        "--model",
        cli_model,
        "--max-budget-usd",
        os.environ.get("SKILLSENTRY_CI_CLAUDE_MAX_BUDGET_USD", "1"),
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(os.environ.get("SKILLSENTRY_CI_CLAUDE_TIMEOUT", "300")),
        )
    except Exception as exc:
        print(f"  ❌ claude CLI fallback failed before completion: {exc}", file=sys.stderr)
        return None

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        print(f"  ❌ claude CLI fallback failed: {err[:500]}", file=sys.stderr)
        return None
    return proc.stdout.strip()


def call_llm(prompt: str, model: str = "claude-sonnet-4-6", max_tokens: int = 4000) -> str | None:
    """通用 LLM 调用（Anthropic SDK），供 sentry_ci.py 的 check/cases 步骤复用"""
    if anthropic is None:
        print("  ❌ anthropic SDK 未安装，请 pip install anthropic", file=sys.stderr)
        return _call_claude_cli(prompt, model=model, max_tokens=max_tokens)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ❌ ANTHROPIC_API_KEY 环境变量未设置", file=sys.stderr)
        return _call_claude_cli(prompt, model=model, max_tokens=max_tokens)

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
        return _call_claude_cli(prompt, model=model, max_tokens=max_tokens)


def grade_exact_match(expected: str, response_text: str) -> tuple[bool, str]:
    """确定性评审：exact_match——response 中必须包含 expected 文本（忽略首尾空白）。
    返回 (pass, evidence)。"""
    needle = expected.strip()
    if needle in response_text:
        # 截取匹配位置的上下文作为 evidence（最多 60 字）
        idx = response_text.find(needle)
        start = max(0, idx - 10)
        snippet = response_text[start: idx + len(needle) + 10].replace("\n", " ")
        return True, f"found: 「{snippet[:60]}」"
    return False, f"not found: 「{needle[:60]}」"


def grade_existence(expected: str, response_text: str) -> tuple[bool, str]:
    """确定性评审：existence——检查 expected 描述的关键词是否出现在 response 中。
    策略：取 expected 中所有长度>=2 的 token，至少一个在 response 中即为通过。
    这是保守策略，对于纯关键词断言准确；如需更精确可升级为 semantic。
    返回 (pass, evidence)。"""
    # 以空格/标点分词，取实质性关键词
    import re as _re
    tokens = [t for t in _re.split(r"[\s,，。；;:：!！?？、]+", expected.strip()) if len(t) >= 2]
    if not tokens:
        # 没有可用 token，退化为 exact_match
        return grade_exact_match(expected, response_text)
    found_tokens = [t for t in tokens if t in response_text]
    if found_tokens:
        return True, f"found token(s): {found_tokens[:3]}"
    return False, f"none of {tokens[:5]} found in response"


def build_grading_prompt(eval_config: dict, transcript: str, response_text: str, semantic_only_assertions: list) -> str:
    """构造单个 eval 的评审 prompt——只包含 semantic 断言。"""
    name = eval_config.get("name", "unknown")
    assertions_text = json.dumps(semantic_only_assertions, ensure_ascii=False, indent=2)

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

## 待评审断言（仅 semantic 类型）
```json
{assertions_text}
```

## 评审规则
- semantic：response 的语义必须符合 expected 描述的含义（不要求精确措辞）

## 输出格式
请以 JSON 格式返回评审结果（直接返回 JSON，不要 markdown 包裹）：
{{
  "assertions": [
    {{
      "name": "断言名",
      "type": "semantic",
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


def build_failed_grading(eval_config: dict, reason: str) -> dict:
    """Build a deterministic failing grading result when the grader cannot score."""
    eval_id = eval_config.get("id", "eval-1")
    assertions = eval_config.get("assertions", [])
    exact_total = sum(1 for a in assertions if a.get("type") == "exact_match")
    sem_total = sum(1 for a in assertions if a.get("type") == "semantic")

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
                        "evidence": reason,
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
                "exact_match": {"pass": 0, "total": exact_total},
                "semantic": {"pass": 0, "total": sem_total},
            },
            "authoritative_pass_rate": 0.0,
            "grader_error": reason,
        },
    }


def attach_grader_timing(grading: dict, started: float) -> dict:
    """Attach observational grader timing without changing scoring fields."""
    duration_ms = round((time.time() - started) * 1000, 1)
    grading["duration_ms"] = duration_ms
    timing = grading.get("timing") if isinstance(grading.get("timing"), dict) else {}
    timing["grader_duration_ms"] = duration_ms
    grading["timing"] = timing
    return grading


def grade_single_eval(
    eval_config: dict,
    session_dir: Path,
    model: str = "claude-sonnet-4-6",
    verbose: bool = False,
) -> dict | None:
    """评审单个 eval，返回 grading 数据"""
    eval_id = eval_config.get("id", "eval-1")
    started = time.time()
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
        return attach_grader_timing({
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
        }, started)

    # ──────────────────────────────────────────────────
    # 确定性评审：exact_match / existence 无需 LLM
    # ──────────────────────────────────────────────────
    deterministic_results: list[dict] = []
    semantic_assertions: list[dict] = []

    for i, a in enumerate(assertions):
        a_type = a.get("type", "semantic")
        a_name = a.get("name", f"A{i+1}")
        a_expected = a.get("expected", "")

        if a_type == "exact_match":
            passed, evidence = grade_exact_match(a_expected, response_text)
            deterministic_results.append({
                "name": a_name,
                "type": a_type,
                "expected": a_expected,
                "pass": passed,
                "evidence": evidence,
                "graded_by": "deterministic",
            })
        elif a_type == "existence":
            passed, evidence = grade_existence(a_expected, response_text)
            deterministic_results.append({
                "name": a_name,
                "type": a_type,
                "expected": a_expected,
                "pass": passed,
                "evidence": evidence,
                "graded_by": "deterministic",
            })
        else:
            # semantic 或未知类型 → 留给 LLM
            semantic_assertions.append(a)

    det_count = len(deterministic_results)
    sem_count = len(semantic_assertions)

    if verbose and det_count > 0:
        det_pass = sum(1 for r in deterministic_results if r["pass"])
        print(
            f"  ⚡ {eval_id}: 确定性评审 {det_count} 条 ({det_pass} pass)，"
            f"LLM 评审 {sem_count} 条",
            file=sys.stderr,
        )

    # ──────────────────────────────────────────────────
    # LLM 评审：仅 semantic 断言（如果有）
    # ──────────────────────────────────────────────────
    llm_results: list[dict] = []

    if semantic_assertions:
        prompt = build_grading_prompt(eval_config, transcript, response_text, semantic_assertions)
        result = call_llm(prompt, model=model, max_tokens=2000)

        if not result:
            if verbose:
                print(f"  ❌ {eval_id}: LLM 评审调用失败", file=sys.stderr)
            # LLM 失败时，semantic 断言全部标记失败
            llm_results = [
                {
                    "name": a.get("name", f"A{i+1}"),
                    "type": "semantic",
                    "expected": a.get("expected", ""),
                    "pass": False,
                    "evidence": "LLM grader call failed",
                    "graded_by": "llm",
                }
                for i, a in enumerate(semantic_assertions)
            ]
        else:
            try:
                json_match = re.search(r"\{[\s\S]*\}", result)
                if not json_match:
                    raise ValueError("LLM grader returned no JSON")
                grading_data = json.loads(json_match.group())
                graded = grading_data.get("assertions", [])
                # 补齐 graded_by 字段
                for g in graded:
                    g["graded_by"] = "llm"
                llm_results = graded
            except (json.JSONDecodeError, ValueError) as e:
                if verbose:
                    print(f"  ❌ {eval_id}: LLM 返回解析失败: {e}", file=sys.stderr)
                llm_results = [
                    {
                        "name": a.get("name", f"A{i+1}"),
                        "type": "semantic",
                        "expected": a.get("expected", ""),
                        "pass": False,
                        "evidence": f"LLM parse error: {e}",
                        "graded_by": "llm",
                    }
                    for i, a in enumerate(semantic_assertions)
                ]

    # ──────────────────────────────────────────────────
    # 合并结果，构造标准格式 grading.json
    # ──────────────────────────────────────────────────
    # 合并：先 deterministic，后 llm（保持原始断言顺序）
    # 通过 name 对齐
    name_to_result: dict[str, dict] = {}
    for r in deterministic_results:
        name_to_result[r["name"]] = r
    for r in llm_results:
        name_to_result[r.get("name", "")] = r

    # 按原始断言顺序重排
    all_graded = []
    for i, a in enumerate(assertions):
        a_name = a.get("name", f"A{i+1}")
        r = name_to_result.get(a_name, {
            "name": a_name,
            "type": a.get("type", "semantic"),
            "expected": a.get("expected", ""),
            "pass": False,
            "evidence": "grading result missing",
            "graded_by": "unknown",
        })
        all_graded.append(r)

    exact_pass = sum(1 for r in all_graded if r.get("type") == "exact_match" and r.get("pass"))
    exact_total = sum(1 for r in all_graded if r.get("type") == "exact_match")
    sem_pass = sum(1 for r in all_graded if r.get("type") == "semantic" and r.get("pass"))
    sem_total = sum(1 for r in all_graded if r.get("type") == "semantic")
    total_pass = sum(1 for r in all_graded if r.get("pass"))
    total_fail = len(all_graded) - total_pass
    total_count = len(all_graded)

    grading = {
        "eval_id": eval_id,
        "runs": {
            "run-1": {
                "pass": total_fail == 0,
                "assertions": [
                    {
                        "id": r.get("name", f"A{i+1}"),
                        "type": r.get("type", "semantic"),
                        "expect": r.get("expected", r.get("expect", "")),
                        "pass": r.get("pass", False),
                        "evidence": r.get("evidence", ""),
                        "graded_by": r.get("graded_by", "unknown"),
                    }
                    for i, r in enumerate(all_graded)
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
            "deterministic_count": det_count,
            "llm_count": sem_count,
        },
    }

    if verbose:
        print(f"  ✅ {eval_id} ({name}): {total_pass}/{total_count} 断言通过 (det={det_count}, llm={sem_count})", file=sys.stderr)

    return attach_grader_timing(grading, started)


def grade_all_evals(
    evals_file: Path,
    session_dir: Path,
    model: str = "claude-sonnet-4-6",
    verbose: bool = False,
) -> bool:
    """评审所有 evals，写入 grading.json，返回是否有至少 1 个成功"""
    with open(evals_file, encoding="utf-8-sig") as f:
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
