#Requires -Version 5.0
<#
  reapply-patches.ps1 - Re-apply GraphRAG site-packages patches after an upgrade.
  Wraps reapply-graphrag-patches.py with the project's python detection.
#>
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"
$Python = Assert-GraphRagPython
$py = Join-Path $PSScriptRoot "reapply-graphrag-patches.py"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& $Python $py
