@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Hub Manager - Builder

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "FZF_EXE=%BASE_DIR%\system_core\fzf.exe"
set "RUNTIME_DIR=%BASE_DIR%\._runtime"
set "MENU_FILE=%RUNTIME_DIR%\builder_menu.txt"
set "RES_FILE=%RUNTIME_DIR%\builder_menu_res.txt"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul

:MAIN
cls
echo ======================================================================
echo   AUDION HUB MANAGER - BUILDER
echo ======================================================================
echo Root: %BASE_DIR%
echo.

if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] PYTHON ENV CMD                      ^| build_cmd        ^| main CMD build script
>>"%MENU_FILE%" echo [02] PYTHON ENV PS                       ^| build_ps         ^| optional PowerShell builder
>>"%MENU_FILE%" echo [03] FZF                                 ^| update_fzf       ^| install/update system_core\fzf.exe
>>"%MENU_FILE%" echo [05] BLAKE3 INSTALL                      ^| install_blake3   ^| install/update Python blake3 package
>>"%MENU_FILE%" echo [06] INIT FOLDERS                         ^| init_folders     ^| create managed project folders
>>"%MENU_FILE%" echo [07] REQUIREMENTS LOCK                    ^| req_lock         ^| refresh pinned dependency lock
>>"%MENU_FILE%" echo [09] PORTABLE OFFLINE                    ^| install_offline  ^| use local runtime and wheelhouse
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [70] CLEAN INSTALL CACHE                 ^| clean_cache      ^| clean install cache/staging/bytecode
>>"%MENU_FILE%" echo [71] VERIFY / DOCTOR                     ^| verify           ^| run doctor.py
>>"%MENU_FILE%" echo [72] CMD ENCODING CHECK                  ^| cmd_encoding     ^| UTF-8 no-BOM CRLF
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [95] OPEN install                        ^| open_install     ^| explorer
>>"%MENU_FILE%" echo [96] OPEN runtime                        ^| open_runtime     ^| explorer
>>"%MENU_FILE%" echo [97] OPEN wheelhouse                     ^| open_wheels      ^| explorer
>>"%MENU_FILE%" echo [98] OPEN licenses                       ^| open_licenses    ^| explorer
>>"%MENU_FILE%" echo [00] EXIT                                ^| exit             ^| close

type "%MENU_FILE%" | "%FZF_EXE%" --prompt="audion@portable-builder > " --pointer=">" --header="Pick step:" --layout=reverse --border="rounded" --info=hidden --margin=1,2 > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW

if /I "%RAW%"=="build_cmd" goto BUILD_CMD
if /I "%RAW%"=="build_ps" goto BUILD_PS
if /I "%RAW%"=="update_fzf" goto UPDATE_FZF
if /I "%RAW%"=="install_blake3" goto INSTALL_BLAKE3
if /I "%RAW%"=="init_folders" goto INIT_FOLDERS
if /I "%RAW%"=="req_lock" goto REQUIREMENTS_LOCK
if /I "%RAW%"=="install_offline" goto INSTALL_OFFLINE
if /I "%RAW%"=="clean_cache" goto CLEAN_CACHE
if /I "%RAW%"=="verify" goto VERIFY
if /I "%RAW%"=="cmd_encoding" goto CMD_ENCODING
if /I "%RAW%"=="open_install" goto OPEN_INSTALL
if /I "%RAW%"=="open_runtime" goto OPEN_RUNTIME
if /I "%RAW%"=="open_wheels" goto OPEN_WHEELS
if /I "%RAW%"=="open_licenses" goto OPEN_LICENSES
if /I "%RAW%"=="exit" exit /b 0
goto MAIN

