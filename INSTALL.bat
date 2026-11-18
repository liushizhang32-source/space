@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install_all.ps1
if errorlevel 1 exit /b 1
.runtime\app\Scripts\python.exe -m playwright install webkit
pause
