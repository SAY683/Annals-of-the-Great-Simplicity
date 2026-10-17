#Requires -Version 5.0
<#
  python_env.ps1 - cross-machine Python interpreter detection and capability check.
  Sourced by start_all.ps1 / trace-engine-web/start.ps1.
#>

$ComplementRoot = Split-Path -Parent $PSScriptRoot

function Get-ComplementPythonProbe {
    param([Parameter(Mandatory)][string]$Exe)
    $code = 'import importlib.util,json,sys; mods=["numpy","pandas","scipy","sklearn","jieba","dowhy","causallearn","pyEDM","fastapi","uvicorn","torch","transformers","graphrag","lancedb","mcp"]; print(json.dumps({"python":sys.executable,"version":sys.version.split()[0],"modules":{m:bool(importlib.util.find_spec(m)) for m in mods}},ensure_ascii=False))'
    $probeFile = Join-Path $env:TEMP "complement_python_probe_$PID.py"
    [IO.File]::WriteAllText($probeFile, $code, [Text.UTF8Encoding]::new($false))
    try {
        $raw = & $Exe $probeFile 2>$null
    } finally {
        try { [IO.File]::Delete($probeFile) } catch { }
    }
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
    try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Resolve-ComplementPython {
    param(
        [string[]]$Required = @(),
        [string]$Preferred = ""
    )
    $candidates = New-Object System.Collections.Generic.List[string]
    foreach ($v in @($Preferred, $env:TRACE_PYTHON_CMD, $env:EDM_PYTHON_CMD, $env:GRAPHRAG_PYTHON)) {
        if ($v) { $candidates.Add([string]$v) }
    }
    $candidates.Add((Join-Path $ComplementRoot '.venv\Scripts\python.exe'))
    $candidates.Add("G:\Python\python.exe")
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) { $candidates.Add($pythonCmd.Source) }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($ver in @("-3.13", "-3.12", "-3.11", "-3.10")) {
            $resolved = & py $ver -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates.Add($resolved.Trim()) }
        }
    }
    $seen = @{}
    $best = $null
    $bestScore = -1
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        if ($seen.ContainsKey($candidate)) { continue }
        $seen[$candidate] = $true
        $exe = $candidate
        if (-not (Test-Path -LiteralPath $exe)) {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($cmd) { $exe = $cmd.Source } else { continue }
        }
        $probe = Get-ComplementPythonProbe -Exe $exe
        if (-not $probe) { continue }
        $missing = @()
        foreach ($mod in $Required) {
            $has = $false
            if ($probe.modules -and $probe.modules.PSObject.Properties[$mod]) {
                $has = [bool]$probe.modules.$mod
            }
            if (-not $has) { $missing += $mod }
        }
        $score = $Required.Count - $missing.Count
        $obj = [pscustomobject]@{
            Path = [string]$probe.python
            Version = [string]$probe.version
            Ok = ($missing.Count -eq 0)
            Missing = $missing
            Modules = $probe.modules
        }
        if ($obj.Ok) { return $obj }
        if ($score -gt $bestScore) { $bestScore = $score; $best = $obj }
    }
    return $best
}

function Write-ComplementPythonHint {
    param($Probe)
    if (-not $Probe) {
        Write-Host "[ERROR] No usable Python interpreter found." -ForegroundColor Red
        Write-Host "        Set TRACE_PYTHON_CMD / EDM_PYTHON_CMD to a python.exe." -ForegroundColor Yellow
        return
    }
    Write-Host "[ERROR] Python is missing modules: $($Probe.Missing -join ', ')" -ForegroundColor Red
    Write-Host "        Candidate: $($Probe.Path) ($($Probe.Version))" -ForegroundColor Yellow
    Write-Host "        Install: & `"$($Probe.Path)`" -m pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host "        Or set TRACE_PYTHON_CMD / EDM_PYTHON_CMD to a complete interpreter." -ForegroundColor Yellow
}
