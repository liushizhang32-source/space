@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\check_environment.ps1
.runtime\app\Scripts\python.exe scripts\ipad_control.py check
pause
