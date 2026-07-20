@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   trace-to-edm Web Console (Portable)
echo   http://localhost:3100
echo ============================================

REM ── 检查 Python ──
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Python not found in PATH
    echo [HINT] 请安装 Python 3.10+ 并加入 PATH
    pause
    exit /b 1
)

REM ── 检查 Node.js ──
where node >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERR] Node.js not found in PATH
    echo [HINT] 请安装 Node.js 18+ 并加入 PATH
    pause
    exit /b 1
)

REM ── 检查便携式 Qwen 模型 ──
if not exist "..\Models\Qwen2.5-1.5B-Instruct" (
    echo [WARN] 未找到 ..\Models\Qwen2.5-1.5B-Instruct
    echo [HINT] 便携式布局下 Qwen 模型应放置在 Complement\TRACE Engine(EDM-Takens CCM)\Models\
    echo [HINT] 也可通过环境变量 QWEN_MODEL_PATH_1_5B 覆盖路径
    echo.
    choice /c YN /m "是否继续启动（可能无法运行 LLM 推理）"
    if errorlevel 2 exit /b 1
)

REM ── 检查 3B 模型（可选）──
if not exist "..\Models\Qwen2.5-3B-Instruct" (
    echo [WARN] 未找到 ..\Models\Qwen2.5-3B-Instruct（3B 模型为可选项）
)

REM ── 设置环境变量（如未指定）──
if "%TRACE_PYTHON_CMD%"=="" set TRACE_PYTHON_CMD=python
if "%PORT%"=="" set PORT=3100

REM ── 首次运行: 安装 npm 依赖 ──
if not exist "node_modules" (
    echo [SETUP] 首次运行，正在安装 npm 依赖...
    call npm install
    if %ERRORLEVEL% neq 0 (
        echo [ERR] npm install 失败
        pause
        exit /b 1
    )
)

REM ── 验证 Python 模块导入 ──
echo [VERIFY] 验证 Python 模块导入...
python -c "import config; print('  config.IS_PORTABLE_LAYOUT =', config.IS_PORTABLE_LAYOUT)"
if %ERRORLEVEL% neq 0 (
    echo [ERR] Python 模块导入失败
    echo [HINT] 请运行 pip install -r requirements.txt
    pause
    exit /b 1
)

echo [OK] 启动服务...
echo [OK] 浏览器访问: http://localhost:3100
echo [OK] 按 Ctrl+C 停止服务
echo.

node server.js
pause
