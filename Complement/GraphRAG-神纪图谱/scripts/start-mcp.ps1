#Requires -Version 5.0
<#
  start-mcp.ps1 - Start the portable GraphRAG MCP server.
  The MCP server talks stdio; keep this window open while the host (Codex/Claude/Cursor) connects.
  Configurable via env: GRAPHRAG_PYTHON
#>
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$archiveRoot = Split-Path -Parent $scriptDir
$project = Join-Path $archiveRoot "project"
$mcpPy = Join-Path $archiveRoot "mcp\graphrag_mcp.py"

if (-not (Test-Path -LiteralPath $mcpPy)) {
    Write-Host "[ERROR] 找不到 MCP 脚本：$mcpPy" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $project)) {
    Write-Host "[ERROR] 找不到项目目录：$project" -ForegroundColor Red
    exit 1
}

$Python = Assert-GraphRagPython -ExtraModule "mcp"

Write-Host "[GraphRAG] 启动 MCP 服务器 ..." -ForegroundColor Cyan
Write-Host "  python  : $Python"
Write-Host "  project : $project"
Write-Host "  保持此窗口开启。宿主程序将通过 stdio 连接。" -ForegroundColor Yellow

$env:GRAPHRAG_PROJECT = $project
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& $Python $mcpPy
