@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
echo [1] GUI
echo [2] Mirror preview sample
echo [3] Project shell
echo.
choice /C 123 /N /M "Select: "
if errorlevel 3 goto shell
if errorlevel 2 goto preview
if errorlevel 1 goto gui
:gui
call launcher_gui.cmd
goto end
:preview
python system_core\main.py --mirror-preview demo_local --json
if not defined AUDION_NO_PAUSE pause
goto end
:shell
call launcher_project.cmd
:end
endlocal
