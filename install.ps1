# SkillSentry 一键安装脚本（Windows PowerShell）
# 用法：cd SkillSentry; .\install.ps1
# 支持：Claude Code（%USERPROFILE%\.claude\skills\）和 OpenCode（%APPDATA%\opencode\skills\）

$ErrorActionPreference = "Stop"

$RepoDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir  = Join-Path $RepoDir "tools"

$ClaudeSkills   = Join-Path $env:USERPROFILE ".claude\skills"
$OpenCodeSkills = Join-Path $env:APPDATA "opencode\skills"

$Tools = @("sentry-lint","sentry-trigger","sentry-cases","sentry-executor","sentry-report")

# 检测目标平台
$Targets = @()
if (Test-Path (Join-Path $env:USERPROFILE ".claude"))                  { $Targets += "claude" }
if (Test-Path (Join-Path $env:APPDATA "opencode"))                     { $Targets += "opencode" }
if ($Targets.Count -eq 0) {
    Write-Host "⚠️  未检测到 Claude Code 或 OpenCode，默认安装到 Claude Code 目录" -ForegroundColor Yellow
    $Targets += "claude"
}

function Install-To {
    param($SkillsDir, $Platform)

    Write-Host ""
    Write-Host "📦 安装到 $Platform（$SkillsDir）" -ForegroundColor Cyan

    # SkillSentry 主体（排除 tools/ 和 sessions/）
    $Dest = Join-Path $SkillsDir "SkillSentry"
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null

    Get-ChildItem -Path $RepoDir | Where-Object {
        $_.Name -notin @("tools","sessions",".git")
    } | Copy-Item -Destination $Dest -Recurse -Force

    Write-Host "  ✅ SkillSentry"

    # 各 sentry-* 工具
    foreach ($tool in $Tools) {
        $toolDest = Join-Path $SkillsDir $tool
        New-Item -ItemType Directory -Force -Path $toolDest | Out-Null
        $src = Join-Path $ToolsDir "$tool\SKILL.md"
        Copy-Item -Path $src -Destination (Join-Path $toolDest "SKILL.md") -Force
        Write-Host "  ✅ $tool"
    }
}

function Verify-Install {
    Write-Host ""
    Write-Host "🔍 验证安装..." -ForegroundColor Cyan
    $OK = $true
    foreach ($SkillsDir in @($ClaudeSkills, $OpenCodeSkills)) {
        if (-not (Test-Path (Join-Path $SkillsDir "SkillSentry"))) { continue }
        Write-Host "  📂 $SkillsDir"
        foreach ($tool in (@("SkillSentry") + $Tools)) {
            $f = Join-Path $SkillsDir "$tool\SKILL.md"
            if (Test-Path $f) {
                Write-Host "    ✅ $tool"
            } else {
                Write-Host "    ❌ $tool（缺失）" -ForegroundColor Red
                $OK = $false
            }
        }
    }
    if ($OK) {
        Write-Host ""
        Write-Host "🎉 安装完成！" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "⚠️  部分文件缺失，请检查上方日志" -ForegroundColor Yellow
    }
}

# --- 主流程 ---
Write-Host "🛡  SkillSentry 安装脚本" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━"

foreach ($target in $Targets) {
    switch ($target) {
        "claude"   { Install-To $ClaudeSkills "Claude Code" }
        "opencode" { Install-To $OpenCodeSkills "OpenCode" }
    }
}

Verify-Install

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host "快速开始（直接复制到 Claude Code / OpenCode）：" -ForegroundColor Cyan
Write-Host ""
Write-Host "  检查结构 <Skill名>      ← 30 秒，先做这个热个身"
Write-Host "  测评 <Skill名>          ← 系统自动推荐工作流，不用选"
Write-Host ""
Write-Host "不知道 Skill 名？把 SKILL.md 放到："
Write-Host "  Claude Code：  ~\.claude\skills\<Skill名>\SKILL.md"
Write-Host "  OpenCode：     %APPDATA%\opencode\skills\<Skill名>\SKILL.md"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor White
Write-Host ""
