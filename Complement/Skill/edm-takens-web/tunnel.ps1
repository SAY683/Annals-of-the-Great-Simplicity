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

# Constraint #2: 使用相对路径，无硬编码绝对路径
# cloudflared 必须由用户自行加入 PATH（参见 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/）

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

# 1. 检查 cloudflared (Constraint #3: 预检查 + 官方安装链接)
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "[ERROR] 未找到 cloudflared。" -ForegroundColor Red
    Write-Host "请安装: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/"
    Write-Host "或下载二进制: https://github.com/cloudflare/cloudflared/releases"
    Write-Host "安装后请确保 cloudflared.exe 已加入系统 PATH。"
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
# Constraint #6: node_modules 缺失时自动 npm install，并清除 HTTP_PROXY/HTTPS_PROXY
$frontendDir = Join-Path $scriptDir "frontend"
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "[ERROR] 前端依赖缺失且未找到 npm，请安装 Node.js。" -ForegroundColor Red
        Read-Host "按 Enter 退出"
        exit 1
    }
    Write-Host "[WARN] frontend/node_modules 缺失，正在 npm install..." -ForegroundColor Yellow
    # 清除代理环境变量以避免 npm install 失败
    Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
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

# 3. 轮询 HTTP health check Vite 前端 (5173)，最多等待 40 秒
# P1-1: HTTP health check 替代 TCP 端口检测，确认服务真正就绪
$port = 5173
$backendPort = 8000
$waited = 0
$maxWait = 40
Write-Host "      轮询 HTTP health check 前端 $port + 后端 $backendPort (最多 $maxWait 秒)..." -ForegroundColor Gray
$frontendOk = $false
$backendOk = $false
while ($waited -lt $maxWait) {
    if (-not $frontendOk) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$port" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $frontendOk = $true }
        } catch { }
    }
    if (-not $backendOk) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$backendPort/api/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $backendOk = $true }
        } catch { }
    }
    if ($frontendOk -and $backendOk) { break }
    Start-Sleep 2
    $waited += 2
    if ($waited % 10 -eq 0) {
        $status = @()
        if ($frontendOk) { $status += "frontend✓" } else { $status += "frontend…" }
        if ($backendOk)  { $status += "backend✓" } else { $status += "backend…" }
        Write-Host "      已等待 ${waited}s: $($status -join ' ')" -ForegroundColor Gray
    }
}
if (-not $frontendOk) {
    Write-Host "[ERROR] Vite 前端端口 $port 在 ${maxWait}s 内未就绪。" -ForegroundColor Red
    if ($serverJob -and -not $serverJob.HasExited) { Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue }
    Read-Host "按 Enter 退出"
    exit 1
}
if (-not $backendOk) {
    Write-Host "[WARN] 后端 $backendPort 未就绪（前端可用，隧道继续）" -ForegroundColor Yellow
}
Write-Host "      前端 $port + 后端 $backendPort 就绪 ✓ (等待了 ${waited}s)" -ForegroundColor Green

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
    # P1-1/P2-fix: cloudflared 1033 fix —
    #   1. Remove --protocol http2 (forces HTTP/2 to local dev server → 1033)
    #   2. --edge-ip-version 4 avoids IPv6 TLS timeout chain (~15s → instant)
    #   3. --no-chunked-encoding improves local dev server compatibility
    $cfJob = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel", "--edge-ip-version", "4", "--no-chunked-encoding", "--url", "http://localhost:$port" `
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
