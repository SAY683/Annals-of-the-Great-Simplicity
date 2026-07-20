@echo off
chcp 65001 >nul
REM trace-to-edm Tunnel Launcher (English wrapper for stability)
REM Pre-checks cloudflared and node_modules, then launches tunnel.ps1
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

REM Constraint #7: port conflict pre-check (netstat) for port 3100
netstat -ano | findstr ":3100 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [WARN] Port 3100 is already in use. Server may fail to start.
    echo        Close any process using port 3100 and retry.
    pause
    exit /b 1
)

REM Constraint #4 & #8: launch tunnel.ps1 in a new window with port info in title
start "trace-to-edm Tunnel (port 3100)" cmd /c "powershell -NoProfile -ExecutionPolicy Bypass -File .\tunnel.ps1"

endlocal
