@echo off
chcp 65001 >nul 2>&1
REM R46-D fix (ROUND46 P0): Pure English echo to avoid GBK mis-decode.
cd /d "%~dp0"
echo [TRACE Engine Web] Finding and stopping stale services...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_servers.ps1"
pause
