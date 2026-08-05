@echo off
chcp 65001 >nul
REM Self-test: run a global search query against the portable index.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0selfcheck-query.ps1"
pause
