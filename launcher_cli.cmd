@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist "%ROOT%runtime\python.exe" (
  set "PY=%ROOT%runtime\python.exe"
) else if exist "%ROOT%runtime\python\python.exe" (
  set "PY=%ROOT%runtime\python\python.exe"
) else (
  set "PY=python"
)

cd /d "%ROOT%"
"%PY%" "%ROOT%system_core\main.py" %*
endlocal
