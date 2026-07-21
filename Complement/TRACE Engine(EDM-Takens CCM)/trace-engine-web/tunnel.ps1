#Requires -Version 5.0
<#
  TRACE Engine Web + Cloudflare Tunnel (PowerShell 版)
  =====================================================
  使用方法:
    1. 在脚本所在目录双击运行
    2. 或在 PowerShell 中: ./启动隧道.ps1

  依赖项:
    - Node.js (>= 18)
    - cloudflared (https://github.com/cloudflare/cloudflared/releases)
#>

$ErrorActionPreference = "Stop"
# 仅在非 UTF-8 控制台时设置编码，避免与 cmd chcp 65001 重复编码导致中文重影
$currentOut = [Console]::OutputEncoding
if ($currentOut -isnot [System.Text.Encoding] -or $currentOut.WebName -ne 'utf-8') {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
}

# Constraint #2: 使用相对路径，无硬编码绝对路径
# cloudflared 必须由用户自行加入 PATH（参见 https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/）

# 使用脚本所在目录（相对路径，便携式兼容）
# $PSScriptRoot 在 PS 3.0+ 自动可用（包括 -File 调用）
$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " TRACE Engine Web + Cloudflare Tunnel" -ForegroundColor Cyan
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

Write-Host "[1/2] 启动 trace-engine-web (start.ps1, 端口 3000~3020)..." -ForegroundColor Cyan
# 服务在隐藏窗口中运行，输出重定向到日志文件，避免弹出多余窗口
$serverOut = Join-Path (Join-Path $scriptDir "work") "server.log"
$serverErr = Join-Path (Join-Path $scriptDir "work") "server_err.log"
if (-not (Test-Path (Join-Path $scriptDir "work"))) { New-Item -ItemType Directory -Path (Join-Path $scriptDir "work") -Force | Out-Null }
$serverJob = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "start.ps1" `
    -WorkingDirectory $scriptDir -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
Write-Host "      服务日志: $serverOut / $serverErr" -ForegroundColor Gray

# 4. 轮询探测实际监听端口（最多等待 40 秒）。
# P1-1: 改用 HTTP health check（Invoke-WebRequest）替代 Get-NetTCPConnection，
# 因为在非管理员 PowerShell 或受限网络配置中 Get-NetTCPConnection 可能不可用，
# 并且 TCP 端口监听不代表 HTTP 服务已就绪。
$port = 0
$maxPort = 3020
$waited = 0
$maxWait = 40
Write-Host "      轮询 HTTP health check 端口 3000~$maxPort (最多等待 $maxWait 秒)..." -ForegroundColor Gray
while ($waited -lt $maxWait) {
    $p = 3000
    while ($p -le $maxPort) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $port = $p; break }
        } catch {
            # silently skip — service not ready on this port yet
        }
        $p++
    }
    if ($port -gt 0) { break }
    Start-Sleep 2
    $waited += 2
    if ($waited % 10 -eq 0) { Write-Host "      已等待 $waited 秒..." -ForegroundColor Gray }
}
if ($port -eq 0) {
    Write-Host "[ERROR] 端口范围 3000~$maxPort 在 ${maxWait} 秒内均无监听，服务可能启动失败。" -ForegroundColor Red
    Write-Host "       --- 服务日志尾部 (server.log) ---" -ForegroundColor Gray
    if (Test-Path $serverOut) { Get-Content $serverOut -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray } }
    Write-Host "       --- 服务错误日志尾部 (server_err.log) ---" -ForegroundColor Gray
    if (Test-Path $serverErr) { Get-Content $serverErr -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" -ForegroundColor Red } }
    if ($serverJob -and -not $serverJob.HasExited) { Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue }
    Read-Host "按 Enter 退出"
    exit 1
}
Write-Host "      检测到服务监听端口: $port (等待了 $waited 秒)" -ForegroundColor Green

Write-Host ""
Write-Host "[2/2] 启动 Cloudflare 隧道到 :$port ..." -ForegroundColor Cyan
Write-Host "      按 Ctrl+C 关闭隧道，服务进程将自动清理。" -ForegroundColor Gray
Write-Host ""

$urlFile = Join-Path $scriptDir "tunnel_url.txt"
# 隧道日志归档到专用子目录，避免污染项目根目录
$logDir = Join-Path $scriptDir "tunnel_logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

# 使用时间戳命名日志文件，避免被其他 cloudflared 进程锁定
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$cfOut = Join-Path $logDir "cf_out_$timestamp.log"
$cfErr = Join-Path $logDir "cf_err_$timestamp.log"

# 重要：不清理其他 cloudflared 进程！
# 用户可能已经启动了其他隧道的 cloudflared（分开启动模式），
# 全局 Stop-Process 会误杀其他隧道的监听进程。
# 时间戳日志文件已避免文件锁定问题，无需清理。

# 清理 tunnel_logs 目录中的旧日志文件（只保留最新一次启动的日志）
$oldCfLogs = Get-ChildItem -Path $logDir -Filter "cf_*_*.log" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*_$timestamp.log" }
if ($oldCfLogs) {
    foreach ($old in $oldCfLogs) {
        Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
    }
    Write-Host "      [清理] 删除 $($oldCfLogs.Count) 个旧日志文件" -ForegroundColor DarkGray
}

Write-Host "      隧道日志目录: $logDir" -ForegroundColor Gray

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
        # 无 BOM 写入 UTF-8，避免用户复制 URL 时带入不可见 BOM 字符
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($urlFile, $tunnelUrl, $utf8NoBom)
        Write-Host "      隧道运行中。按 Ctrl+C 关闭。" -ForegroundColor Gray
        while (-not $cfJob.HasExited) {
            Start-Sleep 1
        }
        Write-Host "[WARN] cloudflared 进程已退出 (退出码: $($cfJob.ExitCode))" -ForegroundColor Yellow
        if (Test-Path $cfErr) {
            Write-Host "       --- cloudflared 日志尾部 ---" -ForegroundColor Gray
            Get-Content $cfErr -Tail 10 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
        }
    } else {
        Write-Host "[ERROR] 未能在 ${maxWait} 秒内建立隧道，请检查 $cfOut / $cfErr" -ForegroundColor Red
    }
} catch {
    Write-Host ""
    Write-Host "[ERROR] 脚本执行失败: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
} finally {
    try {
        if ($cfJob -and -not $cfJob.HasExited) {
            Write-Host "[清理] 关闭 Cloudflare 隧道 (PID $($cfJob.Id.ToString()))..." -ForegroundColor Yellow
            Stop-Process -Id $cfJob.Id -Force -ErrorAction SilentlyContinue
        }
    } catch { }
    try {
        if ($serverJob -and -not $serverJob.HasExited) {
            Write-Host "[清理] 关闭 trace-engine-web 服务 (PID $($serverJob.Id.ToString()))..." -ForegroundColor Yellow
            Stop-Process -Id $serverJob.Id -Force -ErrorAction SilentlyContinue
        }
    } catch { }
    Read-Host "按 Enter 退出"
}
