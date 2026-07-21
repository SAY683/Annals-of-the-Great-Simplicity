@echo off
chcp 65001 >nul
REM trace-to-edm Tunnel Launcher (English-only for encoding safety)
REM Pre-checks cloudflared and node_modules, then launches tunnel.ps1
REM in a new PowerShell window.
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

REM Constraint #6: node_modules pre-check (project root) + auto npm install
if not exist "%~dp0node_modules" (
    echo [WARN] node_modules missing, running npm install...
    set HTTP_PROXY=
    set HTTPS_PROXY=
    pushd "%~dp0"
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
REM If port 3100 is occupied by a previous instance, tunnel.ps1 will reuse it.

REM Constraint #4 & #8: launch tunnel.ps1 in a new PowerShell window
REM Use relative path (tunnel.ps1) and empty title to avoid cmd "start"
REM parsing issues with parentheses in path (TRACE Engine(EDM-Takens CCM))
echo [OK] Pre-checks passed. Launching tunnel...
start "" powershell -NoProfile -ExecutionPolicy Bypass -File "tunnel.ps1"

endlocal
echo.
echo [OK] Tunnel window launched. Check the new window for URL.
echo      (cloudflared must be in PATH beforehand)
pause
