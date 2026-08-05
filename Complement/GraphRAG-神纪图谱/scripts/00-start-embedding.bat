@echo off
chcp 65001 >nul
REM Start local bge-m3 embedding service (llama-server) for GraphRAG.
REM Configurable via env: LLAMA_SERVER, BGE_MODEL, EMBED_PORT
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-embedding.ps1"
pause
