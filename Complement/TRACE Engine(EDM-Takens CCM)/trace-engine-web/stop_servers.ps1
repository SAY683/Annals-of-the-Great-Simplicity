<#
  安全停止本项目的 stale Node 与 Python 桥接进程
  ==================================================
  仅结束命令行包含 "trace-engine-web\server.js" 的 node.exe 进程，
  以及命令行包含 "py_bridge.py" 的 Python 进程，避免误杀其它服务。
#>

$ErrorActionPreference = "SilentlyContinue"
$nodeKilled = 0
$pyKilled = 0

Get-WmiObject Win32_Process -Filter "name='node.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like '*trace-engine-web*server.js*')) {
        Write-Host "正在结束 Node 进程 PID=$($_.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force
        $nodeKilled++
    }
}

Get-WmiObject Win32_Process -Filter "name='python.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like '*py_bridge.py*')) {
        Write-Host "正在结束 Python 桥接进程 PID=$($_.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force
        $pyKilled++
    }
}

if ($nodeKilled -eq 0 -and $pyKilled -eq 0) {
    Write-Host "未发现 trace-engine-web 的 stale 进程。" -ForegroundColor Green
} else {
    Write-Host "已结束 $nodeKilled 个 Node 进程，$pyKilled 个 Python 桥接进程。" -ForegroundColor Green
}
