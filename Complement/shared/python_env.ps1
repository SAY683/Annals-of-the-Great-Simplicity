#Requires -Version 5.0
<#
  python_env.ps1 - cross-machine Python interpreter detection and capability check.
  Sourced by start_all.ps1 / trace-engine-web/start.ps1.

  Candidate order is portable-first:
    explicit component variables -> .venv -> COMPLEMENT_PYTHON_CANDIDATES
    -> Windows py launcher -> PATH. No machine-specific drive is assumed.
#>

$ComplementRoot = Split-Path -Parent $PSScriptRoot

function Get-ComplementPythonProbe {
    param([Parameter(Mandatory)][string]$Exe)
    $code = 'import importlib.util,json,sys; mods=["numpy","pandas","scipy","sklearn","jieba","dowhy","causallearn","pyEDM","fastapi","uvicorn","torch","transformers","graphrag","lancedb","mcp"]; print(json.dumps({"python":sys.executable,"version":sys.version.split()[0],"modules":{m:bool(importlib.util.find_spec(m)) for m in mods}},ensure_ascii=False))'
    $probeFile = Join-Path $env:TEMP "complement_python_probe_$PID.py"
    [IO.File]::WriteAllText($probeFile, $code, [Text.UTF8Encoding]::new($false))
    try {
        $raw = & $Exe $probeFile 2>$null
    } catch {
        return $null
    } finally {
        try { [IO.File]::Delete($probeFile) } catch { }
    }
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
    try { return ($raw | ConvertFrom-Json) } catch { return $null }
}

function Add-PythonCandidate {
    param(
        [System.Collections.Generic.List[string]]$Candidates,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $Candidates.Add($Value)
}

function Resolve-ComplementPython {
    param(
        [string[]]$Required = @(),
        [string]$Preferred = ""
    )
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($v in @($Preferred, $env:TRACE_PYTHON_CMD, $env:EDM_PYTHON_CMD, $env:GRAPHRAG_PYTHON)) {
        Add-PythonCandidate $candidates $v
    }
    Add-PythonCandidate $candidates (Join-Path $ComplementRoot '.venv\Scripts\python.exe')
    Add-PythonCandidate $candidates (Join-Path $ComplementRoot '.venv\bin\python')
    if ($env:COMPLEMENT_PYTHON_CANDIDATES) {
        foreach ($v in ($env:COMPLEMENT_PYTHON_CANDIDATES -split [IO.Path]::PathSeparator)) {
            Add-PythonCandidate $candidates $v.Trim()
        }
    }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($ver in @('-3.13', '-3.12', '-3.11', '-3.10')) {
            try {
                $resolved = & py $ver -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved) {
                    Add-PythonCandidate $candidates $resolved.Trim()
                }
            } catch { }
        }
    }
    foreach ($cmdName in @('python', 'python3')) {
        $pythonCmd = Get-Command $cmdName -ErrorAction SilentlyContinue
        if ($pythonCmd) { Add-PythonCandidate $candidates $pythonCmd.Source }
    }

    $seen = @{}
    $best = $null
    $bestScore = -1
    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        $exe = $candidate
        if (-not (Test-Path -LiteralPath $exe)) {
            $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($cmd) { $exe = $cmd.Source } else { continue }
        }
        if ($seen.ContainsKey($exe)) { continue }
        $seen[$exe] = $true
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
        Write-Host '[ERROR] No usable Python interpreter found.' -ForegroundColor Red
        Write-Host '        Set TRACE_PYTHON_CMD / EDM_PYTHON_CMD / GRAPHRAG_PYTHON,' -ForegroundColor Yellow
        Write-Host '        or create .venv with tools\bootstrap.ps1.' -ForegroundColor Yellow
        return
    }
    Write-Host "[ERROR] Python is missing modules: $($Probe.Missing -join ', ')" -ForegroundColor Red
    Write-Host "        Candidate: $($Probe.Path) ($($Probe.Version))" -ForegroundColor Yellow
    Write-Host "        Install: & `"$($Probe.Path)`" -m pip install -r requirements.txt" -ForegroundColor Yellow
    Write-Host '        Or set the matching *_PYTHON_CMD variable to a complete interpreter.' -ForegroundColor Yellow
}