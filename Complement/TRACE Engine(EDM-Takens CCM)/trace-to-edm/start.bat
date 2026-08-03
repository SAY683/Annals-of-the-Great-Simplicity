@echo off
cd /d "%~dp0"

echo ============================================
echo   trace-to-edm Web Console
echo   http://localhost:3100
echo ============================================

REM ── Node.js 检查 ──────────────────────────────────────
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Node.js not found
    pause
    exit /b 1
)

REM ── Python 检查 (盲审 P2-8 修缮 2026-08-02) ─────────
REM trace-to-edm 依赖 bridge.py 等 Python 模块, 缺 Python 会导致 /api/* 全部失效.
REM 检查 python 命令, 缺失时尝试 python3 (Linux/macOS 习惯).
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    where python3 >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [ERR] Python not found
        echo [ERR] trace-to-edm 依赖 Python (bridge.py 等), 请先安装 Python 3.8+
        echo [ERR] 下载: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo [WARN] 使用 python3 命令 (建议设置为 python 或配置 TRACE_PYTHON_CMD=python3)
)

REM ── 关键脚本检查 ─────────────────────────────────────
if not exist "bridge.py" (
    echo [ERR] bridge.py not found — 核心桥接脚本缺失
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
