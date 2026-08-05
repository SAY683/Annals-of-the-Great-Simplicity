#Requires -Version 5.0
<#
  stop-embedding.ps1 - Stop the local bge-m3 embedding service on port 8081.
#>
$ErrorActionPreference = "Continue"
$Port = if ($env:EMBED_PORT) { [int]$env:EMBED_PORT } else { 8081 }
$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($conn) {
    $ids = $conn.OwningProcess | Sort-Object -Unique
    foreach ($id in $ids) {
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -match "llama") {
            Write-Host "[OK] 停止 llama-server (PID $id)" -ForegroundColor Green
            Stop-Process -Id $id -Force
        }
    }
} else {
    Write-Host "[INFO] 端口 $Port 无服务在监听。" -ForegroundColor Gray
}
