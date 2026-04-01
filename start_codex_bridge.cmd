@echo off
setlocal

cd /d "%~dp0"

set "REPO_ROOT=%CD%"
set "VENV_PYTHON=%REPO_ROOT%\.venv\Scripts\python.exe"
set "BRIDGE_SCRIPT=%REPO_ROOT%\scripts\codex_bridge.py"
set "BRIDGE_OVERRIDE_FILE=%REPO_ROOT%\scripts\codex_bridge.local.cmd"

if exist "%BRIDGE_OVERRIDE_FILE%" (
    call "%BRIDGE_OVERRIDE_FILE%"
)

if not defined CODEX_BRIDGE_HOST set "CODEX_BRIDGE_HOST=127.0.0.1"
if not defined CODEX_BRIDGE_PORT set "CODEX_BRIDGE_PORT=8765"
if not defined CODEX_BRIDGE_WORKDIR set "CODEX_BRIDGE_WORKDIR=%REPO_ROOT%\scripts\.codex-bridge-workdir"
if not defined CODEX_BRIDGE_SANDBOX set "CODEX_BRIDGE_SANDBOX=read-only"

if not exist "%BRIDGE_SCRIPT%" (
    echo [paper-reader-agent bridge] Bridge script not found: %BRIDGE_SCRIPT%
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [paper-reader-agent bridge] Python not found on PATH.
    echo Please install Python 3.12+ and make sure the "python" command is available.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [paper-reader-agent bridge] Creating repo-local virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [paper-reader-agent bridge] Standard venv creation failed. Trying fallback...
        python -m venv --without-pip .venv
        if errorlevel 1 goto setup_failed

        python -m pip --python "%VENV_PYTHON%" install pip
        if errorlevel 1 goto setup_failed
    )
)

if not defined CODEX_BRIDGE_COMMAND (
    call :resolve_codex_command
    if not defined CODEX_BRIDGE_COMMAND (
        echo [paper-reader-agent bridge] `codex` command not found.
        echo Install Codex CLI and sign in first, or set CODEX_BRIDGE_COMMAND in scripts\codex_bridge.local.cmd.
        pause
        exit /b 1
    )
)

call :bridge_running
if "%BRIDGE_RUNNING%"=="1" (
    echo [paper-reader-agent bridge] Bridge is already running at http://%CODEX_BRIDGE_HOST%:%CODEX_BRIDGE_PORT%/v1
    exit /b 0
)

echo [paper-reader-agent bridge] Starting local Codex bridge...
echo [paper-reader-agent bridge] URL: http://%CODEX_BRIDGE_HOST%:%CODEX_BRIDGE_PORT%/v1
echo [paper-reader-agent bridge] Workdir: %CODEX_BRIDGE_WORKDIR%
echo [paper-reader-agent bridge] Command: %CODEX_BRIDGE_COMMAND%
echo.
"%VENV_PYTHON%" "%BRIDGE_SCRIPT%" --host "%CODEX_BRIDGE_HOST%" --port "%CODEX_BRIDGE_PORT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [paper-reader-agent bridge] Bridge exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%

:setup_failed
echo.
echo [paper-reader-agent bridge] Setup failed.
echo Please check the messages above, then try again.
pause
exit /b 1

:bridge_running
set "BRIDGE_RUNNING=0"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $response = Invoke-RestMethod -Uri 'http://%CODEX_BRIDGE_HOST%:%CODEX_BRIDGE_PORT%/v1/health' -TimeoutSec 2; if ($response.ok) { exit 0 } } catch { }; exit 1" >nul 2>nul
if not errorlevel 1 set "BRIDGE_RUNNING=1"
exit /b 0

:resolve_codex_command
set "CODEX_BRIDGE_COMMAND="
for /f "delims=" %%I in ('where codex 2^>nul') do (
    echo %%~fI | findstr /I /C:"\\WindowsApps\\" >nul
    if errorlevel 1 (
        if /I "%%~xI"==".cmd" if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
        if /I "%%~xI"==".bat" if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
    )
)
if defined CODEX_BRIDGE_COMMAND exit /b 0

for /f "delims=" %%I in ('where codex 2^>nul') do (
    echo %%~fI | findstr /I /C:"\\WindowsApps\\" >nul
    if errorlevel 1 (
        if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
    )
)
if defined CODEX_BRIDGE_COMMAND exit /b 0

for /f "delims=" %%I in ('where codex 2^>nul') do (
    if /I "%%~xI"==".cmd" if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
    if /I "%%~xI"==".bat" if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
)
if defined CODEX_BRIDGE_COMMAND exit /b 0

for /f "delims=" %%I in ('where codex 2^>nul') do (
    if not defined CODEX_BRIDGE_COMMAND set "CODEX_BRIDGE_COMMAND=%%~fI"
)
exit /b 0
