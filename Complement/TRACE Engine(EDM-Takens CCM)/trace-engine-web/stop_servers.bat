@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo [TRACE Engine Web] 正在查找并停止 stale 服务...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_servers.ps1"
pause
