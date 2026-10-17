#Requires -Version 5.0
param(
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$Token
)
$ErrorActionPreference = "Stop"
$env:TUNNEL_TARGET = $Target
$env:TUNNEL_GATE_PORT = [string]$Port
$env:TUNNEL_ACCESS_TOKEN = $Token
& node (Join-Path $PSScriptRoot 'tunnel_gate.js')
exit $LASTEXITCODE