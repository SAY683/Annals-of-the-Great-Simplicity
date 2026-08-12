#Requires -Version 5.0
<#
  selfcheck-query.ps1 - Self-test: run a global search against the portable index.
  Requires: embedding service (00-start-embedding) + LLM provider (DeepSeek official API or CC Switch proxy).
#>
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$archiveRoot = Split-Path -Parent $scriptDir
$project = Join-Path $archiveRoot "project"

if (-not (Test-Path -LiteralPath "$project\output")) {
    Write-Host "[ERROR] 项目尚无索引：$project\output（先运行 03-rebuild-index.bat）" -ForegroundColor Red
    exit 1
}

$Python = Assert-GraphRagPython
$graphragCli = Get-GraphRagCli -Python $Python
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host "[GraphRAG] 自检：Global Search 查询 '什么是爱？'" -ForegroundColor Cyan
Write-Host "  project : $project"
Write-Host "  cli     : $graphragCli"
& $graphragCli query --root $project --method global "什么是爱？"
Write-Host ""
Write-Host "[完成] 若上方出现结构化回答，则索引与链路正常。" -ForegroundColor Green