:FALLBACK_MENU
echo [01] PYTHON ENV CMD
echo [02] PYTHON ENV PS
echo [03] FZF
echo [05] BLAKE3 INSTALL
echo [06] INIT FOLDERS
echo [07] REQUIREMENTS LOCK
echo [09] PORTABLE OFFLINE
echo.
echo [70] CLEAN INSTALL CACHE
echo [71] VERIFY / DOCTOR
echo [72] CMD ENCODING CHECK
echo.
echo [95] OPEN install
echo [96] OPEN runtime
echo [97] OPEN wheelhouse
echo [98] OPEN licenses
echo.
echo [00] EXIT
echo.
set "RAW="
set /p RAW="Select step number or id: "
call :TRIM RAW
if not defined RAW goto MAIN
if /I "%RAW%"=="01" goto BUILD_CMD
if /I "%RAW%"=="1" goto BUILD_CMD
if /I "%RAW%"=="build_cmd" goto BUILD_CMD
if /I "%RAW%"=="02" goto BUILD_PS
if /I "%RAW%"=="2" goto BUILD_PS
if /I "%RAW%"=="build_ps" goto BUILD_PS
if /I "%RAW%"=="03" goto UPDATE_FZF
if /I "%RAW%"=="3" goto UPDATE_FZF
if /I "%RAW%"=="update_fzf" goto UPDATE_FZF
if /I "%RAW%"=="05" goto INSTALL_BLAKE3
if /I "%RAW%"=="5" goto INSTALL_BLAKE3
if /I "%RAW%"=="install_blake3" goto INSTALL_BLAKE3
if /I "%RAW%"=="06" goto INIT_FOLDERS
if /I "%RAW%"=="6" goto INIT_FOLDERS
if /I "%RAW%"=="init_folders" goto INIT_FOLDERS
if /I "%RAW%"=="07" goto REQUIREMENTS_LOCK
if /I "%RAW%"=="7" goto REQUIREMENTS_LOCK
if /I "%RAW%"=="req_lock" goto REQUIREMENTS_LOCK
if /I "%RAW%"=="09" goto INSTALL_OFFLINE
if /I "%RAW%"=="9" goto INSTALL_OFFLINE
if /I "%RAW%"=="install_offline" goto INSTALL_OFFLINE
if /I "%RAW%"=="70" goto CLEAN_CACHE
if /I "%RAW%"=="clean_cache" goto CLEAN_CACHE
if /I "%RAW%"=="71" goto VERIFY
if /I "%RAW%"=="verify" goto VERIFY
if /I "%RAW%"=="72" goto CMD_ENCODING
if /I "%RAW%"=="cmd_encoding" goto CMD_ENCODING
if /I "%RAW%"=="95" goto OPEN_INSTALL
if /I "%RAW%"=="open_install" goto OPEN_INSTALL
if /I "%RAW%"=="96" goto OPEN_RUNTIME
if /I "%RAW%"=="open_runtime" goto OPEN_RUNTIME
if /I "%RAW%"=="97" goto OPEN_WHEELS
if /I "%RAW%"=="open_wheels" goto OPEN_WHEELS
if /I "%RAW%"=="98" goto OPEN_LICENSES
if /I "%RAW%"=="open_licenses" goto OPEN_LICENSES
if /I "%RAW%"=="00" exit /b 0
if /I "%RAW%"=="0" exit /b 0
if /I "%RAW%"=="exit" exit /b 0
goto MAIN

:BUILD_CMD
call "%BASE_DIR%\install\Build_Portable_Env_Build.cmd"
goto MAIN

:BUILD_PS
call "%BASE_DIR%\install\Build_Portable_Env.cmd"
goto MAIN

:INSTALL_BLAKE3
call "%BASE_DIR%\install\Install-BLAKE3.cmd"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:INIT_FOLDERS
call "%BASE_DIR%\install\init_folders.cmd"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:REQUIREMENTS_LOCK
call "%BASE_DIR%\install\Update-Requirements-Lock.cmd"
goto MAIN

:UPDATE_FZF
call "%BASE_DIR%\install\launcher-tools-update_fzf.cmd"
goto MAIN

:INSTALL_OFFLINE
call "%BASE_DIR%\install\install_portable_offline.cmd"
goto MAIN

:CLEAN_CACHE
call "%BASE_DIR%\install\Clean-Install-Cache.cmd"
goto MAIN

:VERIFY
call "%BASE_DIR%\install\verify_portable_env.cmd"
goto MAIN

:CMD_ENCODING
call "%BASE_DIR%\install\Check-CmdEncoding.cmd" -Fix
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OPEN_INSTALL
start "" explorer "%BASE_DIR%\install"
goto MAIN

:OPEN_RUNTIME
start "" explorer "%BASE_DIR%\runtime"
goto MAIN

:OPEN_WHEELS
start "" explorer "%BASE_DIR%\wheelhouse"
goto MAIN

:OPEN_LICENSES
if not exist "%BASE_DIR%\licenses" mkdir "%BASE_DIR%\licenses" >nul 2>nul
start "" explorer "%BASE_DIR%\licenses"
goto MAIN

:TRIM
for /f "tokens=* delims= " %%z in ("!%~1!") do set "%~1=%%z"
:TRIM_R
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto TRIM_R
goto :eof

