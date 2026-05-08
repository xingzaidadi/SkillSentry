#!/usr/bin/env bash
# cleanup-old-memory.sh — 清理旧版 SkillSentry 的 memory 残留
# 用法: bash cleanup-old-memory.sh [--dry-run] [--force]
#
# 背景: SkillSentry v3→v5→v7.x 经历多次重构，旧版行为模式（纯文本列表）
#        会通过 memory_search 覆写新版的飞书交互卡片指令。
#        此脚本清理 MEMORY.md 和 memory/*.md 中的旧版 SkillSentry 引用。
#
# --dry-run: 只预览，不执行清理
# --force:   无人值守模式，跳过确认提示（适用于 cron）

set -euo pipefail

WORKSPACE="${OPENCLAW_WORKSPACE:-$HOME/.openclaw/workspace}"
DRY_RUN=false
FORCE=false
for arg in " "$@; do
  [[ "$arg" == " --dry-run" ]] && DRY_RUN=true
  [[ "$arg" == " --force" ]] && FORCE=true
done

echo "=== SkillSentry 旧记忆清理工具 ==="
echo "工作目录: $WORKSPACE"
echo "模式: $($DRY_RUN && echo '预览(dry-run)' || echo '执行')"

# 备份
BACKUP_DIR="$WORKSPACE/memory/.cleanup-backup-$(date +%Y%m%d%H%M%S)"
mkdir -p "$BACKUP_DIR"

cleaned=0

# 1. 清理 MEMORY.md 中的旧 SkillSentry 段落
if [[ -f "$WORKSPACE/MEMORY.md" ]]; then
    # 搜索包含 SkillSentry 旧版关键词的行
    old_patterns=$(grep -n -i "skillsentry\|skill.?sent\|sentry.?lint\|sentry.?trigger\|sentry.?cases\|sentry.?executor\|sentry.?grader\|sentry.?report" "$WORKSPACE/MEMORY.md" 2>/dev/null | grep -v "v7\.\|version.*7\.\|当前版本" || true)
    
    if [[ -n "$old_patterns" ]]; then
        echo ""
        echo "--- MEMORY.md 中发现旧版 SkillSentry 引用 ---"
        echo "$old_patterns"
        echo ""
        
        if $DRY_RUN; then
            echo "[dry-run] 将从 MEMORY.md 中移除以上行"
        else
            # 备份原文件
            cp "$WORKSPACE/MEMORY.md" "$BACKUP_DIR/MEMORY.md.bak"
            # 移除包含旧版引用的行（保留包含 v7 的行）
            grep -v -i "skillsentry\|skill.?sent\|sentry.?lint\|sentry.?trigger\|sentry.?cases\|sentry.?executor\|sentry.?grader\|sentry.?report" "$WORKSPACE/MEMORY.md" > "$WORKSPACE/MEMORY.md.tmp" || true
            mv "$WORKSPACE/MEMORY.md.tmp" "$WORKSPACE/MEMORY.md"
            echo "✅ MEMORY.md 已清理"
        fi
        ((cleaned++))
    fi
fi

# 2. 清理 memory/*.md 中的旧版 SkillSentry 会话记录
echo ""
echo "--- 扫描 memory/*.md ---"

for f in "$WORKSPACE"/memory/*.md; do
    [[ -f "$f" ]] || continue
    fname=$(basename "$f")
    
    # 跳过清理备份目录
    [[ "$fname" == ".cleanup-backup-"* ]] && continue
    
    # 检查是否包含 SkillSentry 相关内容
    if grep -q -i "skillsentry\|skill-eval-测评\|sentry-check\|sentry-cases\|sentry-executor\|sentry-grader\|sentry-report" "$f" 2>/dev/null; then
        # 检查是否是旧版本（不含 v7.6）
        has_new_version=$(grep -c "v7\.\|version.*7\." "$f" 2>/dev/null || echo "0")
        has_old_content=$(grep -c -i "skillsentry\|skill-eval-测评\|sentry-" "$f" 2>/dev/null || echo "0")
        
        if [[ "$has_old_content" -gt 0 && "$has_new_version" -eq 0 ]]; then
            echo "  📄 $fname — 旧版 SkillSentry 记录 ($has_old_content 行)"
            if $DRY_RUN; then
                echo "     [dry-run] 将归档到 $BACKUP_DIR/"
            else
                cp "$f" "$BACKUP_DIR/$fname"
                rm "$f"
                echo "     ✅ 已归档"
            fi
            ((cleaned++))
        elif [[ "$has_old_content" -gt 0 && "$has_new_version" -gt 0 ]]; then
            echo "  📄 $fname — 混合版本，需手动检查 ($has_old_content 旧 / $has_new_version 新)"
        fi
    fi
done

# 3. 清理 .dreams/ 中的旧引用
if [[ -d "$WORKSPACE/memory/.dreams" ]]; then
    echo ""
    echo "--- 扫描 memory/.dreams/ ---"
    for f in "$WORKSPACE"/memory/.dreams/*.txt; do
        [[ -f "$f" ]] || continue
        fname=$(basename "$f")
        if grep -q -i "skillsentry\|sentry-" "$f" 2>/dev/null; then
            has_new=$(grep -c "v7\." "$f" 2>/dev/null || echo "0")
            if [[ "$has_new" -eq 0 ]]; then
                echo "  📄 $fname — 旧版引用"
                if $DRY_RUN; then
                    echo "     [dry-run] 将归档"
                else
                    cp "$f" "$BACKUP_DIR/$fname"
                    rm "$f"
                    echo "     ✅ 已归档"
                fi
                ((cleaned++))
            fi
        fi
    done
fi

echo ""
echo "=== 完成: 清理了 $cleaned 个文件/段落 ==="
if ! $DRY_RUN && [[ $cleaned -gt 0 ]]; then
    echo "备份位置: $BACKUP_DIR"
    echo "⚠️ 建议重启 OpenClaw 会话以确保旧记忆完全清除"
fi
