@echo off
chcp 65001 >nul
REM R46-D fix (ROUND46 P0): Pure English bat to avoid GBK mis-decode.
pushd "%~dp0"

REM -- Python availability check --
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] python not found, ensure Python is in system PATH.
    pause
    popd
    exit /b 1
)

echo [*] Starting EDM-Takens Web MVP ...
echo [*] Working directory: %cd%
python start_mvp.py

if %errorlevel% neq 0 (
    echo [ERROR] Startup script exited abnormally.
    pause
)

popd
