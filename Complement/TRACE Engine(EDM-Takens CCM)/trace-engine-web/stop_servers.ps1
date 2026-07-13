<#
  安全停止本项目的 stale Node 与 Python 桥接进程
  ==================================================
  结束命令行包含 "server.js" 的 node.exe 进程（排除 vite 开发服务器），
  以及命令行包含 "py_bridge.py" 的 Python 进程，避免误杀其它服务。
  同时结束所有子进程（如由 Node 启动的 cmd.exe 包装进程）。
#>

$ErrorActionPreference = "SilentlyContinue"
$nodeKilled = 0
$pyKilled = 0
$childKilled = 0

function Stop-ProcessTree($pid) {
    Get-WmiObject Win32_Process | Where-Object { $_.ParentProcessId -eq $pid } | ForEach-Object {
        Stop-ProcessTree $_.ProcessId
        try {
            Stop-Process -Id $_.ProcessId -Force
            $script:childKilled++
        } catch { }
    }
}

Get-WmiObject Win32_Process -Filter "name='node.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like '*server.js*') -and ($cmd -notlike '*vite*')) {
        Write-Host "正在结束 Node 进程 PID=$($_.ProcessId) CMD=$cmd" -ForegroundColor Yellow
        Stop-ProcessTree $_.ProcessId
        Stop-Process -Id $_.ProcessId -Force
        $nodeKilled++
    }
}

Get-WmiObject Win32_Process -Filter "name='python.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and (($cmd -like '*py_bridge.py*') -or ($cmd -like '*llama_worker.py*'))) {
        Write-Host "正在结束 Python 进程 PID=$($_.ProcessId)" -ForegroundColor Yellow
        Stop-ProcessTree $_.ProcessId
        Stop-Process -Id $_.ProcessId -Force
        $pyKilled++
    }
}

if ($nodeKilled -eq 0 -and $pyKilled -eq 0 -and $childKilled -eq 0) {
    Write-Host "未发现 trace-engine-web 的 stale 进程。" -ForegroundColor Green
} else {
    Write-Host "已结束 $nodeKilled 个 Node 进程，$pyKilled 个 Python 桥接进程，$childKilled 个子进程。" -ForegroundColor Green
}
