#Requires -Version 5.0
<#
  EDM-Takens Web + Cloudflare Tunnel (PowerShell 版)
  ==================================================
  使用方法:
    1. 在脚本所在目录双击运行
    2. 或在 PowerShell 中: ./启动隧道.ps1

  依赖项:
    - Python (>= 3.10)
    - cloudflared (https://github.com/cloudflare/cloudflared/releases)
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 加入 cloudflared 默认安装路径
$env:Path += ";C:\Program Files (x86)\cloudflared"

# 使用脚本所在目录（相对路径，便携式兼容）
# $PSScriptRoot 在 PS 3.0+ 自动可用（包括 -File 调用）
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " EDM-Takens Web + Cloudflare Tunnel" -ForegroundColor Cyan
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

# 2. 检查 Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "[ERROR] 未找到 python，请确保 Python 已加入系统 PATH。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 3. 检查前端 npm 依赖（start_mvp.py 会启动 Vite 开发服务器）
$frontendDir = Join-Path $scriptDir "frontend"
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "[ERROR] 前端依赖缺失且未找到 npm，请安装 Node.js。" -ForegroundColor Red
        Read-Host "按 Enter 退出"
        exit 1
    }
    Write-Host "[WARN] frontend/node_modules 缺失，正在 npm install..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] npm install 失败。" -ForegroundColor Red
        Pop-Location
        Read-Host "按 Enter 退出"
        exit 1
    }
    Pop-Location
}

Write-Host "[1/2] 启动 EDM-Takens 后端 (backend:8000, frontend:5173)..." -ForegroundColor Cyan
$serverJob = Start-Process -FilePath "python" -ArgumentList "start_mvp.py" `
    -WorkingDirectory $scriptDir -PassThru -WindowStyle Normal

# 3. 轮询检查前端是否监听 5173（最多等待 30 秒）
$port = 5173
$waited = 0
$maxWait = 30
Write-Host "      轮询检测端口 $port (最多等待 $maxWait 秒)..." -ForegroundColor Gray
$inUse = $null
while ($waited -lt $maxWait) {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) { break }
    Start-Sleep 2
    $waited += 2
    if ($waited % 10 -eq 0) { Write-Host "      已等待 $waited 秒..." -ForegroundColor Gray }
}
if (-not $inUse) {
    Write-Host "[ERROR] 端口 $port 在 ${maxWait} 秒内无监听，后端可能启动失败。" -ForegroundColor Red
    Write-Host "       请检查 start_mvp.py 输出和日志。" -ForegroundColor Gray
    if ($serverJob -and -not $serverJob.HasExited) { Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue }
    Read-Host "按 Enter 退出"
    exit 1
}
Write-Host "      检测到前端监听端口: $port (等待了 $waited 秒)" -ForegroundColor Green

Write-Host ""
Write-Host "[2/2] 启动 Cloudflare 隧道到 :$port ..." -ForegroundColor Cyan
Write-Host "      按 Ctrl+C 关闭隧道，服务进程将自动清理。" -ForegroundColor Gray
Write-Host ""

$urlFile = Join-Path $scriptDir "tunnel_url.txt"
$cfOut = Join-Path $scriptDir "tunnel_cloudflared_out.log"
$cfErr = Join-Path $scriptDir "tunnel_cloudflared_err.log"
if (Test-Path $cfOut) { Remove-Item $cfOut -Force -ErrorAction SilentlyContinue }
if (Test-Path $cfErr) { Remove-Item $cfErr -Force -ErrorAction SilentlyContinue }

Write-Host "      隧道日志: $cfOut / $cfErr" -ForegroundColor Gray

$cfJob = $null
try {
    $cfJob = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel", "--protocol", "http2", "--url", "http://localhost:$port" `
        -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $cfOut -RedirectStandardError $cfErr

    $tunnelUrl = $null
    $maxWait = 60
    $waited = 0
    while ($waited -lt $maxWait -and -not $tunnelUrl) {
        Start-Sleep 2
        $waited += 2
        $allLogs = @()
        if (Test-Path $cfOut) { $allLogs += Get-Content $cfOut -ErrorAction SilentlyContinue }
        if (Test-Path $cfErr) { $allLogs += Get-Content $cfErr -ErrorAction SilentlyContinue }
        if ($allLogs) {
            $tunnelUrl = $allLogs | `
                Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | `
                Select-Object -First 1 | ForEach-Object { $_.Matches.Value }
        }
        if ($waited % 10 -eq 0 -and -not $tunnelUrl) {
            Write-Host "      已等待 $waited 秒，仍在建立隧道..." -ForegroundColor Gray
        }
    }

    if ($tunnelUrl) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  隧道 URL: $tunnelUrl" -ForegroundColor Green
        Write-Host "  本地端口: $port" -ForegroundColor Green
        Write-Host "  已保存至: $urlFile" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        $tunnelUrl | Out-File -FilePath $urlFile -Encoding UTF8 -Force
        Write-Host "      隧道运行中。按 Ctrl+C 关闭。" -ForegroundColor Gray
        while (-not $cfJob.HasExited) {
            Start-Sleep 1
        }
    } else {
        Write-Host "[ERROR] 未能在 ${maxWait} 秒内建立隧道，请检查 $cfOut / $cfErr" -ForegroundColor Red
    }
} finally {
    if ($cfJob -and -not $cfJob.HasExited) {
        Write-Host "[清理] 关闭 Cloudflare 隧道 (PID $($cfJob.Id.ToString()))..." -ForegroundColor Yellow
        Stop-Process -Id $cfJob.Id -Force -ErrorAction SilentlyContinue
    }
    if ($serverJob -and -not $serverJob.HasExited) {
        Write-Host "[清理] 关闭 EDM-Takens 后端 (PID $($serverJob.Id.ToString()))..." -ForegroundColor Yellow
        Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue
    }
}

Read-Host "按 Enter 退出"
