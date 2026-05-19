#!/usr/bin/env python3
"""
publish.py — SkillSentry 三件套一步到位发布脚本 v1.0

输入：workspace_dir, skill_name, user_open_id, mode, risk_level
输出：
  1. HTML 报告生成（调用 generate_html_report.py）
  2. 飞书云文档上传 + 所有权转让 → 返回链接
  3. history.json 追加本次记录

用法：
  python3 publish.py \
    --workspace-dir /path/to/iteration-N \
    --skill-name "finance-doc-query-prod" \
    --user-open-id "ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef" \
    --mode quick \
    --risk-level B \
    [--avg-delta 0.15] \
    [--folder-token "fldcnXXX"] \
    [--skip-feishu] \
    [--skip-history]

退出码：
  0 = 全部成功
  1 = 参数错误
  2 = HTML 生成失败
  3 = 飞书上传失败（HTML 仍存在本地）
  4 = history 更新失败（HTML + 飞书链接已成功）

输出 JSON 到 stdout（供 LLM 解析）：
{
  "status": "success" | "partial" | "error",
  "html_path": "/path/to/eval-report.html",
  "feishu_url": "https://mi.feishu.cn/docx/xxx" | null,
  "feishu_token": "doxcnXXX" | null,
  "history_updated": true | false,
  "message": "发送给用户的最终消息文本"
}
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args():
    p = argparse.ArgumentParser(description="SkillSentry publish: report + feishu + history")
    p.add_argument("--workspace-dir", required=True, help="iteration workspace 目录")
    p.add_argument("--skill-name", required=True, help="被测 Skill 名称")
    p.add_argument("--user-open-id", required=True, help="用户 open_id（所有权转让目标）")
    p.add_argument("--mode", default="quick", choices=["smoke", "quick", "standard", "full"])
    p.add_argument("--risk-level", default="B", choices=["S", "A", "B", "C"])
    p.add_argument("--avg-delta", type=float, default=None, help="平均增益 Δ")
    p.add_argument("--folder-token", default=None, help="飞书云空间目标文件夹 token")
    p.add_argument("--skip-feishu", action="store_true", help="跳过飞书上传")
    p.add_argument("--skip-history", action="store_true", help="跳过 history 更新")
    p.add_argument("--user-name", default="", help="用户名（用于报告标注）")
    return p.parse_args()


def step1_generate_html(workspace_dir: str, skill_name: str, risk_level: str, user_name: str) -> str:
    """生成 HTML 报告，返回报告文件路径"""
    script_dir = Path(__file__).parent
    gen_script = script_dir / "generate_html_report.py"

    output_path = os.path.join(workspace_dir, "eval-report.html")

    cmd = [
        sys.executable, str(gen_script),
        workspace_dir,
        "--skill-name", skill_name,
        "--risk-level", risk_level,
        "--output", output_path,
    ]
    if user_name:
        cmd.extend(["--user", user_name])

    print(f"[publish] Step 1: 生成 HTML 报告...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[publish] ❌ HTML 生成失败: {result.stderr}", file=sys.stderr)
        return None

    if not os.path.exists(output_path):
        print(f"[publish] ❌ HTML 文件未生成: {output_path}", file=sys.stderr)
        return None

    size = os.path.getsize(output_path)
    print(f"[publish] ✅ HTML 报告已生成: {output_path} ({size:,} bytes)", file=sys.stderr)
    return output_path


def step2_upload_feishu(html_path: str, skill_name: str, user_open_id: str,
                        folder_token: str = None) -> dict:
    """
    上传 HTML 到飞书云空间并转让所有权。
    返回 {"url": "...", "token": "..."} 或 None。

    注意：这个函数输出指令让 LLM 调用飞书 API（因为我们没有直接的飞书 SDK）。
    实际执行需要通过 OpenClaw 的飞书工具链。
    """
    print(f"[publish] Step 2: 上传飞书云空间...", file=sys.stderr)

    # 读取 HTML 文件大小
    size = os.path.getsize(html_path)
    filename = f"{skill_name}_eval-report_{datetime.now().strftime('%Y%m%d')}.html"

    # 输出上传指令（由调用方/LLM 执行）
    upload_instructions = {
        "action": "upload_html_to_feishu",
        "file_path": html_path,
        "file_name": filename,
        "folder_token": folder_token,
        "transfer_to": user_open_id,
        "size": size,
    }

    print(f"[publish] 📤 需要上传: {filename} ({size:,} bytes)", file=sys.stderr)
    print(f"[publish] 📤 转让给: {user_open_id}", file=sys.stderr)

    return upload_instructions


def step3_update_history(workspace_dir: str, skill_name: str, mode: str,
                         avg_delta: float = None) -> bool:
    """更新 history.json"""
    print(f"[publish] Step 3: 更新 history.json...", file=sys.stderr)

    script_dir = Path(__file__).parent
    update_script = script_dir / "update_history.py"

    cmd = [
        sys.executable, str(update_script),
        "--skill", skill_name,
        "--session-dir", workspace_dir,
        "--mode", mode,
    ]
    if avg_delta is not None:
        cmd.extend(["--avg-delta", str(avg_delta)])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[publish] ⚠️ history 更新失败: {result.stderr}", file=sys.stderr)
        # 不致命：尝试本地写入
        return fallback_history_update(workspace_dir, skill_name, mode, avg_delta)

    print(f"[publish] ✅ history.json 已更新", file=sys.stderr)
    if result.stdout:
        print(result.stdout, file=sys.stderr)
    return True


def fallback_history_update(workspace_dir: str, skill_name: str, mode: str,
                            avg_delta: float = None) -> bool:
    """当 update_history.py 的默认路径不存在时，尝试本地 fallback"""
    # 尝试在 skill 的 inputs 目录写入
    possible_paths = [
        Path.home() / ".openclaw" / "skills" / "skill-eval-测评" / "inputs" / skill_name / "history.json",
        Path.home() / ".claude" / "skills" / "SkillSentry" / "inputs" / skill_name / "history.json",
    ]

    for history_file in possible_paths:
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if history_file.exists():
                with open(history_file, encoding="utf-8-sig") as f:
                    data = json.load(f)
                    history = data if isinstance(data, list) else []

            # 读取 grading 数据
            ws_dir = Path(workspace_dir)
            total_passed = total_total = 0
            for eval_dir in sorted(ws_dir.iterdir()):
                if not eval_dir.name.startswith("eval-"):
                    continue
                # with_skill grading
                g_file = eval_dir / "with_skill" / "grading.json"
                if not g_file.exists():
                    g_file = eval_dir / "grading.json"
                if g_file.exists():
                    try:
                        g = json.load(open(g_file, encoding="utf-8-sig"))
                        s = g.get("summary", {})
                        total_passed += s.get("passed", 0)
                        total_total += s.get("total", 0)
                    except Exception:
                        pass

            pass_rate = round(total_passed / total_total, 4) if total_total > 0 else None

            entry = {
                "run_at": datetime.now(tz=timezone.utc).isoformat(),
                "session": os.path.basename(workspace_dir),
                "mode": mode,
                "eval_count": sum(1 for d in ws_dir.iterdir() if d.name.startswith("eval-")),
                "exact_pass_rate": pass_rate,
                "overall_pass_rate": pass_rate,
                "avg_delta": round(avg_delta, 4) if avg_delta is not None else None,
            }

            # 判决
            if pass_rate is None:
                entry["verdict"] = "ERROR"
            elif pass_rate >= 0.95:
                entry["verdict"] = "S"
            elif pass_rate >= 0.90:
                entry["verdict"] = "A"
            elif pass_rate >= 0.80:
                entry["verdict"] = "B"
            elif pass_rate >= 0.70:
                entry["verdict"] = "C"
            else:
                entry["verdict"] = "FAIL"

            if avg_delta is not None and avg_delta < 0:
                entry["verdict"] = "FAIL"

            # 幂等
            if not any(e.get("session") == entry["session"] for e in history):
                history.append(entry)

            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            print(f"[publish] ✅ fallback history 写入: {history_file}", file=sys.stderr)
            return True

        except Exception as e:
            print(f"[publish] ⚠️ fallback 路径失败 {history_file}: {e}", file=sys.stderr)
            continue

    return False


def read_grading_summary(workspace_dir: str) -> dict:
    """从 workspace 读取 grading 汇总数据，用于生成最终消息"""
    ws_dir = Path(workspace_dir)
    total_passed = total_total = 0
    eval_count = 0

    for eval_dir in sorted(ws_dir.iterdir()):
        if not eval_dir.name.startswith("eval-"):
            continue
        eval_count += 1
        # 尝试 with_skill/grading.json，再 fallback 到 grading.json
        g_file = eval_dir / "with_skill" / "grading.json"
        if not g_file.exists():
            g_file = eval_dir / "grading.json"
        if g_file.exists():
            try:
                g = json.load(open(g_file, encoding="utf-8-sig"))
                s = g.get("summary", {})
                total_passed += s.get("passed", 0)
                total_total += s.get("total", 0)
            except Exception:
                pass

    pass_rate = total_passed / total_total if total_total > 0 else 0
    return {
        "eval_count": eval_count,
        "total_passed": total_passed,
        "total_total": total_total,
        "pass_rate": pass_rate,
    }


def build_message(skill_name: str, mode: str, risk_level: str, grading: dict,
                  html_path: str, feishu_url: str = None, avg_delta: float = None) -> str:
    """生成发送给用户的最终消息文本"""
    rate = grading["pass_rate"]
    total_p = grading["total_passed"]
    total_t = grading["total_total"]
    eval_count = grading["eval_count"]

    # 判决
    risk_thresholds = {"S": 0.95, "A": 0.90, "B": 0.80, "C": 0.70}
    threshold = risk_thresholds.get(risk_level, 0.80)

    if rate >= threshold and (avg_delta is None or avg_delta >= 0):
        verdict = "PASS ✅"
        grade = "S" if rate >= 0.95 else ("A" if rate >= 0.90 else "B")
    elif rate >= threshold * 0.95:
        verdict = "CONDITIONAL PASS ⚠️"
        grade = "B"
    else:
        verdict = "FAIL ❌"
        grade = "C" if rate >= 0.70 else "F"

    delta_str = f"Δ {avg_delta:+.0%}" if avg_delta is not None else "Δ N/A"

    lines = [
        f"🦞 SkillSentry · {skill_name} · {mode} 模式测评完成",
        "",
        f"**{verdict}** · 等级 {grade} · {int(rate*100)}% ({total_p}/{total_t}) · {delta_str}",
        f"用例 {eval_count} 个 · 风险 {risk_level} 级 · 阈值 ≥{int(threshold*100)}%",
    ]

    if feishu_url:
        lines.append("")
        lines.append(f"📎 完整报告：{feishu_url}")
    elif html_path:
        lines.append("")
        lines.append(f"📎 本地报告：{html_path}")

    return "\n".join(lines)


def main():
    args = parse_args()
    ws_dir = os.path.abspath(args.workspace_dir)

    if not os.path.isdir(ws_dir):
        print(json.dumps({"status": "error", "message": f"workspace 不存在: {ws_dir}"}))
        sys.exit(1)

    result = {
        "status": "success",
        "html_path": None,
        "feishu_url": None,
        "feishu_token": None,
        "feishu_upload_instructions": None,
        "history_updated": False,
        "message": "",
    }

    # ── Step 1: HTML 报告 ──────────────────────────────────────────────────
    html_path = step1_generate_html(ws_dir, args.skill_name, args.risk_level, args.user_name)
    if not html_path:
        result["status"] = "error"
        result["message"] = "HTML 报告生成失败，请检查 workspace 中是否有 eval-*/grading.json"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(2)
    result["html_path"] = html_path

    # ── Step 2: 飞书上传指令 ───────────────────────────────────────────────
    if not args.skip_feishu:
        upload_info = step2_upload_feishu(
            html_path, args.skill_name, args.user_open_id, args.folder_token
        )
        result["feishu_upload_instructions"] = upload_info
    else:
        print(f"[publish] ⏭️ 跳过飞书上传 (--skip-feishu)", file=sys.stderr)

    # ── Step 3: History ────────────────────────────────────────────────────
    if not args.skip_history:
        history_ok = step3_update_history(ws_dir, args.skill_name, args.mode, args.avg_delta)
        result["history_updated"] = history_ok
        if not history_ok:
            if result["status"] == "success":
                result["status"] = "partial"
    else:
        print(f"[publish] ⏭️ 跳过 history 更新 (--skip-history)", file=sys.stderr)

    # ── 生成最终消息 ──────────────────────────────────────────────────────
    grading = read_grading_summary(ws_dir)
    message = build_message(
        args.skill_name, args.mode, args.risk_level, grading,
        html_path, result.get("feishu_url"), args.avg_delta
    )
    result["message"] = message

    # ── 输出 ──────────────────────────────────────────────────────────────
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result["status"] == "error":
        sys.exit(2)
    elif result["status"] == "partial":
        sys.exit(4)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
