@echo off
cd /d "%~dp0"
.runtime\app\Scripts\python.exe scripts\ipad_control.py stop
pause
