#!/usr/bin/env bash
# install.sh — SkillSentry 部署后验证 + manifest 对齐
# 不删除任何 memory 文件。只验证文件完整性、版本一致性和 manifest 状态。
# 用法: bash install.sh [--restart]

set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
MANIFEST="$HOME/.openclaw/skill_manifest.json"
RESTART=false
for arg in " $@"; do
    [[ "$arg" == " --restart" ]] && RESTART=true
done

echo "🦞 SkillSentry Installer"
echo "========================"
echo "Skill 目录: $SKILL_DIR"
echo "工作目录:   $WORKSPACE"
echo ""

# ─── Step 1: 验证 Skill 文件完整性 ───
echo "📋 Step 1: 文件完整性检查"

required_files=(
    "SKILL.md"
    "tools/sentry-check/SKILL.md"
    "tools/sentry-cases/SKILL.md"
    "tools/sentry-executor/SKILL.md"
    "tools/sentry-grader/SKILL.md"
    "tools/sentry-report/SKILL.md"
)

missing=0
for f in "${required_files[@]}"; do
    if [[ -f "$SKILL_DIR/$f" ]]; then
        echo "  ✅ $f"
    else
        echo "  ❌ $f — 缺失"
        missing=$((missing + 1))
    fi
done

if [[ $missing -gt 0 ]]; then
    echo ""
    echo "❌ 缺少 $missing 个必需文件，安装中止"
    exit 1
fi
echo ""

# ─── Step 2: 检查版本号 ───
echo "📋 Step 2: 版本检查"
version=$(grep -m1 'version:' "$SKILL_DIR/SKILL.md" | sed 's/.*"\(.*\)".*/\1/')
echo "  当前版本: v${version}"
echo ""

# ─── Step 3: 验证行为优先级指令 ───
echo "📋 Step 3: 验证行为优先级指令"
if grep -q "版本锁定.*行为优先级\|行为优先级" "$SKILL_DIR/SKILL.md" 2>/dev/null; then
    echo "  ✅ SKILL.md 包含行为优先级指令（SKILL.md > memory）"
else
    echo "  ⚠️ SKILL.md 缺少行为优先级指令（版本可能过旧）"
fi
echo ""

# ─── Step 4: 验证交互卡片指令 ───
echo "📋 Step 4: 验证交互卡片指令"
if grep -q "feishu_ask_user_question" "$SKILL_DIR/SKILL.md" 2>/dev/null; then
    echo "  ✅ SKILL.md 包含 feishu_ask_user_question 调用规范"
else
    echo "  ⚠️ SKILL.md 缺少交互卡片指令"
fi
echo ""

# ─── Step 5: 检查 manifest 中的 contentHash ───
echo "📋 Step 5: manifest 对齐检查"
need_restart=false

if [[ -f "$MANIFEST" ]]; then
    current_hash=$(sha256sum "$SKILL_DIR/SKILL.md" | cut -d' ' -f1)
    manifest_hash=$(python3 -c "
import json,sys
try:
    d=json.load(open('$MANIFEST'))
    h=d.get('skills',{}).get('skill-eval-测评',{}).get('contentHash','NOT_FOUND')
    print(h)
except:
    print('PARSE_ERROR')
" 2>/dev/null || echo "PARSE_ERROR")

    if [[ "$manifest_hash" == "$current_hash" ]]; then
        echo "  ✅ manifest hash 与 SKILL.md 一致（gateway 已加载最新版本）"
    elif [[ "$manifest_hash" == "NOT_FOUND" ]]; then
        echo "  ⚠️ manifest 中未找到 skill-eval-测评（首次注册，gateway 需重启）"
        need_restart=true
    elif [[ "$manifest_hash" == "PARSE_ERROR" ]]; then
        echo "  ⚠️ manifest 解析失败，建议重启 gateway"
        need_restart=true
    else
        echo "  ⚠️ manifest hash 与 SKILL.md 不一致!"
        echo "     manifest: $manifest_hash"
        echo "     SKILL.md: $current_hash"
        echo "     → gateway 仍在使用旧版本的 skill description"
        echo "     → 重启 gateway 后 agent 才能看到新版 description 中的规则"
        need_restart=true
    fi
else
    echo "  ℹ️ skill_manifest.json 不存在（gateway 首次启动时会自动创建）"
fi
echo ""

# ─── Step 6: 检查 memory 中的旧行为模式（仅供参考，不删除）───
echo "📋 Step 6: memory 冲突检测（仅供参考）"
old_behaviors=0
if [[ -d "$WORKSPACE/memory" ]]; then
    while IFS= read -r f; do
        [[ -f "$f" ]] || continue
        if grep -q "报个编号.*直接开干\|纯文本.*列表\|Markdown.*表格.*罗列" "$f" 2>/dev/null; then
            fname=$(basename "$f")
            echo "  ⚠️ $fname — 可能含旧版行为模式"
            old_behaviors=$((old_behaviors + 1))
        fi
    done < <(find "$WORKSPACE/memory" -name "*.md" -type f 2>/dev/null)
fi

if [[ $old_behaviors -eq 0 ]]; then
    echo "  ✅ 未发现旧版行为模式冲突"
else
    echo "  ℹ️ 发现 $old_behaviors 处旧版行为模式（不影响运行，SKILL.md 优先级更高）"
fi
echo ""

# ─── 完成 ───
echo "========================"
echo "🦞 SkillSentry v${version} 安装完成"

if $need_restart; then
    echo ""
    echo "⚠️ 检测到 manifest 需要更新。"
    if $RESTART; then
        echo "正在重启 gateway..."
        openclaw gateway restart 2>/dev/null && echo "✅ gateway 已重启" || echo "❌ 重启失败，请手动执行: openclaw gateway restart"
    else
        echo "请执行: openclaw gateway restart"
        echo "或重新运行: bash install.sh --restart"
    fi
fi

echo ""
echo "行为优先级规则: SKILL.md > memory"
echo "memory 文件保留不动，行为冲突时以 SKILL.md 为准。"
