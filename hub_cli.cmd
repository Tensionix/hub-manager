@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem Audion Hub Manager: the console command. A button of the window and this command run the
rem same thing; every command prints one JSON document.
rem
rem   hub_cli.cmd projects list
rem   hub_cli.cmd mirror plan demo_local
rem   hub_cli.cmd mirror apply demo_local --apply
rem   hub_cli.cmd check-paths demo_local --layer source README.md output\report.pdf
rem   hub_cli.cmd lab create
rem   hub_cli.cmd canon
rem
rem The whole list: hub_cli.cmd --help, or the head of system_core\cli.py.
rem Exit codes: 0 done, 1 a bad result or a failure, 2 a wrong call (nothing changed).

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"

set "PYTHON_CMD="
if exist "%BASE_DIR%\runtime\python.exe" set "PYTHON_CMD=%BASE_DIR%\runtime\python.exe"
if not defined PYTHON_CMD if exist "%BASE_DIR%\runtime\python\python.exe" set "PYTHON_CMD=%BASE_DIR%\runtime\python\python.exe"
rem Not a block in brackets: a path with a bracket in it - "Program Files (x86)" - would close it.
if not defined PYTHON_CMD goto NO_PYTHON

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PYTHON_CMD%" -u "%BASE_DIR%\system_core\cli.py" %*
exit /b %ERRORLEVEL%

:NO_PYTHON
echo {"ok": false, "error": "Python of the program was not found: %BASE_DIR:\=\\%\\runtime\\python.exe - build the environment: builder_main.cmd", "kind": "failed"}
exit /b 1
