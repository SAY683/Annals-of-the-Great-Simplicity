#Requires -Version 5.0
<#
  start_all.ps1 - three-web-project launcher
  Default: local-only (127.0.0.1). No Cloudflare tunnel is started.
  Tunnel mode: .\start_all.ps1 -EnableTunnel  or  .\start_all.bat tunnel
  Tunnel mode starts local token gates (shared/tunnel_gate.js) on 3300/3301/3302
  and points cloudflared at the gates. The public URL alone is not authentication.
#>
param(
    [switch]$EnableTunnel,
    [string]$TunnelAccessToken = $env:TUNNEL_ACCESS_TOKEN,
    [switch]$AllowMissingDeps,
    [switch]$NoPause
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
Set-Location $scriptDir

. (Join-Path $scriptDir 'shared\python_env.ps1')

function Find-ProjectDir($name, $hints) {
    foreach ($h in $hints) {
        $p = Join-Path $scriptDir $h
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Ensure-NpmDeps($projectDir, $label, $subDir = "") {
    $targetDir = if ($subDir) { Join-Path $projectDir $subDir } else { $projectDir }
    if (-not (Test-Path -LiteralPath $targetDir)) {
        Write-Host "  [ERROR] ${label}: directory not found: $targetDir" -ForegroundColor Red
        return $false
    }
    $nodeModules = Join-Path $targetDir "node_modules"
    if (Test-Path -LiteralPath $nodeModules) { return $true }
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "  [ERROR] ${label}: node_modules missing and npm not found" -ForegroundColor Red
        return $false
    }
    Write-Host "  [INFO] ${label}: node_modules missing, installing..." -ForegroundColor Yellow
    Push-Location $targetDir
    try {
        $lock = Join-Path $targetDir "package-lock.json"
        if (Test-Path -LiteralPath $lock) { & npm ci --no-audit --no-fund 2>&1 | Out-Host }
        else { & npm install --no-audit --no-fund 2>&1 | Out-Host }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [ERROR] ${label}: npm install failed (exit $LASTEXITCODE)" -ForegroundColor Red
            return $false
        }
        Write-Host "  [OK] ${label}: npm dependencies installed" -ForegroundColor Green
    } finally { Pop-Location }
    return $true
}

function Wait-HealthCheck($url, $label, $maxWaitSec = 60) {
    $waited = 0
    while ($waited -lt $maxWaitSec) {
        try {
            $resp = Invoke-WebRequest -Uri $url -Method GET -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "  $label ready (${waited}s)" -ForegroundColor Green
                return $true
            }
        } catch { }
        Start-Sleep 2
        $waited += 2
        if ($waited % 10 -eq 0) { Write-Host "  waiting for $label ($url) ... ${waited}s" -ForegroundColor Gray }
    }
    Write-Host "  $label startup timeout" -ForegroundColor Red
    return $false
}

