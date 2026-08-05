@echo off
chcp 65001 >nul
REM Stop the local bge-m3 embedding service.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-embedding.ps1"
pause
