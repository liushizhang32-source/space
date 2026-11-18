@echo off
cd /d "%~dp0"
set "IPAD_START_BAT=%~f0"
net session >nul 2>&1
if errorlevel 1 (
 powershell.exe -NoProfile -Command "Start-Process -FilePath $env:IPAD_START_BAT -Verb RunAs"
 exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_ipad.ps1
pause
