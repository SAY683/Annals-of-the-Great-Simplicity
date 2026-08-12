#Requires -Version 5.0
<#
  rebuild-index.ps1 - Rebuild the GraphRAG index from input.
  Prerequisites (all must be running):
    1. embedding service  -> 00-start-embedding.bat (port 8081)
    2. LLM provider       -> DeepSeek official API (api.deepseek.com), or local CC Switch proxy 15721
  This re-runs entity extraction, summarization, community reports and embeddings.
  NOTE: cache/ folder is NOT shipped; first rebuild after a fresh copy will re-call the LLM.
#>
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\common.ps1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$archiveRoot = Split-Path -Parent $scriptDir
$project = Join-Path $archiveRoot "project"

$Python = Assert-GraphRagPython
$graphragCli = Get-GraphRagCli -Python $Python
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host "[GraphRAG] 重建索引 ..." -ForegroundColor Cyan
Write-Host "  project : $project"
Write-Host "  cli     : $graphragCli"

# ---- pre-flight checks ----
$embedPort = if ($env:EMBED_PORT) { [int]$env:EMBED_PORT } else { 8081 }
$llmPort   = 15721
$settingsFile = Join-Path $project "settings.yaml"
$settingsText = if (Test-Path -LiteralPath $settingsFile) { Get-Content -Raw -Encoding UTF8 $settingsFile } else { "" }
$usesLocalProxy = $settingsText -match "api_base:\s*http://127\.0\.0\.1:15721"
$usesOfficialApi = $settingsText -match "api_base:\s*https://api\.deepseek\.com"
$missing = @()
if (-not (Get-NetTCPConnection -State Listen -LocalPort $embedPort -ErrorAction SilentlyContinue)) {
    $missing += "embedding 服务 (端口 $embedPort) —— 请先运行 00-start-embedding.bat"
}
if ($usesLocalProxy -and -not (Get-NetTCPConnection -State Listen -LocalPort $llmPort -ErrorAction SilentlyContinue)) {
    $missing += "LLM 代理 (端口 $llmPort, CC Switch) —— 请先启动 CC Switch"
}
if ($usesOfficialApi) {
    Write-Host "[OK] LLM 使用官方 DeepSeek (api.deepseek.com)，无需本地 LLM 端口。" -ForegroundColor Green
}
if ($missing.Count -gt 0) {
    Write-Host "[WARN] 以下依赖未就绪，重建可能失败：" -ForegroundColor Yellow
    foreach ($m in $missing) { Write-Host "   - $m" -ForegroundColor Yellow }
    Write-Host "  继续尝试？(Ctrl+C 取消；Enter 继续)" -ForegroundColor Yellow
    Read-Host | Out-Null
}

& $graphragCli index --root $project
Write-Host "[完成] 索引重建结束。" -ForegroundColor Green
