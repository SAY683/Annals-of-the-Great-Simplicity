#Requires -Version 5.0
<#
  common.ps1 - shared helpers for GraphRAG portable scripts.
  Dot-source:  . "$PSScriptRoot\common.ps1"
  Provides:
    Get-GraphRagPython  - detect a python that can import `graphrag`
                          (respects GRAPHRAG_PYTHON and COMPLEMENT_PYTHON_CANDIDATES)
    Get-GraphRagCli     - locate graphrag.exe next to that python
#>
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Get-GraphRagPython {
    <#
      Candidate order is portable-first: explicit variable, project .venv,
      caller-provided candidates, py launcher, PATH.
    #>
    $candidates = @()
    if ($env:GRAPHRAG_PYTHON) { $candidates += $env:GRAPHRAG_PYTHON }
    $projectRoot = Split-Path $PSScriptRoot -Parent
    $candidates += (Join-Path $projectRoot '.venv\Scripts\python.exe')
    $candidates += (Join-Path $projectRoot '.venv\bin\python')
    if ($env:COMPLEMENT_PYTHON_CANDIDATES) {
        $candidates += ($env:COMPLEMENT_PYTHON_CANDIDATES -split [IO.Path]::PathSeparator)
    }
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($ver in @('-3.13', '-3.12', '-3.11', '-3.10')) {
            try {
                $resolved = & py $ver -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates += $resolved.Trim() }
            } catch { }
        }
    }
    $candidates += 'python'
    $candidates += 'python3'
    $seen = @{}
    foreach ($py in $candidates) {
        if (-not $py) { continue }
        $cmd = Get-Command $py -ErrorAction SilentlyContinue
        $exe = if ($cmd) { $cmd.Source } else { $py }
        if (-not (Test-Path -LiteralPath $exe) -or $seen.ContainsKey($exe)) { continue }
        $seen[$exe] = $true
        try {
            $out = & $exe -c "import graphrag; print('OK')" 2>$null | Select-Object -Last 1
            if ($out -match '^OK$') { return $exe }
        } catch {}
    }
    return $null
}

function Get-GraphRagCli {
    <#
      Returns the graphrag.exe next to $Python, or 'graphrag' (PATH fallback).
    #>
    param([string]$Python)
    if ($Python -and (Test-Path -LiteralPath $Python)) {
        $cli = Join-Path (Split-Path $Python) "Scripts\graphrag.exe"
        if (Test-Path -LiteralPath $cli) { return $cli }
        $posixCli = Join-Path (Split-Path $Python) "graphrag"
        if (Test-Path -LiteralPath $posixCli) { return $posixCli }
    }
    return "graphrag"
}

function Assert-GraphRagPython {
    <#
      Resolve a graphrag-capable python or exit with a clear message.
      Returns the python path.
    #>
    param([string]$ExtraModule = "")
    $py = Get-GraphRagPython
    if (-not $py) {
        Write-Host "[ERROR] 未找到可用的 Python（需要能 import graphrag）。" -ForegroundColor Red
        Write-Host "        请设置 GRAPHRAG_PYTHON 指向正确的 python.exe，或先创建项目 .venv。" -ForegroundColor Yellow
        exit 1
    }
    if ($ExtraModule) {
        $mods = $ExtraModule -split ","
        $missing = @()
        foreach ($m in $mods) {
            & $py -c "import $m" 2>$null
            if ($LASTEXITCODE -ne 0) { $missing += $m }
        }
        if ($missing.Count -gt 0) {
            Write-Host "[ERROR] 当前 Python 缺少模块: $($missing -join ', ')" -ForegroundColor Red
            Write-Host "        请用该 Python 安装缺失模块后重试，或设置 GRAPHRAG_PYTHON。" -ForegroundColor Yellow
            exit 1
        }
    }
    return $py
}