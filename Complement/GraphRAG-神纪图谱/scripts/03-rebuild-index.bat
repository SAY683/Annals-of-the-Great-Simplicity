@echo off
chcp 65001 >nul
REM Rebuild the GraphRAG index from input (needs LLM + embedding services).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rebuild-index.ps1"
pause
