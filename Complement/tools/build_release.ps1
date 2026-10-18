#Requires -Version 5.0
<#
.SYNOPSIS
  Build a clean source release archive from Git-tracked files.

.DESCRIPTION
  The archive is produced with `git archive HEAD`, so ignored runtime state
  (results, work, logs, caches, node_modules, local models) is never included.
  Model weights and multi-GB base models remain separate distribution artifacts.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_release.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_release.ps1 -SkipAudit
#>
[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$SkipAudit,
    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Push-Location $repoRoot
try {
    $dirty = @(& git status --porcelain)
    if ($dirty.Count -gt 0 -and -not $AllowDirty) {
        throw "Working tree is not clean. Commit/stash changes or pass -AllowDirty.`n$($dirty -join "`n")"
    }

    if (-not $SkipAudit) {
        $python = $env:TRACE_PYTHON_CMD
        if (-not $python) {
            try {
                . (Join-Path $repoRoot 'Complement\shared\python_env.ps1')
                $resolved = Resolve-ComplementPython -Required @('numpy', 'pandas', 'scipy', 'sklearn', 'jieba', 'dowhy', 'causallearn')
                if ($resolved -and $resolved.Ok) { $python = $resolved.Path }
            } catch { }
        }
        if (-not $python) { $python = 'python' }
        & $python 'Complement\TRACE Engine(EDM-Takens CCM)\verify_portable.py' --no-e2e
        if ($LASTEXITCODE -ne 0) { throw 'Portable audit failed; release was not built.' }
    }

    $commit = (& git rev-parse HEAD).Trim()
    $short = (& git rev-parse --short HEAD).Trim()
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        $OutputPath = Join-Path $repoRoot "release\Annals-of-the-Great-Simplicity-$short.zip"
    } elseif (-not [IO.Path]::IsPathRooted($OutputPath)) {
        $OutputPath = Join-Path $repoRoot $OutputPath
    }
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    $outputDir = Split-Path -Parent $OutputPath
    [IO.Directory]::CreateDirectory($outputDir) | Out-Null

    & git archive --format=zip '--prefix=Annals-of-the-Great-Simplicity/' "--output=$OutputPath" HEAD
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
        throw 'git archive failed.'
    }

    $file = Get-Item -LiteralPath $OutputPath
    $hash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash
    $manifest = [ordered]@{
        artifact = $file.Name
        commit = $commit
        created_at = (Get-Date).ToString('o')
        size_bytes = $file.Length
        sha256 = $hash
        source = 'git archive HEAD'
        excluded = @('node_modules', 'runtime results/work/logs/caches', 'local model weights')
    }
    $manifestPath = [IO.Path]::ChangeExtension($OutputPath, '.manifest.json')
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    Write-Host "[release] archive : $OutputPath" -ForegroundColor Green
    Write-Host "[release] manifest: $manifestPath" -ForegroundColor Green
    Write-Host "[release] sha256  : $hash" -ForegroundColor Cyan
    Write-Host "[release] size    : $([math]::Round($file.Length / 1MB, 2)) MB" -ForegroundColor Cyan
}
finally {
    Pop-Location
}