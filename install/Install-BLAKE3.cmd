@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "BASE_DIR=%~dp0.."
set "PYTHON_EXE=%BASE_DIR%\runtime\python.exe"
set "WHEELHOUSE_DIR=%BASE_DIR%\wheelhouse"

echo ======================================================================
echo   AUDION HUB MANAGER - BLAKE3 INSTALL
echo ======================================================================
echo Root:       %BASE_DIR%
echo Python:     %PYTHON_EXE%
echo Wheelhouse: %WHEELHOUSE_DIR%
echo.

if not exist "%PYTHON_EXE%" goto ERR_PYTHON

"%PYTHON_EXE%" -m pip --version >nul 2>nul
if errorlevel 1 goto ERR_PIP

if exist "%WHEELHOUSE_DIR%\blake3*.whl" goto INSTALL_LOCAL
goto INSTALL_ONLINE

:INSTALL_LOCAL
echo Installing BLAKE3 from local wheelhouse...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --no-index --find-links="%WHEELHOUSE_DIR%" --upgrade blake3
if errorlevel 1 goto ERR_INSTALL
goto DONE

:INSTALL_ONLINE
echo Local BLAKE3 wheel was not found.
echo Installing BLAKE3 from Python package index...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --upgrade blake3
if errorlevel 1 goto ERR_INSTALL
goto DONE

:DONE
echo.
echo [OK] BLAKE3 install/update finished.
echo [INFO] Run builder step [71] VERIFY / DOCTOR for diagnostics.
exit /b 0

:ERR_PYTHON
echo [ERROR] runtime\python.exe was not found.
echo [INFO] Run builder step [01] PYTHON ENV CMD first.
exit /b 1

:ERR_PIP
echo [ERROR] pip is not available in portable runtime.
echo [INFO] Run builder step [01] PYTHON ENV CMD or [09] PORTABLE OFFLINE first.
exit /b 1

:ERR_INSTALL
echo [ERROR] Failed to install BLAKE3.
exit /b 1
