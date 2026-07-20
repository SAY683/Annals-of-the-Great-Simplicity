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

# Constraint #2: 使用相对路径，无硬编码绝对路径
# cloudflared 必须由用户自行加入 PATH（参见 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/）

# 使用脚本所在目录（相对路径，便携式兼容）
# $PSScriptRoot 在 PS 3.0+ 自动可用（包括 -File 调用）
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " trace-to-edm + Cloudflare Tunnel" -ForegroundColor Cyan
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

# 2. 检查 Node.js
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "[ERROR] 未找到 node，请确保 Node.js 已加入系统 PATH。" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 3. 检查 npm 依赖
# Constraint #6: node_modules 缺失时自动 npm install，并清除 HTTP_PROXY/HTTPS_PROXY
if (-not (Test-Path (Join-Path $scriptDir "node_modules"))) {
    Write-Host "[WARN] node_modules 缺失，正在 npm install..." -ForegroundColor Yellow
    # 清除代理环境变量以避免 npm install 失败
    Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
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

# 4. 轮询探测实际监听端口（最多等待 20 秒）
$port = 0
$maxPort = 3120
$waited = 0
$maxWait = 20
Write-Host "      轮询检测端口 3100~$maxPort (最多等待 $maxWait 秒)..." -ForegroundColor Gray
while ($waited -lt $maxWait) {
    $p = 3100
    while ($p -le $maxPort) {
        $inUse = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($inUse) { $port = $p; break }
        $p++
    }
    if ($port -gt 0) { break }
    Start-Sleep 2
    $waited += 2
    if ($waited % 10 -eq 0) { Write-Host "      已等待 $waited 秒..." -ForegroundColor Gray }
}
if ($port -eq 0) {
    Write-Host "[ERROR] 端口范围 3100~$maxPort 在 ${maxWait} 秒内均无监听，服务可能启动失败。" -ForegroundColor Red
    if ($serverJob -and -not $serverJob.HasExited) { Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue }
    Read-Host "按 Enter 退出"
    exit 1
}
Write-Host "      检测到服务监听端口: $port (等待了 $waited 秒)" -ForegroundColor Green

Write-Host ""
Write-Host "[2/2] 启动 Cloudflare 隧道到 :$port ..." -ForegroundColor Cyan
Write-Host "      按 Ctrl+C 关闭隧道，服务进程将自动清理。" -ForegroundColor Gray
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

    # 轮询等待隧道 URL 出现
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
    # 隧道关闭后清理服务进程
    if ($serverJob -and -not $serverJob.HasExited) {
        Write-Host "[清理] 关闭 trace-to-edm server (PID $($serverJob.Id.ToString()))..." -ForegroundColor Yellow
        Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue
    }
}

Read-Host "按 Enter 退出"
