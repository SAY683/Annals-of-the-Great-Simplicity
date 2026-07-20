#Requires -Version 5.0
<#
  start_all.ps1 — 五项目统一启动脚本 (P1-6)
  ============================================
  按依赖顺序启动三个 Web 服务，并在每个服务通过健康检查后才继续。

  启动顺序:
    1. edm-takens-web   (FastAPI, 端口 8000) — EDM 分析引擎
    2. trace-engine-web (Express, 端口 3000+) — 文本因果分析
    3. trace-to-edm     (Express, 端口 3100) — 三层桥接器

  停止:
    Ctrl+C 终止本脚本 → 自动按逆序停止所有服务。

  环境变量:
    $env:EDM_SKIP_SYNC_CHECK=1  跳过后端副本同步检查
    $env:EDM_PORT               edm-takens-web 端口 (默认 8000)
    $env:TRACE_PORT             trace-engine-web 端口 (默认 3000)
    $env:BRIDGE_PORT            trace-to-edm 端口 (默认 3100)

  依赖项:
    - Python 3.10+ (edm-takens-web)
    - Node.js 18+  (trace-engine-web, trace-to-edm)
    - pip install -r requirements.txt (各项目)
#>

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

$edmPort   = if ($env:EDM_PORT)   { [int]$env:EDM_PORT }   else { 8000 }
$tracePortStart = if ($env:TRACE_PORT) { [int]$env:TRACE_PORT } else { 3000 }
$bridgePort = if ($env:BRIDGE_PORT) { [int]$env:BRIDGE_PORT } else { 3100 }

# 健康检查辅助函数
function Wait-HealthCheck($url, $label, $maxWaitSec = 60) {
    $waited = 0
    Write-Host "  等待 $label ($url) 就绪 (最多 ${maxWaitSec}s)..." -ForegroundColor Gray
    while ($waited -lt $maxWaitSec) {
        try {
            $resp = Invoke-WebRequest -Uri $url -Method GET -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "  $label 就绪 ✓ (等待 ${waited}s)" -ForegroundColor Green
                return $true
            }
        } catch { }
        Start-Sleep 2
        $waited += 2
    }
    Write-Host "  $label 启动超时 ✗" -ForegroundColor Red
    return $false
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  五项目统一启动 (start_all.ps1)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "服务端口: edm-takens-web=$edmPort, trace-engine-web=$tracePortStart, trace-to-edm=$bridgePort" -ForegroundColor Gray
Write-Host ""

# ═══════════════ 1. edm-takens-web ═══════════════
Write-Host "[1/3] 启动 edm-takens-web (Python FastAPI, 端口 $edmPort)..." -ForegroundColor Cyan
$edmDir = Join-Path $scriptDir "edm-takens-web"
if (-not (Test-Path $edmDir)) {
    Write-Host "[ERROR] 目录不存在: $edmDir" -ForegroundColor Red
    exit 1
}
$edmJob = Start-Process -FilePath "python" `
    -ArgumentList "run_backend.py", "--port", $edmPort `
    -WorkingDirectory $edmDir -PassThru -WindowStyle Normal
if (-not (Wait-HealthCheck "http://127.0.0.1:$edmPort/api/health" "edm-takens-web")) {
    if (-not $edmJob.HasExited) { Stop-Process -Id $edmJob.Id -Force -ErrorAction SilentlyContinue }
    exit 1
}

# ═══════════════ 2. trace-engine-web ═══════════════
Write-Host ""
Write-Host "[2/3] 启动 trace-engine-web (Node.js Express, 端口 $tracePortStart~3020)..." -ForegroundColor Cyan
$traceDir = Join-Path $scriptDir "trace-engine-web"
if (-not (Test-Path $traceDir)) {
    Write-Host "[ERROR] 目录不存在: $traceDir" -ForegroundColor Red
    exit 1
}
$traceJob = Start-Process -FilePath "node" `
    -ArgumentList "server.js" `
    -WorkingDirectory $traceDir -PassThru -WindowStyle Normal

# 探测 trace-engine-web 的实际监听端口 (3000-3020)
$tracePort = 0
$waited = 0
$maxWait = 40
while ($waited -lt $maxWait) {
    $p = $tracePortStart
    while ($p -le ($tracePortStart + 20)) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { $tracePort = $p; break }
        } catch { }
        $p++
    }
    if ($tracePort -gt 0) { break }
    Start-Sleep 2
    $waited += 2
}
if ($tracePort -eq 0) {
    Write-Host "[ERROR] trace-engine-web 未能在 ${maxWait}s 内启动。" -ForegroundColor Red
    if (-not $traceJob.HasExited) { Stop-Process -Id $traceJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $edmJob.HasExited)   { Stop-Process -Id $edmJob.Id   -Force -ErrorAction SilentlyContinue }
    exit 1
}
Write-Host "  trace-engine-web 就绪 ✓ (端口 $tracePort, 等待 ${waited}s)" -ForegroundColor Green

# ═══════════════ 3. trace-to-edm ═══════════════
Write-Host ""
Write-Host "[3/3] 启动 trace-to-edm (Node.js Express, 端口 $bridgePort)..." -ForegroundColor Cyan
$bridgeDir = Join-Path $scriptDir "trace-to-edm"
if (-not (Test-Path $bridgeDir)) {
    Write-Host "[ERROR] 目录不存在: $bridgeDir" -ForegroundColor Red
    exit 1
}
$bridgeJob = Start-Process -FilePath "node" `
    -ArgumentList "server.js" `
    -WorkingDirectory $bridgeDir -PassThru -WindowStyle Normal
if (-not (Wait-HealthCheck "http://127.0.0.1:$bridgePort/api/health" "trace-to-edm")) {
    if (-not $bridgeJob.HasExited) { Stop-Process -Id $bridgeJob.Id -Force -ErrorAction SilentlyContinue }
    if (-not $traceJob.HasExited)  { Stop-Process -Id $traceJob.Id  -Force -ErrorAction SilentlyContinue }
    if (-not $edmJob.HasExited)    { Stop-Process -Id $edmJob.Id    -Force -ErrorAction SilentlyContinue }
    exit 1
}

# ═══════════════ 运行中 ═══════════════
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  三个服务全部就绪!" -ForegroundColor Green
Write-Host "  edm-takens-web:   http://localhost:$edmPort" -ForegroundColor Green
Write-Host "  trace-engine-web: http://localhost:$tracePort" -ForegroundColor Green
Write-Host "  trace-to-edm:     http://localhost:$bridgePort" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "按 Ctrl+C 停止所有服务。" -ForegroundColor Gray

# 等待 Ctrl+C
try {
    while ($true) { Start-Sleep 1 }
} finally {
    Write-Host ""
    Write-Host "[清理] 按逆序停止服务..." -ForegroundColor Yellow
    foreach ($job in @($bridgeJob, $traceJob, $edmJob)) {
        if ($job -and -not $job.HasExited) {
            Write-Host "  停止 PID $($job.Id)..." -ForegroundColor Gray
            Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "[清理] 完成。" -ForegroundColor Yellow
}
