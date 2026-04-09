#!/usr/bin/env bash
# SkillSentry 一键安装脚本
# 用法：cd SkillSentry && bash install.sh
# 支持：Claude Code（~/.claude/skills/）和 OpenCode（~/.config/opencode/skills/）

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="$REPO_DIR/tools"

CLAUDE_SKILLS="$HOME/.claude/skills"
OPENCODE_SKILLS="$HOME/.config/opencode/skills"

TOOLS=(sentry-lint sentry-trigger sentry-cases sentry-executor sentry-report)

# 检测目标平台
detect_targets() {
  TARGETS=()
  [[ -d "$HOME/.claude" ]]          && TARGETS+=("claude")
  [[ -d "$HOME/.config/opencode" ]] && TARGETS+=("opencode")

  if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "⚠️  未检测到 Claude Code 或 OpenCode，默认安装到 Claude Code 目录"
    TARGETS=("claude")
  fi
}

install_to() {
  local SKILLS_DIR="$1"
  local PLATFORM="$2"

  echo ""
  echo "📦 安装到 $PLATFORM（$SKILLS_DIR）"

  # 安装 SkillSentry 主体（排除 tools/ 本身，避免路径混乱）
  mkdir -p "$SKILLS_DIR/SkillSentry"
  rsync -a --exclude='.git' --exclude='tools' --exclude='sessions' \
    "$REPO_DIR/" "$SKILLS_DIR/SkillSentry/"
  echo "  ✅ SkillSentry"

  # 安装各 sentry-* 工具
  for tool in "${TOOLS[@]}"; do
    mkdir -p "$SKILLS_DIR/$tool"
    cp "$TOOLS_DIR/$tool/SKILL.md" "$SKILLS_DIR/$tool/SKILL.md"
    echo "  ✅ $tool"
  done
}

verify() {
  echo ""
  echo "🔍 验证安装..."
  local OK=true
  for SKILLS_DIR in "$CLAUDE_SKILLS" "$OPENCODE_SKILLS"; do
    [[ ! -d "$SKILLS_DIR/SkillSentry" ]] && continue
    echo "  📂 $SKILLS_DIR"
    for tool in SkillSentry "${TOOLS[@]}"; do
      if [[ -f "$SKILLS_DIR/$tool/SKILL.md" ]]; then
        echo "    ✅ $tool"
      else
        echo "    ❌ $tool（缺失）"
        OK=false
      fi
    done
  done
  $OK && echo "" && echo "🎉 安装完成！" || echo "" && echo "⚠️  部分文件缺失，请检查上方日志"
}

# --- 主流程 ---
echo "🛡  SkillSentry 安装脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━"

detect_targets

for target in "${TARGETS[@]}"; do
  case "$target" in
    claude)   install_to "$CLAUDE_SKILLS" "Claude Code" ;;
    opencode) install_to "$OPENCODE_SKILLS" "OpenCode" ;;
  esac
done

verify

echo ""
echo "使用方式："
echo "  Claude Code / OpenCode 中直接说：「测评 <你的Skill名>」"
echo ""
