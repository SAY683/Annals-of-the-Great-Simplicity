@echo off
chcp 65001 >nul
REM TRACE Engine Web Tunnel Launcher (English wrapper for stability)
REM Calls tunnel.ps1 to avoid UTF-8/GBK codepage issues in cmd.exe
setlocal
set PATH=%PATH%;C:\Program Files (x86)\cloudflared
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tunnel.ps1"
if exist "%~dp0tunnel_url.txt" (
    echo.
    echo [INFO] Recently used tunnel URL:
    type "%~dp0tunnel_url.txt"
    echo.
)
endlocal
