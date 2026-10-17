#Requires -Version 5.0
<#
  bootstrap.ps1 - create a local .venv and install the portable Python stack.
  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\bootstrap.ps1
    powershell ... -Python "C:\Python313\python.exe"
    powershell ... -VenvDir "D:\complement-venv"
  After bootstrap, start_all.ps1 will auto-detect .venv\Scripts\python.exe.
#>
param(
    [string]$Python = "",
    [string]$VenvDir = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$traceRoot = Join-Path $root "TRACE Engine(EDM-Takens CCM)"
if (-not $VenvDir) { $VenvDir = Join-Path $root ".venv" }
if (-not $Python) {
    $helper = Join-Path $root "shared\python_env.ps1"
    if (Test-Path $helper) {
        . $helper
        $probe = Resolve-ComplementPython -Required @('numpy','pandas','scipy','sklearn','fastapi','uvicorn')
        if ($probe) { $Python = $probe.Path }
    }
}
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    Write-Host "[ERROR] No usable Python found. Pass -Python path\to\python.exe" -ForegroundColor Red
    exit 1
}
Write-Host "[bootstrap] Python: $Python" -ForegroundColor Cyan
Write-Host "[bootstrap] venv:   $VenvDir" -ForegroundColor Cyan
& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
$venvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) { throw "venv python not found: $venvPy" }
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
$requirements = @(
    (Join-Path $traceRoot "trace-engine\requirements.txt"),
    (Join-Path $traceRoot "trace-engine-web\requirements.txt"),
    (Join-Path $traceRoot "edm-takens\requirements.txt"),
    (Join-Path $traceRoot "edm-takens-web\requirements.txt")
)
foreach ($req in $requirements) {
    if (Test-Path -LiteralPath $req) {
        Write-Host "[bootstrap] installing $req" -ForegroundColor Gray
        & $venvPy -m pip install -r $req
        if ($LASTEXITCODE -ne 0) { throw "pip install failed: $req" }
    }
}
Write-Host "[OK] venv ready: $venvPy" -ForegroundColor Green
Write-Host "     Set TRACE_PYTHON_CMD / EDM_PYTHON_CMD to this path, or let start_all.ps1 auto-detect .venv." -ForegroundColor Gray