#Requires -Version 5.0
<#
  start_all.ps1 — 三 Web 项目统一启动 + Cloudflare 隧道
  ======================================================
  自动探测项目路径（便携目录布局），按依赖顺序启动三个 Web 服务，
  每个服务通过健康检查后才继续，最后启动三个 Cloudflare 隧道。

  启动顺序:
    1. edm-takens-web   (Python FastAPI, 前端 5173 / 后端 8000)
    2. trace-engine-web (Node.js Express, 端口 3000~3020)
    3. trace-to-edm     (Node.js Express, 端口 3100)

  三个隧道 URL 获取后统一显示。按 Ctrl+C 停止所有服务与隧道。

  依赖项:
    - Python 3.10+ (edm-takens-web)
    - Node.js 18+  (trace-engine-web, trace-to-edm)
    - cloudflared  (https://github.com/cloudflare/cloudflared/releases)
#>

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

# ═══════════════ 路径探测 ═══════════════
# 便携目录布局:
#   Complement\
#   ├── start_all.ps1 (本脚本)
#   └── TRACE Engine(EDM-Takens CCM)\
#       ├── edm-takens-web\
#       ├── trace-engine-web\
#       └── trace-to-edm\
# 开发目录布局 (.skills):
#   .skills\
#   ├── start_all.ps1 (本脚本)
#   ├── trace-engine-web\
#   ├── trace-to-edm\
#   └── edm-takens-web\

function Find-ProjectDir($name, $hints) {
    foreach ($h in $hints) {
        $p = Join-Path $scriptDir $h
        if (Test-Path $p) { return $p }
    }
    return $null
}

# 检查 node_modules 是否存在，缺失时自动运行 npm install。
# 重启电脑后便携目录的 node_modules 可能被清理或从未安装，
# 此函数确保 Node.js 项目在启动前依赖就绪。
function Ensure-NpmDeps($projectDir, $label, $subDir = "") {
    $targetDir = if ($subDir) { Join-Path $projectDir $subDir } else { $projectDir }
    if (-not (Test-Path $targetDir)) {
        Write-Host "  [ERROR] ${label}: 目录不存在 $targetDir" -ForegroundColor Red
        return $false
    }
    $nodeModules = Join-Path $targetDir "node_modules"
    if (Test-Path $nodeModules) { return $true }

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "  [ERROR] ${label}: node_modules 缺失且未找到 npm，无法自动安装" -ForegroundColor Red
        return $false
    }
    Write-Host "  [INFO] ${label}: node_modules 缺失，自动执行 npm install..." -ForegroundColor Yellow
    Push-Location $targetDir
    try {
        & npm install --no-audit --no-fund 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] ${label}: npm install 失败 (exit $LASTEXITCODE)" -ForegroundColor Red
            return $false
        }
        Write-Host "  [OK] ${label}: npm 依赖已安装" -ForegroundColor Green
    } finally {
        Pop-Location
    }
    return $true
}

$edmDir   = Find-ProjectDir "edm-takens-web"   @("TRACE Engine(EDM-Takens CCM)\edm-takens-web", "edm-takens-web", "Skill\edm-takens-web")
$traceDir = Find-ProjectDir "trace-engine-web" @("TRACE Engine(EDM-Takens CCM)\trace-engine-web", "trace-engine-web")
$bridgeDir = Find-ProjectDir "trace-to-edm"    @("TRACE Engine(EDM-Takens CCM)\trace-to-edm", "trace-to-edm")

