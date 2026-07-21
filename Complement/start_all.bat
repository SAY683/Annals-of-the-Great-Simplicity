@echo off
chcp 65001 >nul
REM start_all.bat ¡ª Three Web Projects Unified Launcher
REM Launches start_all.ps1 which starts all three web services
REM and their Cloudflare tunnels in a single window.
setlocal
cd /d "%~dp0"

REM Show previously used tunnel URLs (if any)
echo.
if exist "%~dp0TRACE Engine(EDM-Takens CCM)\trace-engine-web\tunnel_url.txt" (
    echo [INFO] Previous trace-engine-web URL:
    type "%~dp0TRACE Engine(EDM-Takens CCM)\trace-engine-web\tunnel_url.txt"
    echo.
)
if exist "%~dp0TRACE Engine(EDM-Takens CCM)\trace-to-edm\tunnel_url.txt" (
    echo [INFO] Previous trace-to-edm URL:
    type "%~dp0TRACE Engine(EDM-Takens CCM)\trace-to-edm\tunnel_url.txt"
    echo.
)
if exist "%~dp0Skill\edm-takens-web\tunnel_url.txt" (
    echo [INFO] Previous edm-takens-web URL:
    type "%~dp0Skill\edm-takens-web\tunnel_url.txt"
    echo.
)

REM Pre-check: cloudflared
where cloudflared >nul 2>&1
if errorlevel 1 (
    echo [ERROR] cloudflared not found in PATH.
    echo Please install from:
    echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
    echo Or download binary:
    echo   https://github.com/cloudflare/cloudflared/releases
    pause
    exit /b 1
)

REM Pre-check: python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Please install Python 3.10+.
    pause
    exit /b 1
)

REM Pre-check: node
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] node not found in PATH. Please install Node.js 18+.
    pause
    exit /b 1
)

echo [OK] Pre-checks passed. Launching unified starter...
echo      (All three services + tunnels will start in this window)
echo.

REM Launch start_all.ps1 in current window (not a new window, so user can Ctrl+C)
powershell -NoProfile -ExecutionPolicy Bypass -File "start_all.ps1"

endlocal
pause
