#Requires -Version 5.0
<#
.SYNOPSIS
  Audit or remove known Complement runtime artifacts.

.DESCRIPTION
  Default mode is a dry run. Logs/caches are listed without being deleted unless
  -Apply is supplied. Task outputs, work directories, archives and job databases
  are only included with -IncludeTaskHistory, because they may contain user data.

.EXAMPLES
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1 -Apply
  powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean_runtime.ps1 -Apply -IncludeTaskHistory
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply,
    [switch]$IncludeTaskHistory
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$complement = Join-Path $repoRoot 'Complement'
$targets = [System.Collections.Generic.List[string]]::new()

function Add-Target {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return }
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside repository: $full"
    }
    if (Test-Path -LiteralPath $full) {
        if (-not $targets.Contains($full)) { $targets.Add($full) }
    }
}

# Always-safe runtime noise: logs, caches and transient tunnel state.
$logDirs = @(
    'Complement\tunnel_logs',
    'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\tunnel_logs',
    'Complement\TRACE Engine(EDM-Takens CCM)\trace-engine-web\tunnel_logs',
    'Complement\TRACE Engine(EDM-Takens CCM)\trace-to-edm\tunnel_logs'
)
foreach ($relative in $logDirs) { Add-Target (Join-Path $repoRoot $relative) }

Get-ChildItem -LiteralPath $complement -Directory -Filter 'GraphRAG-*' -ErrorAction SilentlyContinue |
    ForEach-Object { Add-Target (Join-Path $_.FullName 'project\logs') }

$tunnelUrls = @(
    'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\tunnel_url.txt',
    'Complement\TRACE Engine(EDM-Takens CCM)\trace-engine-web\tunnel_url.txt',
    'Complement\TRACE Engine(EDM-Takens CCM)\trace-to-edm\tunnel_url.txt'
)
foreach ($relative in $tunnelUrls) { Add-Target (Join-Path $repoRoot $relative) }

Get-ChildItem -LiteralPath $complement -Recurse -Force -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('__pycache__', '.pytest_cache') } |
    ForEach-Object { Add-Target $_.FullName }

Add-Target (Join-Path $repoRoot '.pytest_cache')
Add-Target (Join-Path $repoRoot '__pycache__')

Get-ChildItem -LiteralPath $repoRoot -Force -File -Filter '.tmp_*.py' -ErrorAction SilentlyContinue |
    ForEach-Object { Add-Target $_.FullName }

# User/task history is opt-in.
if ($IncludeTaskHistory) {
    $historyTargets = @(
        'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\results',
        'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\archive',
        'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\work',
        'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\jobs.sqlite',
        'Complement\TRACE Engine(EDM-Takens CCM)\trace-engine-web\work',
        'Complement\TRACE Engine(EDM-Takens CCM)\trace-to-edm\work',
        'Complement\TRACE Engine(EDM-Takens CCM)\trace-to-edm\projects\_index.json',
        'Complement\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\outputs'
    )
    foreach ($relative in $historyTargets) { Add-Target (Join-Path $repoRoot $relative) }

    Get-ChildItem -LiteralPath (Join-Path $repoRoot 'Complement\TRACE Engine(EDM-Takens CCM)\edm-takens-web\data') -Filter 'trace_to_edm_*.csv' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Target $_.FullName }
    Get-ChildItem -LiteralPath (Join-Path $repoRoot 'Complement\TRACE Engine(EDM-Takens CCM)\trace-to-edm\projects') -Recurse -Filter '_*pending.csv' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Target $_.FullName }
}

if ($targets.Count -eq 0) {
    Write-Host '[clean] No known runtime artifacts found.' -ForegroundColor Green
    exit 0
}

Write-Host "[clean] $($targets.Count) runtime target(s) detected." -ForegroundColor Cyan
if (-not $Apply) {
    Write-Host '[clean] DRY RUN: nothing will be deleted. Re-run with -Apply to remove.' -ForegroundColor Yellow
}
if ($IncludeTaskHistory) {
    Write-Host '[clean] Task history/work/archive outputs are included.' -ForegroundColor Yellow
}

foreach ($target in $targets) {
    if (-not $Apply) {
        Write-Host "  WOULD REMOVE  $target"
        continue
    }
    if ($PSCmdlet.ShouldProcess($target, 'Remove runtime artifact')) {
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Host "  REMOVED       $target" -ForegroundColor DarkGray
    }
}

Write-Host '[clean] Complete.' -ForegroundColor Green
