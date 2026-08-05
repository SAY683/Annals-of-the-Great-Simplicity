#Requires -Version 5.0
<#
  common.ps1 - shared helpers for GraphRAG portable scripts.
  Dot-source:  . "$PSScriptRoot\common.ps1"
  Provides:
    Get-GraphRagPython  - detect a python that can import `graphrag` (respects $env:GRAPHRAG_PYTHON)
    Get-GraphRagCli     - locate graphrag.exe next to that python
#>
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Get-GraphRagPython {
    <#
      Returns the path of a python.exe that can import `graphrag`, or $null.
      Candidate order: $env:GRAPHRAG_PYTHON -> known installs -> `python` on PATH.
    #>
    $candidates = @()
    if ($env:GRAPHRAG_PYTHON) { $candidates += $env:GRAPHRAG_PYTHON }
    $candidates += "G:\Python\python.exe"
    $candidates += "C:\Python313\python.exe"
    $candidates += "C:\Python312\python.exe"
    $candidates += "C:\Python311\python.exe"
    $candidates += "python"
    foreach ($py in $candidates) {
        if (-not $py) { continue }
        $cmd = Get-Command $py -ErrorAction SilentlyContinue
        $exe = if ($cmd) { $cmd.Source } else { $py }
        if (-not (Test-Path -LiteralPath $exe)) { continue }
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
        Write-Host "        请设置环境变量 GRAPHRAG_PYTHON 指向正确的 python.exe，或安装 graphrag 后重试。" -ForegroundColor Yellow
        exit 1
    }
    if ($ExtraModule) {
        $mods = $ExtraModule -split ","
        $missing = @()
        foreach ($m in $mods) {
            $chk = & $py -c "import $m" 2>$null
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
