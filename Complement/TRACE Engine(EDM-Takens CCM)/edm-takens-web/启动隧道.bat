@echo off
chcp 65001 >nul
REM EDM-Takens Web Tunnel Launcher (English wrapper for stability)
REM Pre-checks cloudflared and frontend node_modules, then launches tunnel.ps1
REM in a new window using "start \"title\" cmd /c \"...\"".
setlocal
cd /d "%~dp0"

REM Show previously used tunnel URL (if any)
if exist "%~dp0tunnel_url.txt" (
    echo.
    echo [INFO] Previously used tunnel URL:
    type "%~dp0tunnel_url.txt"
    echo.
)

REM Constraint #3: cloudflared pre-check
where cloudflared >nul 2>&1
if errorlevel 1 (
    echo [ERROR] cloudflared not found in PATH.
    echo Please install from:
    echo   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
    echo Or download binary:
    echo   https://github.com/cloudflare/cloudflared/releases
    echo After install, ensure cloudflared.exe is in PATH.
    pause
    exit /b 1
)

REM Constraint #6: frontend node_modules pre-check + auto npm install
if not exist "%~dp0frontend\node_modules" (
    echo [WARN] frontend\node_modules missing, running npm install...
    set HTTP_PROXY=
    set HTTPS_PROXY=
    pushd "%~dp0frontend"
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

REM Port conflict check removed: tunnel.ps1 handles port reuse via health check.
REM If ports 5173/8000 are occupied by a previous instance, tunnel.ps1 will reuse them.

REM Constraint #4 & #8: launch tunnel.ps1 in a new PowerShell window
REM Use relative path (tunnel.ps1) and empty title to avoid cmd "start"
REM parsing issues with parentheses in path
echo [OK] Pre-checks passed. Launching tunnel...
start "" powershell -NoProfile -ExecutionPolicy Bypass -File "tunnel.ps1"

endlocal
echo.
echo [OK] Tunnel window launched. Check the new window for URL.
echo      (cloudflared must be in PATH beforehand)
pause
