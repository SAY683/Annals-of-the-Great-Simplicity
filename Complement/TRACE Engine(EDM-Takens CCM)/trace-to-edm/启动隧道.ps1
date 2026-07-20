#Requires -Version 5.0
<#
  trace-to-edm + Cloudflare Tunnel (PowerShell 版)
  ================================================
  使用方法:
    1. 在脚本所在目录双击运行
    2. 或在 PowerShell 中: ./启动隧道.ps1

  依赖项:
    - Node.js (>= 18)
    - cloudflared (https://github.com/cloudflare/cloudflared/releases)
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 加入 cloudflared 默认安装路径
$env:Path += ";C:\Program Files (x86)\cloudflared"

# 使用脚本所在目录（相对路径，便携式兼容）
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " trace-to-edm + Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 cloudflared
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "[ERROR] 未找到 cloudflared。" -ForegroundColor Red
    Write-Host "请安装: https://github.com/cloudflare/cloudflared/releases"
    Write-Host "或将其加入 PATH 或 C:\Program Files (x86)\cloudflared\"
    Read-Host "按 Enter 退出"
    exit 1
}

# 2. 检查 Node.js
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "[ERROR] 未找到 node，请确保 Node.js 已加入系统 PATH。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 3. 检查 npm 依赖
if (-not (Test-Path (Join-Path $scriptDir "node_modules"))) {
    Write-Host "[WARN] node_modules 缺失，正在 npm install..." -ForegroundColor Yellow
    Push-Location $scriptDir
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] npm install 失败。" -ForegroundColor Red
        Pop-Location
        Read-Host "按 Enter 退出"
        exit 1
    }
    Pop-Location
}

Write-Host "[1/2] 启动 trace-to-edm server (端口 3100)..." -ForegroundColor Cyan
$serverJob = Start-Process -FilePath "node" -ArgumentList "server.js" `
    -WorkingDirectory $scriptDir -PassThru -WindowStyle Normal
Write-Host "      等待 5 秒让服务就绪..." -ForegroundColor Gray
Start-Sleep 5

# 4. 探测实际监听端口
$port = 3100
$maxPort = 3120
while ($port -le $maxPort) {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) { break }
    $port++
}
if ($port -gt $maxPort) {
    Write-Host "[ERROR] 端口范围 3100~3120 均无监听，服务可能启动失败。" -ForegroundColor Red
    if ($serverJob -and -not $serverJob.HasExited) { Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue }
    Read-Host "按 Enter 退出"
    exit 1
}
Write-Host "      检测到服务监听端口: $port" -ForegroundColor Green

Write-Host ""
Write-Host "[2/2] 启动 Cloudflare 隧道到 :$port ..." -ForegroundColor Cyan
Write-Host "      按 Ctrl+C 关闭隧道，服务进程将自动清理。" -ForegroundColor Gray
Write-Host ""

try {
    # P1-1/P2-fix: cloudflared 1033 fix —
    #   --edge-ip-version 4 avoids IPv6 TLS timeout chain (~15s → instant)
    #   --no-chunked-encoding improves local dev server compatibility
    #   No --protocol http2 (default auto negotiates best protocol)
    & cloudflared tunnel --edge-ip-version 4 --no-chunked-encoding --url "http://localhost:$port"
} finally {
    # 隧道关闭后清理服务进程
    if ($serverJob -and -not $serverJob.HasExited) {
        Write-Host "[清理] 关闭 trace-to-edm server (PID $($serverJob.Id))..." -ForegroundColor Yellow
        Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue
    }
}

Read-Host "按 Enter 退出"
