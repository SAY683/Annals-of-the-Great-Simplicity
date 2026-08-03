@echo off
chcp 65001 >nul
REM R46-D fix (ROUND46 P0): Pure English bat to avoid GBK mis-decode.
cd /d "%~dp0"

echo ============================================
echo   trace-to-edm Web Console (Portable)
echo   http://localhost:3100
echo ============================================

REM -- Python check --
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Python not found in PATH
    echo [HINT] Please install Python 3.10+ and add to PATH
    pause
    exit /b 1
)

REM -- Node.js check --
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Node.js not found in PATH
    echo [HINT] Please install Node.js 18+ and add to PATH
    pause
    exit /b 1
)

REM -- Portable Qwen model check --
if not exist "..\Models\Qwen2.5-1.5B-Instruct" (
    echo [WARN] ..\Models\Qwen2.5-1.5B-Instruct not found
    echo [HINT] Place Qwen model under Complement\TRACE Engine(EDM-Takens CCM)\Models\
    echo [HINT] Or override path via QWEN_MODEL_PATH_1_5B env var
    echo.
    choice /c YN /m "Continue anyway (LLM inference may fail)"
    if errorlevel 2 exit /b 1
)

REM -- Optional 3B model check --
if not exist "..\Models\Qwen2.5-3B-Instruct" (
    echo [WARN] ..\Models\Qwen2.5-3B-Instruct not found (3B model is optional)
)

REM -- Set env vars (if not specified) --
if "%TRACE_PYTHON_CMD%"=="" set TRACE_PYTHON_CMD=python
if "%PORT%"=="" set PORT=3100

REM -- First run: install npm deps --
if not exist "node_modules" (
    echo [SETUP] First run, installing npm deps...
    call npm install
    if %ERRORLEVEL% neq 0 (
        echo [ERR] npm install failed
        pause
        exit /b 1
    )
)

REM -- Verify Python module import --
echo [VERIFY] Verifying Python module import...
python -c "import config; print('  config.IS_PORTABLE_LAYOUT =', config.IS_PORTABLE_LAYOUT)"
if %ERRORLEVEL% neq 0 (
    echo [ERR] Python module import failed
    echo [HINT] Run pip install -r requirements.txt
    pause
    exit /b 1
)

echo [OK] Starting server...
echo [OK] Open browser: http://localhost:3100
echo [OK] Press Ctrl+C to stop
echo.

node server.js
pause
