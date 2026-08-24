@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo Audion Hub Manager project shell
echo.
echo Commands:
echo   launcher_gui.cmd
echo   python system_core\main.py --mirror-preview demo_local --json
echo   python -m pytest tests
cmd /k
