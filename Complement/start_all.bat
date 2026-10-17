@echo off
chcp 65001 >nul
REM start_all.bat - local-first launcher.
REM Default: local services only (127.0.0.1).
REM Tunnel mode:  start_all.bat tunnel
REM In tunnel mode a token gate protects the public URLs.
setlocal
cd /d "%~dp0"

if /I "%~1"=="tunnel" (
    echo [INFO] Starting services with protected Cloudflare tunnels...
    powershell -NoProfile -ExecutionPolicy Bypass -File "start_all.ps1" -EnableTunnel -NoPause
) else (
    echo [INFO] Starting local services only. Use "start_all.bat tunnel" for protected tunnels.
    powershell -NoProfile -ExecutionPolicy Bypass -File "start_all.ps1" -NoPause
)

endlocal
pause
