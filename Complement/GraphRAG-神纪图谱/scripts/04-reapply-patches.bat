@echo off
chcp 65001 >nul
REM Re-apply GraphRAG site-packages patches (run after upgrading graphrag).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0reapply-patches.ps1"
pause
