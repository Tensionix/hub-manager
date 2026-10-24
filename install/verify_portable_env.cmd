@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Audion Hub Manager - Verify
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"
rem What a release is checked for. The environment: Python and the packages of
rem the engine (doctor.py). The door: it reads the canon of Git, by which the
rem window draws its buttons. The window: App\ is not built by a build and
rem travels as it is, so it is checked to be in place and to check itself - the
rem door answers it, the canon has its words, the theme its colours of Git.
rem Nothing here needs the .NET SDK.
if not exist "%ROOT%\runtime\python.exe" goto ERR_PYTHON
if not exist "%ROOT%\system_core\doctor.py" goto ERR_DOCTOR
call "%ROOT%\install\Check-CmdEncoding.cmd"
if errorlevel 1 goto ERR_CMD_ENCODING
"%ROOT%\runtime\python.exe" "%ROOT%\system_core\doctor.py" --project-root "%ROOT%"
set "RC=%errorlevel%"
if not "%RC%"=="0" goto DONE_VERIFY
echo.
echo [DOOR] Reading the canon of Git through the console door...
call "%ROOT%\hub_cli.cmd" canon >nul
set "RC=%errorlevel%"
if not "%RC%"=="0" goto ERR_DOOR
echo [OK] The door reads the canon.
echo.
echo [WINDOW] Checking the built window in App\ ...
set "RC=1"
if not exist "%ROOT%\Start.exe" goto ERR_START
"%ROOT%\Start.exe" --self-test
if errorlevel 1 goto ERR_APP
if not exist "%ROOT%\App\AudionPs.exe" goto ERR_APP
set "CHECK_FILE=%TEMP%\hub_manager_self_test_%RANDOM%%RANDOM%.txt"
start "" /wait "%ROOT%\App\AudionHubManager.exe" --self-test --to "%CHECK_FILE%"
rem The exit code alone is not trusted (a check ended by hand ends with -1, and
rem "if errorlevel 1" does not see it): the report has to say so in its last line.
if not exist "%CHECK_FILE%" goto ERR_SELF_CHECK
findstr /B /C:"[OK] all checks passed" "%CHECK_FILE%" >nul
if errorlevel 1 goto ERR_SELF_CHECK
for /f %%N in ('findstr /B /C:"[OK] " "%CHECK_FILE%" ^| find /c /v ""') do echo [OK] The window checked itself: %%N lines of its report are OK.
del /f /q "%CHECK_FILE%" >nul 2>nul
set "RC=0"
:DONE_VERIFY
if not defined AUDION_NO_PAUSE pause
exit /b %RC%
:ERR_PYTHON
echo [ERROR] runtime\python.exe was not found.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_DOCTOR
echo [ERROR] doctor.py was not found.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_CMD_ENCODING
echo [ERROR] CMD encoding check failed.
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_DOOR
echo [ERROR] The console door did not read the canon: hub_cli.cmd canon
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_START
echo [ERROR] Start.exe was not found: install\Build-StartLauncher.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_APP
echo [ERROR] App\AudionHubManager.exe or App\AudionPs.exe was not found: install\Build-App.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1
:ERR_SELF_CHECK
echo [ERROR] The window did not pass its own check: App\AudionHubManager.exe --self-test --to report.txt
if exist "%CHECK_FILE%" findstr /B /C:"[FAIL]" "%CHECK_FILE%"
if not defined AUDION_NO_PAUSE pause
exit /b 1