function Test-PortListening($port) {
    try {
        return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Stop-ProcessTree($id) {
    if (-not $id) { return }
    try { & taskkill /PID $id /T /F 2>$null | Out-Null } catch { }
}

function Start-Gate($target, $port, $label) {
    $gateScript = Join-Path $scriptDir 'shared\start_tunnel_gate.ps1'
    $logDir = Join-Path $scriptDir 'tunnel_logs'
    [IO.Directory]::CreateDirectory($logDir) | Out-Null
    $out = Join-Path $logDir "gate_${port}_out.log"
    $err = Join-Path $logDir "gate_${port}_err.log"
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$gateScript`" -Target `"$target`" -Port $port -Token `"$TunnelAccessToken`""
    $p = Start-Process -FilePath "powershell" -ArgumentList $args -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err
    Write-Host "  [gate] $label -> $target (127.0.0.1:$port, PID $($p.Id))" -ForegroundColor Gray
    return $p
}

$edmDir = Find-ProjectDir "edm-takens-web" @("TRACE Engine(EDM-Takens CCM)\edm-takens-web", "edm-takens-web", "Skill\edm-takens-web")
$traceDir = Find-ProjectDir "trace-engine-web" @("TRACE Engine(EDM-Takens CCM)\trace-engine-web", "trace-engine-web")
$bridgeDir = Find-ProjectDir "trace-to-edm" @("TRACE Engine(EDM-Takens CCM)\trace-to-edm", "trace-to-edm")

$missing = @()
if (-not $edmDir) { $missing += "edm-takens-web" }
if (-not $traceDir) { $missing += "trace-engine-web" }
if (-not $bridgeDir) { $missing += "trace-to-edm" }
if ($missing.Count -gt 0) {
    Write-Host "[ERROR] missing project directories: $($missing -join ', ')" -ForegroundColor Red
    Write-Host "script dir: $scriptDir" -ForegroundColor Gray
    if (-not $NoPause) { Read-Host "Press Enter to exit" }
    exit 1
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Complement Web Launcher (local-first)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  tunnel mode: $(if ($EnableTunnel) { 'ON' } else { 'OFF (default)' })" -ForegroundColor $(if ($EnableTunnel) { 'Yellow' } else { 'Green' })
Write-Host ""

Write-Host "Checking Python environment..." -ForegroundColor Cyan
$traceRequired = @('numpy','pandas','scipy','sklearn','jieba','dowhy','causallearn')
$edmRequired = @('numpy','pandas','scipy','sklearn','fastapi','uvicorn')
$tracePy = Resolve-ComplementPython -Required $traceRequired
$edmPy = Resolve-ComplementPython -Required $edmRequired
if (-not $tracePy -or -not $tracePy.Ok) {
    Write-ComplementPythonHint $tracePy
    if (-not $AllowMissingDeps) { if (-not $NoPause) { Read-Host "Press Enter to exit" }; exit 1 }
    Write-Host "  [WARN] continuing with missing TRACE dependencies (-AllowMissingDeps)" -ForegroundColor Yellow
}
if (-not $edmPy -or -not $edmPy.Ok) {
    Write-ComplementPythonHint $edmPy
    if (-not $AllowMissingDeps) { if (-not $NoPause) { Read-Host "Press Enter to exit" }; exit 1 }
    Write-Host "  [WARN] continuing with missing EDM dependencies (-AllowMissingDeps)" -ForegroundColor Yellow
}
if ($tracePy) {
    $env:TRACE_PYTHON_CMD = $tracePy.Path
    Write-Host "  TRACE Python: $($tracePy.Path) ($($tracePy.Version))" -ForegroundColor Gray
}
if ($edmPy) {
    $env:EDM_PYTHON_CMD = $edmPy.Path
    Write-Host "  EDM   Python: $($edmPy.Path) ($($edmPy.Version))" -ForegroundColor Gray
    if (-not $edmPy.Modules.pyEDM) {
        Write-Host "  [WARN] pyEDM not found; EDM will fall back to NumPy (lower fidelity)." -ForegroundColor Yellow
    }
}
Write-Host ""

Write-Host "Checking npm dependencies..." -ForegroundColor Cyan
$edmDepsOk = Ensure-NpmDeps $edmDir "edm-takens-web frontend" "frontend"
$tewDepsOk = Ensure-NpmDeps $traceDir "trace-engine-web"
$tteDepsOk = Ensure-NpmDeps $bridgeDir "trace-to-edm"
Write-Host ""
if (-not ($edmDepsOk -and $tewDepsOk -and $tteDepsOk)) {
    Write-Host "[ERROR] Node dependencies are incomplete; fix npm errors above before starting." -ForegroundColor Red
    if (-not $NoPause) { Read-Host "Press Enter to exit" }
    exit 1
}
$busyPorts = @(8000, 5173, 3100) | Where-Object { Test-PortListening $_ }
if ($busyPorts.Count -gt 0) {
    Write-Host "[ERROR] required port(s) already listening: $($busyPorts -join ', ')" -ForegroundColor Red
    Write-Host "Stop the existing instance first (or choose a different launcher)." -ForegroundColor Gray
    if (-not $NoPause) { Read-Host "Press Enter to exit" }
    exit 1
}
Write-Host ""

$jobs = @()
$cfJobs = @()

try {    # 1. edm-takens-web
    Write-Host "[1/3] edm-takens-web (FastAPI :8000 / Vite :5173)..." -ForegroundColor Cyan
    $edmWorkDir = Join-Path $edmDir "work"
    [IO.Directory]::CreateDirectory($edmWorkDir) | Out-Null
    $edmOut = Join-Path $edmWorkDir "mvp_out.log"
    $edmErr = Join-Path $edmWorkDir "mvp_err.log"
    $env:JOBS_DB = Join-Path $edmWorkDir "jobs.sqlite"
    $edmExe = if ($edmPy) { $edmPy.Path } else { "python" }
    $edmJob = Start-Process -FilePath $edmExe -ArgumentList "start_mvp.py" `
        -WorkingDirectory $edmDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $edmOut -RedirectStandardError $edmErr
    $jobs += $edmJob
    Write-Host "  PID: $($edmJob.Id)" -ForegroundColor Gray
    $edmBeOk = Wait-HealthCheck "http://127.0.0.1:8000/api/health" "edm-takens-web backend" 90
    $edmFeOk = Wait-HealthCheck "http://127.0.0.1:5173/" "edm-takens-web frontend" 90
    if (-not $edmBeOk -or -not $edmFeOk) {
        throw "edm-takens-web did not become healthy; see $edmErr"
    }

    # 2. trace-engine-web
    Write-Host ""
    Write-Host "[2/3] trace-engine-web (Express :3000-3020)..." -ForegroundColor Cyan
    $tewOut = Join-Path $traceDir "work\server.log"
    $tewErr = Join-Path $traceDir "work\server_err.log"
    [IO.Directory]::CreateDirectory((Join-Path $traceDir "work")) | Out-Null
    $traceStart = Join-Path $traceDir "start.ps1"
    $tewArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$traceStart`""
    $tewJob = Start-Process -FilePath "powershell" -ArgumentList $tewArgs `
        -WorkingDirectory $traceDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $tewOut -RedirectStandardError $tewErr
    $jobs += $tewJob
    Write-Host "  PID: $($tewJob.Id)" -ForegroundColor Gray
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
        throw "trace-engine-web did not become healthy; see $tewErr"
    }
    Write-Host "  trace-engine-web ready on :$tracePort (${waited}s)" -ForegroundColor Green

    # 3. trace-to-edm
    Write-Host ""
    Write-Host "[3/3] trace-to-edm (Express :3100)..." -ForegroundColor Cyan
    $bridgeWorkDir = Join-Path $bridgeDir "work"
    [IO.Directory]::CreateDirectory($bridgeWorkDir) | Out-Null
    $tteOut = Join-Path $bridgeWorkDir "server_out.log"
    $tteErr = Join-Path $bridgeWorkDir "server_err.log"
    $tteJob = Start-Process -FilePath "node" -ArgumentList "server.js" `
        -WorkingDirectory $bridgeDir -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $tteOut -RedirectStandardError $tteErr
    $jobs += $tteJob
    Write-Host "  PID: $($tteJob.Id)" -ForegroundColor Gray
    $bridgePort = 0
    $waited = 0; $maxWait = 30
    while ($waited -lt $maxWait) {
        for ($p = 3100; $p -le 3120; $p++) {
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/api/status" -Method GET -TimeoutSec 2 -ErrorAction Stop
                if ($resp.StatusCode -eq 200) { $bridgePort = $p; break }
            } catch { }
        }
        if ($bridgePort -gt 0) { break }
        Start-Sleep 2; $waited += 2
    }
    if ($bridgePort -eq 0) {
        throw "trace-to-edm did not become healthy; see $tteErr"
    }
    Write-Host "  trace-to-edm ready on :$bridgePort (${waited}s)" -ForegroundColor Green

    # Local-only mode
    if (-not $EnableTunnel) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  Local services ready (no tunnel)" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  trace-engine-web: http://127.0.0.1:$tracePort" -ForegroundColor Gray
        Write-Host "  trace-to-edm:     http://127.0.0.1:$bridgePort" -ForegroundColor Gray
        Write-Host "  edm-takens-web:   http://127.0.0.1:5173" -ForegroundColor Gray
        Write-Host ""
        Write-Host "Press Ctrl+C to stop. Use -EnableTunnel for a protected public tunnel." -ForegroundColor Yellow
        while ($true) { Start-Sleep 1 }
    }
    # Tunnel mode
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) {
        Write-Host "[ERROR] cloudflared not found. Install: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Red
        if (-not $NoPause) { Read-Host "Press Enter to exit" }
        exit 1
    }
    if (-not $TunnelAccessToken) {
        $TunnelAccessToken = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
    }
    if ($TunnelAccessToken.Length -lt 32) {
        Write-Host "[ERROR] TunnelAccessToken must be at least 32 characters." -ForegroundColor Red
        if (-not $NoPause) { Read-Host "Press Enter to exit" }
        exit 1
    }
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [IO.File]::WriteAllText((Join-Path $scriptDir "tunnel_token.txt"), $TunnelAccessToken, $utf8NoBom)

    $traceGatePort = 3300
    $bridgeGatePort = 3301
    $edmGatePort = 3302
    $traceTarget = if ($tracePort -gt 0) { "http://127.0.0.1:$tracePort" } else { "http://127.0.0.1:3000" }

    Write-Host ""
    Write-Host "Starting local tunnel gates..." -ForegroundColor Cyan
    $g1 = Start-Gate $traceTarget $traceGatePort "trace-engine-web"
    $g2 = Start-Gate "http://127.0.0.1:$bridgePort" $bridgeGatePort "trace-to-edm"
    $g3 = Start-Gate "http://127.0.0.1:5173" $edmGatePort "edm-takens-web"
    $jobs += $g1; $jobs += $g2; $jobs += $g3
    [void](Wait-HealthCheck "http://127.0.0.1:$traceGatePort/__gate/health" "trace gate" 20)
    [void](Wait-HealthCheck "http://127.0.0.1:$bridgeGatePort/__gate/health" "bridge gate" 20)
    [void](Wait-HealthCheck "http://127.0.0.1:$edmGatePort/__gate/health" "edm gate" 20)

    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $tewLogDir = Join-Path $traceDir "tunnel_logs"
    $tteLogDir = Join-Path $bridgeDir "tunnel_logs"
    $edwLogDir = Join-Path $edmDir "tunnel_logs"
    foreach ($ld in @($tewLogDir, $tteLogDir, $edwLogDir)) {
        [IO.Directory]::CreateDirectory($ld) | Out-Null
    }
    $cf1Out = Join-Path $tewLogDir "cf_out_$ts.log"
    $cf1Err = Join-Path $tewLogDir "cf_err_$ts.log"
    $cf1 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel --edge-ip-version 4 --no-chunked-encoding --url http://localhost:$traceGatePort" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf1Out -RedirectStandardError $cf1Err
    $cfJobs += $cf1

    $cf2Out = Join-Path $tteLogDir "cf_out_$ts.log"
    $cf2Err = Join-Path $tteLogDir "cf_err_$ts.log"
    $cf2 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel --edge-ip-version 4 --no-chunked-encoding --url http://localhost:$bridgeGatePort" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf2Out -RedirectStandardError $cf2Err
    $cfJobs += $cf2

    $cf3Out = Join-Path $edwLogDir "cf_out_$ts.log"
    $cf3Err = Join-Path $edwLogDir "cf_err_$ts.log"
    $cf3 = Start-Process -FilePath "cloudflared" `
        -ArgumentList "tunnel --edge-ip-version 4 --no-chunked-encoding --url http://localhost:$edmGatePort" `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $cf3Out -RedirectStandardError $cf3Err
    $cfJobs += $cf3
    Write-Host ""
    Write-Host "Waiting for tunnel URLs (up to 60s)..." -ForegroundColor Yellow
    $waited = 0; $maxWait = 60
    $url1 = $null; $url2 = $null; $url3 = $null
    while ($waited -lt $maxWait -and -not ($url1 -and $url2 -and $url3)) {
        Start-Sleep 3; $waited += 3
        foreach ($pair in @(
            @{Out=$cf1Out; Err=$cf1Err; Set='1'},
            @{Out=$cf2Out; Err=$cf2Err; Set='2'},
            @{Out=$cf3Out; Err=$cf3Err; Set='3'}
        )) {
            $logs = @()
            if (Test-Path $pair.Out) { $logs += Get-Content $pair.Out -ErrorAction SilentlyContinue }
            if (Test-Path $pair.Err) { $logs += Get-Content $pair.Err -ErrorAction SilentlyContinue }
            $m = $logs | Select-String -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) {
                if ($pair.Set -eq '1') { $url1 = $m.Matches.Value }
                elseif ($pair.Set -eq '2') { $url2 = $m.Matches.Value }
                else { $url3 = $m.Matches.Value }
            }
        }
        if ($url1 -and $url2 -and $url3) { break }
    }

    if ($url1) { [IO.File]::WriteAllText((Join-Path $traceDir "tunnel_url.txt"), $url1, $utf8NoBom) }
    if ($url2) { [IO.File]::WriteAllText((Join-Path $bridgeDir "tunnel_url.txt"), $url2, $utf8NoBom) }
    if ($url3) { [IO.File]::WriteAllText((Join-Path $edmDir "tunnel_url.txt"), $url3, $utf8NoBom) }

    function Format-TunnelUrl($u) {
        if (-not $u) { return "(not available)" }
        return "$u/?token=$TunnelAccessToken"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Protected tunnel URLs" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  trace-engine-web: $(Format-TunnelUrl $url1)" -ForegroundColor $(if ($url1) {'Green'} else {'Red'})
    Write-Host "  trace-to-edm:     $(Format-TunnelUrl $url2)" -ForegroundColor $(if ($url2) {'Green'} else {'Red'})
    Write-Host "  edm-takens-web:   $(Format-TunnelUrl $url3)" -ForegroundColor $(if ($url3) {'Green'} else {'Red'})
    Write-Host ""
    Write-Host "  Tunnel token: $TunnelAccessToken" -ForegroundColor Yellow
    Write-Host "  Token is also saved to: $(Join-Path $scriptDir 'tunnel_token.txt')" -ForegroundColor Gray
    Write-Host "  The public URL alone is NOT authentication; the gate requires the token." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Ctrl+C to stop all services, gates and tunnels." -ForegroundColor Yellow
    while ($true) { Start-Sleep 1 }
} finally {
    Write-Host ""
    Write-Host "[cleanup] stopping cloudflared tunnels..." -ForegroundColor Yellow
    foreach ($j in $cfJobs) {
        try { if ($j -and -not $j.HasExited) { Stop-ProcessTree $j.Id } } catch { }
    }
    Write-Host "[cleanup] stopping services and gates..." -ForegroundColor Yellow
    foreach ($j in $jobs) {
        try { if ($j -and -not $j.HasExited) { Stop-ProcessTree $j.Id } } catch { }
    }
    Write-Host "[cleanup] done." -ForegroundColor Yellow
    if (-not $NoPause) { Read-Host "Press Enter to exit" }
}