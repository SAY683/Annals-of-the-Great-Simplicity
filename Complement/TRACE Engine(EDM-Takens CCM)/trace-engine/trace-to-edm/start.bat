@echo off
cd /d "%~dp0"

echo ============================================
echo   trace-to-edm Web Console
echo   http://localhost:3100
echo ============================================

where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Node.js not found
    pause
    exit /b 1
)

if not exist "node_modules" (
    echo [SETUP] Installing npm packages...
    call npm install
)

echo [OK] Starting server...
echo [OK] Press Ctrl+C to stop
echo.

node server.js
pause
