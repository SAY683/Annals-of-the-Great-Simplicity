#Requires -Version 5.0
<#
  trace-to-edm + Cloudflare Tunnel (中文入口薄包装)
  ================================================
  Q9 P1-18 统一: 本脚本仅作为中文双击入口，逻辑全部委托给 tunnel.ps1。
  消除双源维护风险：所有 cloudflared 检查 / 端口探测 / health check / 
  URL 持久化 / 代理清除 逻辑统一在 tunnel.ps1 中维护。

  使用方法:
    1. 在脚本所在目录双击运行
    2. 或在 PowerShell 中: ./启动隧道.ps1
#>

$ErrorActionPreference = "Stop"
# 仅在非 UTF-8 控制台时设置编码，避免与 cmd chcp 65001 重复编码导致中文重影
$currentOut = [Console]::OutputEncoding
if ($currentOut -isnot [System.Text.Encoding] -or $currentOut.WebName -ne 'utf-8') {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
}

# 定位同目录下的 tunnel.ps1
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$tunnelScript = Join-Path $scriptDir "tunnel.ps1"

if (-not (Test-Path $tunnelScript)) {
    Write-Host "[ERROR] 未找到 tunnel.ps1 (应位于同目录下)" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

# 转调新版隧道脚本，传递所有参数
& $tunnelScript @args
