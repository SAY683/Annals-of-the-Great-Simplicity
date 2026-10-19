#Requires -Version 5.0
<#
.SYNOPSIS
  Build a clean source release archive from Git-tracked files.

.DESCRIPTION
  The archive is produced with `git archive HEAD`, so ignored runtime state
  (results, work, logs, caches, node_modules, local models) is never included.
  Model weights and multi-GB base models remain separate distribution artifacts.
  The script also rejects archives containing known runtime or secret paths.

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
        $candidates = [System.Collections.Generic.List[string]]::new()
        foreach ($value in @($env:TRACE_PYTHON_CMD, $env:EDM_PYTHON_CMD, $env:GRAPHRAG_PYTHON)) {
            if (-not [string]::IsNullOrWhiteSpace($value)) { $candidates.Add($value) }
        }
        $candidates.Add((Join-Path $repoRoot 'Complement\.venv\Scripts\python.exe'))
        $candidates.Add((Join-Path $repoRoot 'Complement\.venv\bin\python'))
        if ($env:COMPLEMENT_PYTHON_CANDIDATES) {
            foreach ($value in ($env:COMPLEMENT_PYTHON_CANDIDATES -split [IO.Path]::PathSeparator)) {
                if (-not [string]::IsNullOrWhiteSpace($value)) { $candidates.Add($value.Trim()) }
            }
        }
        $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            foreach ($ver in @('-3.13', '-3.12', '-3.11', '-3.10')) {
                try {
                    $resolved = & py $ver -c "import sys; print(sys.executable)" 2>$null
                    if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates.Add($resolved.Trim()) }
                } catch { }
            }
        }
        foreach ($name in @('python', 'python3')) {
            $cmd = Get-Command $name -ErrorAction SilentlyContinue
            if ($cmd) { $candidates.Add($cmd.Source) }
        }

        $python = $null
        $seen = @{}
        foreach ($candidate in $candidates) {
            if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
            $exe = $candidate
            if (-not (Test-Path -LiteralPath $exe)) {
                $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
                if (-not $cmd) { continue }
                $exe = $cmd.Source
            }
            if ($seen.ContainsKey($exe)) { continue }
            $seen[$exe] = $true
            try {
                & $exe -c "import numpy,pandas,scipy,sklearn,jieba,dowhy,causallearn" 2>$null
                if ($LASTEXITCODE -eq 0) { $python = $exe; break }
            } catch { }
        }
        if (-not $python) {
            throw 'No complete Python interpreter found. Set TRACE_PYTHON_CMD or run tools\bootstrap.ps1.'
        }
        Write-Host "[release] audit interpreter: $python" -ForegroundColor DarkGray
        & $python 'Complement\tools\check_docs.py'
        if ($LASTEXITCODE -ne 0) { throw 'Documentation link audit failed; release was not built.' }
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

    # Fail closed: a source package must never contain runtime or secret artifacts.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = 'Annals-of-the-Great-Simplicity/'
    $required = @(
        'README.md',
        'LICENSE',
        'Complement/tools/build_release.ps1',
        'Complement/tools/clean_runtime.ps1',
        'Complement/tools/check_env.py',
        'Complement/tools/check_docs.py',
        'Complement/tools/prepare_news_corpus.py',
        'Complement/tools/requirements-news.txt',
        'Complement/tools/warm_semantic_cache.py',
        'Complement/Docs/07-deployment.md',
        'Complement/TRACE Engine(EDM-Takens CCM)/trace-engine-web/py_bridge_worker.py',
        'Complement/TRACE Engine(EDM-Takens CCM)/trace-to-edm/edm_only.py',
        'Complement/TRACE Engine(EDM-Takens CCM)/verify_portable.py'
    )
    $forbiddenPattern = '(^|/)(node_modules|__pycache__|\.pytest_cache|tunnel_logs|results|work|logs?)(/|$)|(^|/)jobs\.sqlite$|(^|/)tunnel_url\.txt$|(^|/)trace_to_edm_.*\.csv$|(^|/)\.env(\.|$)|\.(safetensors|pyc|pyo|log|pem|key)$'
    $zip = [IO.Compression.ZipFile]::OpenRead($OutputPath)
    $validationError = $null
    try {
        $entries = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        $badEntries = @($entries | Where-Object { $_ -match $forbiddenPattern })
        $missingEntries = @($required | Where-Object { $entries -notcontains ($prefix + $_) })
        if ($badEntries.Count -gt 0) {
            $validationError = "Archive contains forbidden runtime/secret entries:`n$($badEntries -join "`n")"
        } elseif ($missingEntries.Count -gt 0) {
            $validationError = "Archive is missing required files:`n$($missingEntries -join "`n")"
        }
    } finally {
        $zip.Dispose()
    }
    if ($validationError) {
        Remove-Item -LiteralPath $OutputPath -Force
        throw $validationError
    }
    Write-Host "[release] archive check: $($entries.Count) entries, 0 forbidden, required files present" -ForegroundColor DarkGray


    $file = Get-Item -LiteralPath $OutputPath
    $hash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash
    $manifest = [ordered]@{
        artifact = $file.Name
        commit = $commit
        created_at = (Get-Date).ToString('o')
        size_bytes = $file.Length
        sha256 = $hash
        source = 'git archive HEAD'
        excluded = @('node_modules', 'runtime results/work/logs/caches', 'local model weights', 'secrets')
    }
    $manifestPath = [IO.Path]::ChangeExtension($OutputPath, '.manifest.json')
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 4), [Text.UTF8Encoding]::new($false))

    Write-Host "[release] archive : $OutputPath" -ForegroundColor Green
    Write-Host "[release] manifest: $manifestPath" -ForegroundColor Green
    Write-Host "[release] sha256  : $hash" -ForegroundColor Cyan
    Write-Host "[release] size    : $([math]::Round($file.Length / 1MB, 2)) MB" -ForegroundColor Cyan
}
finally {
    Pop-Location
}
