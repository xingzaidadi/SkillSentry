#!/usr/bin/env python3
"""
SkillSentry 读取证明验证器

用途：在主编排器调用子工具后，验证输出是否包含 [sentry-proof] 标记。
     由主编排器通过 exec 调用，返回码决定是否继续。

用法：
  python3 verify_proof.py <output_text_file>
  
返回码：
  0 = 验证通过（包含 [sentry-proof]）
  1 = 验证失败（未包含 [sentry-proof]）
"""

import sys
from pathlib import Path

def verify(text: str) -> bool:
    return "[sentry-proof]" in text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # 从 stdin 读取
        text = sys.stdin.read()
    else:
        p = Path(sys.argv[1])
        if p.exists():
            text = p.read_text(encoding="utf-8")
        else:
            text = sys.argv[1]  # 直接传文本
    
    if verify(text):
        print("✅ [sentry-proof] 验证通过")
        sys.exit(0)
    else:
        print("❌ [sentry-proof] 未找到——子工具未按 SKILL.md 执行，需重跑")
        sys.exit(1)
