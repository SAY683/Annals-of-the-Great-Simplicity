@echo off
chcp 65001 >nul
REM Start GraphRAG MCP server (portable path resolution).
REM Configurable via env: GRAPHRAG_PYTHON
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-mcp.ps1"
pause
