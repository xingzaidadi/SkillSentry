#!/usr/bin/env python3
"""
SkillSentry CI Executor — 用 claude CLI 逐个执行测试用例

每个 eval 独立 subprocess，隔离故障、可超时、可重试。
产出：eval-N/with_skill/outputs/transcript.md + response.md
"""

import json
import subprocess
import sys
import time
from pathlib import Path


def build_eval_prompt(eval_config: dict, skill_content: str) -> str:
    """构造单个 eval 的执行 prompt"""
    prompt = eval_config.get("prompt", "")
    name = eval_config.get("name", "unknown")

    return f"""你正在执行一个 AI Skill 的测试用例。

## 被测 Skill
以下是被测 Skill 的完整定义，你必须按照它的流程来响应用户输入：

```
{skill_content}
```

## 测试用例
用例名：{name}

## 用户输入（你需要按照上面 Skill 的流程来响应这个输入）

{prompt}

---

请按照被测 Skill 的定义来处理上面的用户输入。直接给出响应，不要说"我在测试"之类的元评论。"""


def execute_single_eval(
    eval_config: dict,
    skill_path: Path,
    session_dir: Path,
    eval_idx: int,
    model: str = "claude-sonnet-4-6",
    timeout: int = 120,
    verbose: bool = False,
) -> dict:
    """执行单个 eval，返回结果字典"""
    eval_id = eval_config.get("id", f"eval-{eval_idx}")
    name = eval_config.get("name", "unknown")

    # 创建输出目录
    output_dir = session_dir / eval_id / "with_skill" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    skill_content = skill_path.read_text(encoding="utf-8")
    prompt = build_eval_prompt(eval_config, skill_content)

    start = time.time()
    result = {"eval_id": eval_id, "name": name, "status": "unknown", "duration": 0}

    try:
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--output-format", "text",
            "-p", prompt,
        ]
        if model:
            cmd.extend(["--model", model])

        proc = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=str(session_dir),
        )

        duration = time.time() - start
        result["duration"] = round(duration, 1)

        if proc.returncode == 0 and proc.stdout.strip():
            response = proc.stdout.strip()

            # 写 response.md
            with open(output_dir / "response.md", "w", encoding="utf-8") as f:
                f.write(response)

            # 写 transcript.md（包含 prompt + response）
            transcript = f"""## User Input
{eval_config.get('prompt', '')}

## Skill Response
{response}
"""
            with open(output_dir / "transcript.md", "w", encoding="utf-8") as f:
                f.write(transcript)

            result["status"] = "success"
            result["response_length"] = len(response)

            if verbose:
                print(f"  ✅ {eval_id} ({name}): {duration:.1f}s, {len(response)} chars", file=sys.stderr)
        else:
            result["status"] = "failed"
            result["error"] = proc.stderr[:500] if proc.stderr else "empty response"

            # 写空文件标记失败
            with open(output_dir / "response.md", "w", encoding="utf-8") as f:
                f.write(f"[EXECUTION FAILED]\n{proc.stderr[:500]}")

            if verbose:
                print(f"  ❌ {eval_id} ({name}): exit={proc.returncode}", file=sys.stderr)

    except subprocess.TimeoutExpired:
        duration = time.time() - start
        result["duration"] = round(duration, 1)
        result["status"] = "timeout"
        result["error"] = f"Timeout after {timeout}s"

        with open(output_dir / "response.md", "w", encoding="utf-8") as f:
            f.write(f"[TIMEOUT after {timeout}s]")

        if verbose:
            print(f"  ⏰ {eval_id} ({name}): timeout", file=sys.stderr)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

        if verbose:
            print(f"  💥 {eval_id} ({name}): {e}", file=sys.stderr)

    return result


def execute_all_evals(
    evals_file: Path,
    skill_path: Path,
    session_dir: Path,
    model: str = "claude-sonnet-4-6",
    timeout_per_eval: int = 120,
    verbose: bool = False,
) -> bool:
    """执行所有 evals，返回是否有至少 1 个成功"""
    with open(evals_file, encoding="utf-8") as f:
        evals = json.load(f)

    if not evals:
        print("  ⚠️ evals.json 为空", file=sys.stderr)
        return False

    print(f"  📋 执行 {len(evals)} 个用例 (model={model}, timeout={timeout_per_eval}s/eval)", file=sys.stderr)

    results = []
    success_count = 0

    for idx, eval_config in enumerate(evals, 1):
        result = execute_single_eval(
            eval_config=eval_config,
            skill_path=skill_path,
            session_dir=session_dir,
            eval_idx=idx,
            model=model,
            timeout=timeout_per_eval,
            verbose=verbose,
        )
        results.append(result)
        if result["status"] == "success":
            success_count += 1

    # 写执行摘要
    exec_summary = {
        "total": len(results),
        "success": success_count,
        "failed": len(results) - success_count,
        "results": results,
    }

    with open(session_dir / "executor_results.json", "w", encoding="utf-8") as f:
        json.dump(exec_summary, f, ensure_ascii=False, indent=2)

    print(f"  📊 执行完成: {success_count}/{len(results)} 成功", file=sys.stderr)

    # 至少 1 个成功即可继续 grader
    return success_count > 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SkillSentry CI Executor")
    parser.add_argument("--evals", required=True, help="evals.json 路径")
    parser.add_argument("--skill", required=True, help="SKILL.md 路径")
    parser.add_argument("--session-dir", required=True, help="session 目录")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    success = execute_all_evals(
        evals_file=Path(args.evals),
        skill_path=Path(args.skill),
        session_dir=Path(args.session_dir),
        model=args.model,
        timeout_per_eval=args.timeout,
        verbose=args.verbose,
    )
    sys.exit(0 if success else 1)
