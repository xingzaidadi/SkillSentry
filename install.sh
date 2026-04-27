#!/usr/bin/env bash
# SkillSentry v7.0 一键安装脚本
# 用法：cd SkillSentry && bash install.sh
# 支持：Claude Code / OpenCode / OpenClaw

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="$REPO_DIR/tools"

CLAUDE_SKILLS="$HOME/.claude/skills"
OPENCODE_SKILLS="$HOME/.config/opencode/skills"
OPENCLAW_SKILLS="$HOME/.openclaw/skills"

# v7.0 活跃子工具
TOOLS=(sentry-check sentry-cases sentry-executor sentry-grader sentry-report)

# v7.0 归档 stub（仍需安装，避免旧引用报错）
ARCHIVED=(sentry-openclaw sentry-sync sentry-lint sentry-trigger)

detect_targets() {
  TARGETS=()
  [[ -d "$HOME/.openclaw" ]]         && TARGETS+=("openclaw")
  [[ -d "$HOME/.claude" ]]           && TARGETS+=("claude")
  [[ -d "$HOME/.config/opencode" ]]  && TARGETS+=("opencode")

  if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "⚠️  未检测到任何平台，默认安装到 OpenClaw 目录"
    TARGETS=("openclaw")
  fi
}

install_to() {
  local SKILLS_DIR="$1"
  local PLATFORM="$2"

  echo ""
  echo "📦 安装到 $PLATFORM（$SKILLS_DIR）"

  # 安装主体（排除 tools/ sessions/ .git）
  mkdir -p "$SKILLS_DIR/SkillSentry"
  rsync -a --exclude='.git' --exclude='tools' --exclude='sessions' \
    "$REPO_DIR/" "$SKILLS_DIR/SkillSentry/"
  echo "  ✅ SkillSentry（主编排 v7.0）"

  # 安装活跃子工具
  for tool in "${TOOLS[@]}"; do
    if [[ -d "$TOOLS_DIR/$tool" ]]; then
      mkdir -p "$SKILLS_DIR/$tool"
      cp "$TOOLS_DIR/$tool/SKILL.md" "$SKILLS_DIR/$tool/SKILL.md"
      echo "  ✅ $tool"
    else
      echo "  ⚠️  $tool（tools/ 中不存在，跳过）"
    fi
  done

  # 安装归档 stub
  for tool in "${ARCHIVED[@]}"; do
    if [[ -d "$TOOLS_DIR/$tool" ]]; then
      mkdir -p "$SKILLS_DIR/$tool"
      cp "$TOOLS_DIR/$tool/SKILL.md" "$SKILLS_DIR/$tool/SKILL.md"
      echo "  📦 $tool（归档 stub）"
    fi
  done

  # OpenClaw 额外：创建 workspace 运行时目录
  if [[ "$PLATFORM" == "OpenClaw" ]]; then
    local WS="$HOME/.openclaw/workspace/skills/skill-eval-测评"
    mkdir -p "$WS/sessions" "$WS/scripts"
    # 复制运行时脚本
    [[ -f "$REPO_DIR/scripts/validate_step.py" ]] && \
      cp "$REPO_DIR/scripts/validate_step.py" "$WS/scripts/"
    echo "  ✅ workspace 运行时目录已创建"
  fi
}

verify() {
  echo ""
  echo "🔍 验证安装..."
  local ALL_OK=true
  for SKILLS_DIR in "$OPENCLAW_SKILLS" "$CLAUDE_SKILLS" "$OPENCODE_SKILLS"; do
    [[ ! -d "$SKILLS_DIR/SkillSentry" ]] && continue
    echo "  📂 $SKILLS_DIR"
    for tool in SkillSentry "${TOOLS[@]}"; do
      if [[ -f "$SKILLS_DIR/$tool/SKILL.md" ]]; then
        echo "    ✅ $tool"
      else
        echo "    ❌ $tool（缺失）"
        ALL_OK=false
      fi
    done
  done
  $ALL_OK && echo "" && echo "🎉 安装完成！" || (echo "" && echo "⚠️  部分文件缺失，请检查上方日志")
}

echo "🛡  SkillSentry v7.0 安装脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

detect_targets

for target in "${TARGETS[@]}"; do
  case "$target" in
    openclaw) install_to "$OPENCLAW_SKILLS" "OpenClaw" ;;
    claude)   install_to "$CLAUDE_SKILLS" "Claude Code" ;;
    opencode) install_to "$OPENCODE_SKILLS" "OpenCode" ;;
  esac
done

verify

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "快速开始："
echo "  测评 <Skill名>     ← 自动推荐工作流"
echo "  lint <Skill名>     ← 30秒静态检查"
echo "  check <Skill名>    ← 静态检查 + 触发率"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
