@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo [TRACE Engine Web] Starting via PowerShell wrapper ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo [ERROR] start.ps1 exited with code %errorlevel%.
  echo Common causes: Node.js not installed, port range 3000-3020 in use, or Skill directory missing.
  echo Check work\start.log and work\server.log for details.
)
pause