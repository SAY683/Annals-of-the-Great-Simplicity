@echo off
chcp 65001 >nul
pushd "%~dp0"

:: 检查 Python 可用性
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 python，请确保 Python 已加入系统 PATH。
    pause
    popd
    exit /b 1
)

echo [*] 启动 EDM-Takens Web MVP ...
echo [*] 工作目录: %cd%
python start_mvp.py

if %errorlevel% neq 0 (
    echo [ERROR] 启动脚本异常退出。
    pause
)

popd
