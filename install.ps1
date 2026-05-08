# SkillSentry v7.0 安装脚本 (Windows PowerShell)
# 用法: cd SkillSentry; .\install.ps1

$ErrorActionPreference = "Stop"
$RepoDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToolsDir = Join-Path $RepoDir "tools"

$ClaudeSkills  = Join-Path $env:USERPROFILE ".claude\skills"
$OpenCodeSkills = Join-Path $env:USERPROFILE ".config\opencode\skills"

# v7.0 活跃子工具
$Tools = @("sentry-check","sentry-cases","sentry-executor","sentry-grader","sentry-report")

# v7.0 归档 stub
$Archived = @("sentry-openclaw","sentry-sync","sentry-lint","sentry-trigger")

function Install-To($SkillsDir, $Platform) {
    Write-Host "`n📦 安装到 $Platform ($SkillsDir)"

    $dest = Join-Path $SkillsDir "SkillSentry"
    if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }

    # 复制主体（排除 tools/sessions/.git）
    Get-ChildItem $RepoDir -Exclude "tools","sessions",".git" | Copy-Item -Destination $dest -Recurse -Force
    Write-Host "  ✅ SkillSentry（主编排 v7.0）"

    # 活跃子工具
    foreach ($tool in $Tools) {
        $src = Join-Path $ToolsDir "$tool\SKILL.md"
        if (Test-Path $src) {
            $toolDest = Join-Path $SkillsDir $tool
            if (-not (Test-Path $toolDest)) { New-Item -ItemType Directory -Path $toolDest -Force | Out-Null }
            Copy-Item $src -Destination (Join-Path $toolDest "SKILL.md") -Force
            Write-Host "  ✅ $tool"
        }
    }

    # 归档 stub
    foreach ($tool in $Archived) {
        $src = Join-Path $ToolsDir "$tool\SKILL.md"
        if (Test-Path $src) {
            $toolDest = Join-Path $SkillsDir $tool
            if (-not (Test-Path $toolDest)) { New-Item -ItemType Directory -Path $toolDest -Force | Out-Null }
            Copy-Item $src -Destination (Join-Path $toolDest "SKILL.md") -Force
            Write-Host "  📦 $tool（归档 stub）"
        }
    }
}

Write-Host "🛡  SkillSentry v7.0 安装脚本"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

$installed = $false
if (Test-Path (Join-Path $env:USERPROFILE ".claude")) {
    Install-To $ClaudeSkills "Claude Code"
    $installed = $true
}
if (Test-Path (Join-Path $env:USERPROFILE ".config\opencode")) {
    Install-To $OpenCodeSkills "OpenCode"
    $installed = $true
}
if (-not $installed) {
    Write-Host "⚠️  未检测到 Claude Code 或 OpenCode，默认安装到 Claude Code"
    Install-To $ClaudeSkills "Claude Code"
}

# 验证
Write-Host "`n🔍 验证安装..."
foreach ($SkillsDir in @($ClaudeSkills, $OpenCodeSkills)) {
    if (Test-Path (Join-Path $SkillsDir "SkillSentry")) {
        Write-Host "  📂 $SkillsDir"
        foreach ($tool in (@("SkillSentry") + $Tools)) {
            $f = Join-Path $SkillsDir "$tool\SKILL.md"
            if (Test-Path $f) { Write-Host "    ✅ $tool" }
            else { Write-Host "    ❌ $tool（缺失）" }
        }
    }
}

Write-Host "`n🎉 安装完成！"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host "快速开始："
Write-Host "  测评 <Skill名>     ← 自动推荐工作流"
Write-Host "  lint <Skill名>     ← 30秒静态检查"
Write-Host "  check <Skill名>    ← 静态检查 + 触发率"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
