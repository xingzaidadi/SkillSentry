#!/usr/bin/env python3
"""SkillSentry report server."""

from __future__ import annotations

import argparse
import http.server
import os
import signal
import sys
from pathlib import Path


DEFAULT_BASE_DIR = Path(os.path.expanduser("~/.openclaw/workspace/skills/skill-eval-娴嬭瘎/sessions"))


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    base_dir = DEFAULT_BASE_DIR

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.base_dir), **kwargs)

    def guess_type(self, path):
        mime = super().guess_type(path)
        if mime and mime.startswith("text/"):
            return mime + "; charset=utf-8"
        return mime

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._index_page().encode("utf-8"))
            return
        super().do_GET()

    def _index_page(self):
        items = []
        if self.base_dir.exists():
            for skill_name in sorted(os.listdir(self.base_dir)):
                skill_dir = self.base_dir / skill_name
                if not skill_dir.is_dir():
                    continue
                for session_name in sorted(os.listdir(skill_dir), reverse=True):
                    report = skill_dir / session_name / "report.html"
                    if report.exists():
                        items.append(f'<li><a href="/{skill_name}/{session_name}/report.html">{skill_name}</a> — {session_name}</li>')
                        break
        content = "\n".join(items) if items else "<li>暂无报告</li>"
        return (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'><title>SkillSentry</title>"
            "<style>body{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px}a{color:#4361ee}</style></head>"
            "<body><h1>SkillSentry 报告中心</h1><ul>"
            + content
            + "</ul></body></html>"
        )

    def log_message(self, *args):
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SkillSentry report server")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR), help="Sessions base directory")
    parser.add_argument("--port", type=int, default=18080)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ReportHandler.base_dir = Path(args.base_dir)
    server = http.server.HTTPServer(("0.0.0.0", args.port), ReportHandler)
    print(f"SkillSentry report server running: http://0.0.0.0:{args.port}", flush=True)
    signal.signal(signal.SIGTERM, lambda *unused: sys.exit(0))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