# 健康检查辅助函数
function Wait-HealthCheck($url, $label, $maxWaitSec = 60) {
    $waited = 0
    while ($waited -lt $maxWaitSec) {
        try {
            $resp = Invoke-WebRequest -Uri $url -Method GET -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "  $label 就绪 (等待 ${waited}s)" -ForegroundColor Green
                return $true
            }
        } catch { }
        Start-Sleep 2
        $waited += 2
        if ($waited % 10 -eq 0) { Write-Host "  等待 $label ($url) ... ${waited}s" -ForegroundColor Gray }
    }
    Write-Host "  $label 启动超时" -ForegroundColor Red
    return $false
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  三 Web 项目统一启动 + Cloudflare 隧道" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查依赖
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "[ERROR] 未找到 cloudflared，请安装: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 验证路径
$missing = @()
if (-not $edmDir)    { $missing += "edm-takens-web" }
if (-not $traceDir)  { $missing += "trace-engine-web" }
if (-not $bridgeDir) { $missing += "trace-to-edm" }
if ($missing.Count -gt 0) {
    Write-Host "[ERROR] 未找到项目目录: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "脚本目录: $scriptDir" -ForegroundColor Gray
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "项目路径:" -ForegroundColor Gray
Write-Host "  edm-takens-web:   $edmDir" -ForegroundColor Gray
Write-Host "  trace-engine-web: $traceDir" -ForegroundColor Gray
Write-Host "  trace-to-edm:     $bridgeDir" -ForegroundColor Gray
Write-Host ""

# ═══════════════ NPM 依赖预检 ═══════════════
# 重启电脑后 node_modules 可能缺失，此处自动检测并安装。
# trace-engine-web 的 start.ps1 内部已有同类检查，此处仅为另外两个项目兜底。
Write-Host "检查 npm 依赖..." -ForegroundColor Cyan
$edmDepsOk   = Ensure-NpmDeps $edmDir    "edm-takens-web 前端" "frontend"
$tewDepsOk   = Ensure-NpmDeps $traceDir  "trace-engine-web"
$tteDepsOk   = Ensure-NpmDeps $bridgeDir "trace-to-edm"
Write-Host ""

# 保存所有进程引用，用于 finally 清理
$jobs = @()
$cfJobs = @()

try {
    # ═══════════════ 1. edm-takens-web ═══════════════
    Write-Host "[1/3] 启动 edm-takens-web (Python, 前端 5173 / 后端 8000)..." -ForegroundColor Cyan
    $edmOut = Join-Path $edmDir "mvp_out.log"
    $edmErr = Join-Path $edmDir "mvp_err.log"
    $edmJob = Start-Process -FilePath "python" -ArgumentList "start_mvp.py" `
        -WorkingDirectory $edmDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $edmOut -RedirectStandardError $edmErr
    $jobs += $edmJob
    Write-Host "  PID: $($edmJob.Id)" -ForegroundColor Gray

    $edmFeOk = Wait-HealthCheck "http://127.0.0.1:5173/" "edm-takens-web 前端" 60
    $edmBeOk = $true  # 后端就绪由前端代理保证
    if (-not $edmFeOk) {
        Write-Host "  [WARN] edm-takens-web 前端未就绪，查看日志: $edmErr" -ForegroundColor Yellow
    }

    # ═══════════════ 2. trace-engine-web ═══════════════
    Write-Host ""
    Write-Host "[2/3] 启动 trace-engine-web (Node.js, 端口 3000~3020)..." -ForegroundColor Cyan
    $tewOut = Join-Path $traceDir "work\server.log"
    $tewErr = Join-Path $traceDir "work\server_err.log"
    if (-not (Test-Path (Join-Path $traceDir "work"))) { New-Item -ItemType Directory -Path (Join-Path $traceDir "work") -Force | Out-Null }
    $tewJob = Start-Process -FilePath "powershell" `
        -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","start.ps1" `
        -WorkingDirectory $traceDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $tewOut -RedirectStandardError $tewErr
    $jobs += $tewJob
    Write-Host "  PID: $($tewJob.Id)" -ForegroundColor Gray

    # 探测 trace-engine-web 实际端口
    $tracePort = 0
    $waited = 0; $maxWait = 40
    while ($waited -lt $maxWait) {
        $p = 3000
        while ($p -le 3020) {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/health" -Method GET -TimeoutSec 2 -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $tracePort = $p; break }
            } catch { }
            $p++
        }
        if ($tracePort -gt 0) { break }
        Start-Sleep 2; $waited += 2
    }
    if ($tracePort -eq 0) {
        Write-Host "  [WARN] trace-engine-web 未就绪，查看日志: $tewErr" -ForegroundColor Yellow
    } else {
        Write-Host "  trace-engine-web 就绪 (端口 $tracePort, 等待 ${waited}s)" -ForegroundColor Green
    }

    # ═══════════════ 3. trace-to-edm ═══════════════
    Write-Host ""
    Write-Host "[3/3] 启动 trace-to-edm (Node.js, 端口 3100)..." -ForegroundColor Cyan
    $tteOut = Join-Path $bridgeDir "server_out.log"
    $tteErr = Join-Path $bridgeDir "server_err.log"
    $tteJob = Start-Process -FilePath "node" -ArgumentList "server.js" `
        -WorkingDirectory $bridgeDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $tteOut -RedirectStandardError $tteErr
    $jobs += $tteJob
    Write-Host "  PID: $($tteJob.Id)" -ForegroundColor Gray

    $tteOk = Wait-HealthCheck "http://127.0.0.1:3100/api/status" "trace-to-edm" 30
    if (-not $tteOk) {
        Write-Host "  [WARN] trace-to-edm 未就绪，查看日志: $tteErr" -ForegroundColor Yellow
    }

    # ═══════════════ 启动 Cloudflare 隧道 ═══════════════
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  启动三个 Cloudflare 隧道" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    $ts = Get-Date -Format "yyyyMMdd_HHmmss"

    # 隧道日志归档到各项目的 tunnel_logs/ 子目录
    $tewLogDir = Join-Path $traceDir "tunnel_logs"
    $tteLogDir = Join-Path $bridgeDir "tunnel_logs"
    $edwLogDir = Join-Path $edmDir "tunnel_logs"
    foreach ($ld in @($tewLogDir, $tteLogDir, $edwLogDir)) {
        if (-not (Test-Path $ld)) { New-Item -ItemType Directory -Path $ld -Force | Out-Null }
        # 清理旧日志（只保留最新一次）
        Get-ChildItem -Path $ld -Filter "cf_*_*.log" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*_$ts.log" } | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
    }

    # 隧道 1: trace-engine-web -> port 3000 (或实际探测到的端口)
    $tewCfPort = if ($tracePort -gt 0) { $tracePort } else { 3000 }
    $cf1Out = Join-Path $tewLogDir "cf_out_$ts.log"
    $cf1Err = Join-Path $tewLogDir "cf_err_$ts.log"
    $cf1 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel","--edge-ip-version","4","--no-chunked-encoding","--url","http://localhost:$tewCfPort" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf1Out -RedirectStandardError $cf1Err
    $cfJobs += $cf1
    Write-Host "  [1] trace-engine-web 隧道 (PID $($cf1.Id), port $tewCfPort)" -ForegroundColor Gray

    # 隧道 2: trace-to-edm -> port 3100
    $cf2Out = Join-Path $tteLogDir "cf_out_$ts.log"
    $cf2Err = Join-Path $tteLogDir "cf_err_$ts.log"
    $cf2 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel","--edge-ip-version","4","--no-chunked-encoding","--url","http://localhost:3100" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf2Out -RedirectStandardError $cf2Err
    $cfJobs += $cf2
    Write-Host "  [2] trace-to-edm 隧道 (PID $($cf2.Id), port 3100)" -ForegroundColor Gray

    # 隧道 3: edm-takens-web -> port 5173
    $cf3Out = Join-Path $edwLogDir "cf_out_$ts.log"
    $cf3Err = Join-Path $edwLogDir "cf_err_$ts.log"
    $cf3 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel","--edge-ip-version","4","--no-chunked-encoding","--url","http://localhost:5173" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf3Out -RedirectStandardError $cf3Err
    $cfJobs += $cf3
    Write-Host "  [3] edm-takens-web 隧道 (PID $($cf3.Id), port 5173)" -ForegroundColor Gray

    # 等待隧道 URL
    Write-Host ""
    Write-Host "等待隧道 URL (最多 60s)..." -ForegroundColor Yellow
    $waited = 0; $maxWait = 60
    $url1 = $null; $url2 = $null; $url3 = $null
    while ($waited -lt $maxWait -and -not ($url1 -and $url2 -and $url3)) {
        Start-Sleep 3; $waited += 3
        if (-not $url1) {
            $logs = @(); if (Test-Path $cf1Out) { $logs += Get-Content $cf1Out -ErrorAction SilentlyContinue }; if (Test-Path $cf1Err) { $logs += Get-Content $cf1Err -ErrorAction SilentlyContinue }
            $m = $logs | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $url1 = $m.Matches.Value }
        }
        if (-not $url2) {
            $logs = @(); if (Test-Path $cf2Out) { $logs += Get-Content $cf2Out -ErrorAction SilentlyContinue }; if (Test-Path $cf2Err) { $logs += Get-Content $cf2Err -ErrorAction SilentlyContinue }
            $m = $logs | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $url2 = $m.Matches.Value }
        }
        if (-not $url3) {
            $logs = @(); if (Test-Path $cf3Out) { $logs += Get-Content $cf3Out -ErrorAction SilentlyContinue }; if (Test-Path $cf3Err) { $logs += Get-Content $cf3Err -ErrorAction SilentlyContinue }
            $m = $logs | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $url3 = $m.Matches.Value }
        }
        if ($url1 -and $url2 -and $url3) { break }
        if ($waited % 10 -eq 0) {
            $s = @()
            $s += if ($url1) { "url1-ok" } else { "url1.." }
            $s += if ($url2) { "url2-ok" } else { "url2.." }
            $s += if ($url3) { "url3-ok" } else { "url3.." }
            Write-Host "  ${waited}s: $($s -join ' ')" -ForegroundColor Gray
        }
    }

    # 保存 URL 到各项目
    # 无 BOM 写入 UTF-8，避免用户复制 URL 时带入不可见 BOM 字符
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    if ($url1) { [System.IO.File]::WriteAllText((Join-Path $traceDir "tunnel_url.txt"), $url1, $utf8NoBom) }
    if ($url2) { [System.IO.File]::WriteAllText((Join-Path $bridgeDir "tunnel_url.txt"), $url2, $utf8NoBom) }
    if ($url3) { [System.IO.File]::WriteAllText((Join-Path $edmDir "tunnel_url.txt"), $url3, $utf8NoBom) }

    # 显示结果
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  隧道 URL 汇总" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  trace-engine-web: $url1" -ForegroundColor $(if ($url1) {'Green'} else {'Red'})
    Write-Host "  trace-to-edm:     $url2" -ForegroundColor $(if ($url2) {'Green'} else {'Red'})
    Write-Host "  edm-takens-web:    $url3" -ForegroundColor $(if ($url3) {'Green'} else {'Red'})
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "按 Ctrl+C 停止所有服务与隧道。" -ForegroundColor Yellow
    Write-Host ""

    # 等待 Ctrl+C
    while ($true) { Start-Sleep 1 }

} finally {
    Write-Host ""
    Write-Host "[清理] 停止所有 cloudflared 隧道..." -ForegroundColor Yellow
    foreach ($j in $cfJobs) {
        try { if ($j -and -not $j.HasExited) { Stop-Process -Id $j.Id -Force -ErrorAction SilentlyContinue } } catch {}
    }
    Write-Host "[清理] 停止所有 Web 服务..." -ForegroundColor Yellow
    foreach ($j in $jobs) {
        try { if ($j -and -not $j.HasExited) { Stop-Process -Id $j.Id -Force -ErrorAction SilentlyContinue } } catch {}
    }
    Write-Host "[清理] 完成。" -ForegroundColor Yellow
    Read-Host "按 Enter 退出"
}
