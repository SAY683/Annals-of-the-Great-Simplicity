$ps = Get-Process python,node -ErrorAction SilentlyContinue
if ($ps) {
    $ps | Select-Object Name,Id,StartTime,CPU,
        @{N='MemMB';E={[math]::Round($_.WorkingSet64/1MB,1)}} |
        Format-Table -AutoSize
} else {
    Write-Host "No python/node processes running."
}
Write-Host "---PORTS---"
$conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 3000,3001,3100,5173,8000 }
if ($conns) {
    $conns | Select-Object LocalPort,OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize
} else {
    Write-Host "No target ports listening."
}
