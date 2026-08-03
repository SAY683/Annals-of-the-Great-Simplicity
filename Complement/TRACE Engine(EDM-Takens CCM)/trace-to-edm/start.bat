@echo off
REM R46-C fix (ROUND46 P0): Pure English bat + chcp 65001 to handle Chinese path.
REM Root cause: UTF-8 Chinese comments/echo were mis-decoded by cmd.exe (GBK),
REM causing garbled chars to be parsed as command separators, splitting one
REM line into multiple invalid commands ("neq", "xit", "CE_PYTHON_CMD" ...).
REM Fix: (1) chcp 65001 switches console to UTF-8 for Chinese path handling;
REM      (2) all comments and echo output in pure English to avoid GBK mis-decode.
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   trace-to-edm Web Console
echo   http://localhost:3100
echo ============================================

REM -- Node.js check --
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Node.js not found
    pause
    exit /b 1
)

REM -- Python check (trace-to-edm depends on bridge.py) --
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    where python3 >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [ERR] Python not found
        echo [ERR] trace-to-edm requires Python 3.8+ for bridge.py
        echo [ERR] Download: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [WARN] Using python3 (consider setting TRACE_PYTHON_CMD=python3)
)

REM -- Key script check --
if not exist "bridge.py" (
    echo [ERR] bridge.py not found - core bridge script missing
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
