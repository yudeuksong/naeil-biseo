@echo off
rem Double-click to build dist\NaeilBiseo\NaeilBiseo.exe (ASCII-only file).
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\build_windows.ps1" %*
pause
