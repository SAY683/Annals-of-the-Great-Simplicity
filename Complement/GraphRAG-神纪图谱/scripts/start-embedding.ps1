#Requires -Version 5.0
<#
  start-embedding.ps1 - Start local bge-m3 embedding service (llama-server) on port 8081.
  Configurable via env vars: LLAMA_SERVER, BGE_MODEL, EMBED_PORT.
  Health check retries up to EMBED_WAIT_SECONDS (default 90s) because bge-m3 FP16 can take 10-30s to load.
#>
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$LlamaServer = if ($env:LLAMA_SERVER) { $env:LLAMA_SERVER } else { "G:\AI\llama-cpp\llama-server.exe" }
$Model       = if ($env:BGE_MODEL)     { $env:BGE_MODEL }     else { "G:\AI\轻量大模型\bge-m3\bge-m3-FP16.gguf" }
$Port        = if ($env:EMBED_PORT)    { [int]$env:EMBED_PORT } else { 8081 }
$WaitSec     = if ($env:EMBED_WAIT_SECONDS) { [int]$env:EMBED_WAIT_SECONDS } else { 90 }

Write-Host "[GraphRAG] 启动 bge-m3 向量服务 ..." -ForegroundColor Cyan
Write-Host "  llama-server : $LlamaServer"
Write-Host "  model        : $Model"
Write-Host "  port         : $Port"

if (-not (Test-Path -LiteralPath $LlamaServer)) {
    Write-Host "[ERROR] 找不到 llama-server：$LlamaServer" -ForegroundColor Red
    Write-Host "        请设置环境变量 LLAMA_SERVER 指向 llama-server.exe" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path -LiteralPath $Model)) {
    Write-Host "[ERROR] 找不到模型：$Model" -ForegroundColor Red
    Write-Host "        请设置环境变量 BGE_MODEL 指向 bge-m3 GGUF 文件" -ForegroundColor Yellow
    exit 1
}

# already running?
$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[OK] 端口 $Port 已有服务在监听，跳过启动。" -ForegroundColor Green
    exit 0
}

Start-Process -FilePath $LlamaServer `
    -ArgumentList "--model", "`"$Model`"", "--embedding", "--pooling", "cls", "--port", "$Port", "--host", "127.0.0.1", "--threads", "8", "--batch-size", "4096", "--ubatch-size", "4096" `
    -WindowStyle Hidden

# health check with retry (bge-m3 FP16 may take a while to load)
$ok = $false
$elapsed = 0
while ($elapsed -lt $WaitSec) {
    Start-Sleep -Seconds 5
    $elapsed += 5
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v1/models" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {}
    Write-Host "  ...等待模型加载 ($elapsed/${WaitSec}s)" -ForegroundColor Gray
}
if ($ok) {
    Write-Host "[OK] 向量服务就绪 (HTTP 200, ${elapsed}s)" -ForegroundColor Green
} else {
    Write-Host "[WARN] ${WaitSec}s 内未就绪，请稍后手动确认端口 $Port。" -ForegroundColor Yellow
}
