#!/usr/bin/env python3
"""
SkillSentry Dashboard - 成功率统计

扫描 sessions/ 下所有 session.json，统计测评完成率。
输出 markdown 表格。

Usage:
    python3 scripts/dashboard.py [--sessions-dir PATH]
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime


def find_sessions_dir():
    """Find sessions directory."""
    candidates = [
        Path(__file__).parent.parent / "../../data/skill-eval/sessions",
        Path.home() / ".openclaw/data/skill-eval/sessions",
        Path.home() / ".claude/data/skill-eval/sessions",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def scan_sessions(sessions_dir: Path):
    """Scan all session.json files recursively."""
    results = []
    for session_file in sessions_dir.rglob("session.json"):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "path": str(session_file),
                "skill": data.get("skill", "unknown"),
                "mode": data.get("mode", "unknown"),
                "last_step": data.get("last_step"),
                "started_at": data.get("started_at", ""),
                "grade": data.get("verdict", {}).get("grade", ""),
                "pass_rate": data.get("verdict", {}).get("pass_rate", 0),
            })
        except (json.JSONDecodeError, IOError):
            continue
    return results


def extract_date(started_at: str) -> str:
    """Extract date from ISO timestamp."""
    if not started_at:
        return "unknown"
    try:
        return started_at[:10]
    except (IndexError, TypeError):
        return "unknown"


def generate_dashboard(sessions):
    """Generate markdown dashboard tables."""
    if not sessions:
        return "No sessions found.\n"

    lines = []
    lines.append("# SkillSentry Dashboard\n")
    lines.append(f"Generated: {datetime.now().isoformat()[:19]}\n")

    # Overall stats
    total = len(sessions)
    completed = sum(1 for s in sessions if s["last_step"] == "publish")
    lines.append(f"## Overall\n")
    lines.append(f"- Total sessions: {total}")
    lines.append(f"- Completed (publish): {completed}")
    lines.append(f"- Success rate: {completed/total*100:.1f}%\n")

    # By mode
    by_mode = defaultdict(lambda: {"total": 0, "completed": 0})
    for s in sessions:
        mode = s["mode"]
        by_mode[mode]["total"] += 1
        if s["last_step"] == "publish":
            by_mode[mode]["completed"] += 1

    lines.append("## By Mode\n")
    lines.append("| Mode | Total | Completed | Success Rate |")
    lines.append("|------|-------|-----------|--------------|")
    for mode, stats in sorted(by_mode.items()):
        rate = stats["completed"] / stats["total"] * 100 if stats["total"] else 0
        lines.append(f"| {mode} | {stats['total']} | {stats['completed']} | {rate:.1f}% |")
    lines.append("")

    # By date
    by_date = defaultdict(lambda: {"total": 0, "completed": 0})
    for s in sessions:
        date = extract_date(s["started_at"])
        by_date[date]["total"] += 1
        if s["last_step"] == "publish":
            by_date[date]["completed"] += 1

    lines.append("## By Date\n")
    lines.append("| Date | Total | Completed | Success Rate |")
    lines.append("|------|-------|-----------|--------------|")
    for date, stats in sorted(by_date.items(), reverse=True):
        rate = stats["completed"] / stats["total"] * 100 if stats["total"] else 0
        lines.append(f"| {date} | {stats['total']} | {stats['completed']} | {rate:.1f}% |")
    lines.append("")

    # Recent incomplete sessions
    incomplete = [s for s in sessions if s["last_step"] != "publish"]
    if incomplete:
        lines.append("## Incomplete Sessions (last 10)\n")
        lines.append("| Skill | Mode | Stopped At | Started |")
        lines.append("|-------|------|-----------|---------|")
        for s in sorted(incomplete, key=lambda x: x["started_at"], reverse=True)[:10]:
            lines.append(f"| {s['skill']} | {s['mode']} | {s['last_step'] or 'init'} | {extract_date(s['started_at'])} |")
        lines.append("")

    return "\n".join(lines)


def main():
    sessions_dir = None
    if len(sys.argv) > 2 and sys.argv[1] == "--sessions-dir":
        sessions_dir = Path(sys.argv[2])
    else:
        sessions_dir = find_sessions_dir()

    if not sessions_dir or not sessions_dir.exists():
        print("❌ Sessions directory not found.", file=sys.stderr)
        sys.exit(1)

    sessions = scan_sessions(sessions_dir)
    dashboard = generate_dashboard(sessions)
    print(dashboard)


if __name__ == "__main__":
    main()
