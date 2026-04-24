#!/usr/bin/env python3
"""SkillSentry HTML 报告托管服务（UTF-8 修复版）"""
import http.server
import os, sys, signal

PORT = 18080
BASE_DIR = os.path.expanduser("~/.openclaw/workspace/skills/SkillSentry/sessions")

class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def guess_type(self, path):
        mime = super().guess_type(path)
        if mime and mime.startswith("text/"):
            return mime + "; charset=utf-8"
        return mime

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._index_page().encode())
            return
        super().do_GET()

    def _index_page(self):
        items = ""
        for skill_name in sorted(os.listdir(BASE_DIR)):
            skill_dir = os.path.join(BASE_DIR, skill_name)
            if not os.path.isdir(skill_dir): continue
            for s in sorted(os.listdir(skill_dir), reverse=True):
                report = os.path.join(skill_dir, s, "report.html")
                if os.path.exists(report):
                    items += f'<li><a href="/{skill_name}/{s}/report.html">{skill_name}</a> — {s}</li>\n'
                    break
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>SkillSentry</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;padding:0 20px}}a{{color:#4361ee}}</style></head>
<body><h1>🛡 SkillSentry 报告中心</h1><ul>{items if items else "<li>暂无报告</li>"}</ul></body></html>"""

    def log_message(self, *a): pass

server = http.server.HTTPServer(("0.0.0.0", PORT), ReportHandler)
print(f"🛡 服务启动: http://0.0.0.0:{PORT}", flush=True)
signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
server.serve_forever()
