@echo off
setlocal

cd /d "%~dp0"

if exist "%~dp0scripts\codex_bridge.local.cmd" (
    call "%~dp0scripts\codex_bridge.local.cmd"
)

if not defined PAPER_READER_HOST set "PAPER_READER_HOST=127.0.0.1"
if not defined PAPER_READER_PORT set "PAPER_READER_PORT=8790"
if not defined CODEX_BRIDGE_HOST set "CODEX_BRIDGE_HOST=127.0.0.1"
if not defined CODEX_BRIDGE_PORT set "CODEX_BRIDGE_PORT=8765"

set "APP_BROWSER_HOST=%PAPER_READER_HOST%"
if /I "%APP_BROWSER_HOST%"=="0.0.0.0" set "APP_BROWSER_HOST=127.0.0.1"
set "APP_URL=http://%APP_BROWSER_HOST%:%PAPER_READER_PORT%"
set "DEFAULT_BRIDGE_URL=http://%CODEX_BRIDGE_HOST%:%CODEX_BRIDGE_PORT%/v1"
if not defined PAPER_READER_BRIDGE_URL (
    set "PAPER_READER_EFFECTIVE_BRIDGE_URL=%DEFAULT_BRIDGE_URL%"
) else (
    set "PAPER_READER_EFFECTIVE_BRIDGE_URL=%PAPER_READER_BRIDGE_URL%"
)

set "VENV_PYTHON=.venv\Scripts\python.exe"

where python >nul 2>nul
if errorlevel 1 (
    echo [paper-reader-agent] Python not found on PATH.
    echo Please install Python 3.12+ and make sure the "python" command is available.
    pause
    exit /b 1
)

if not exist "%VENV_PYTHON%" (
    echo [paper-reader-agent] Creating repo-local virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [paper-reader-agent] Standard venv creation failed. Trying fallback...
        python -m venv --without-pip .venv
        if errorlevel 1 goto setup_failed

        python -m pip --python "%VENV_PYTHON%" install pip
        if errorlevel 1 goto setup_failed
    )
)

echo [paper-reader-agent] Installing/updating dependencies in .venv...
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

if /I "%PAPER_READER_DRY_RUN%"=="1" (
    echo [paper-reader-agent] Dry run complete.
    exit /b 0
)

if /I not "%PAPER_READER_SKIP_BRIDGE%"=="1" (
    if /I "%PAPER_READER_EFFECTIVE_BRIDGE_URL%"=="%DEFAULT_BRIDGE_URL%" (
        call :wait_for_bridge 1
        if not "%BRIDGE_READY%"=="1" (
            echo [paper-reader-agent] Starting bundled Codex bridge...
            start "paper-reader-agent bridge" cmd /c call "%~dp0start_codex_bridge.cmd"
            call :wait_for_bridge 15
            if not "%BRIDGE_READY%"=="1" (
                echo [paper-reader-agent] Bridge did not become ready in time.
                echo [paper-reader-agent] Check the bridge window for codex executable errors or set CODEX_BRIDGE_COMMAND in scripts\codex_bridge.local.cmd.
                echo [paper-reader-agent] The app will still start, but AI actions may fail until the bridge is ready.
            )
        )
    ) else (
        echo [paper-reader-agent] Custom bridge URL detected; skipping bundled bridge auto-start.
    )
)

if /I not "%PAPER_READER_SKIP_BROWSER%"=="1" (
    echo [paper-reader-agent] Opening browser...
    start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%APP_URL%'"
)

echo [paper-reader-agent] Starting app at %APP_URL%
"%VENV_PYTHON%" run.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [paper-reader-agent] App exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%

:setup_failed
echo.
echo [paper-reader-agent] Setup failed.
echo Please check the messages above, then try again.
pause
exit /b 1

:wait_for_bridge
set "BRIDGE_READY=0"
set "BRIDGE_WAIT_COUNT=%~1"
if "%BRIDGE_WAIT_COUNT%"=="" set "BRIDGE_WAIT_COUNT=1"
for /L %%I in (1,1,%BRIDGE_WAIT_COUNT%) do (
    powershell -NoProfile -Command "$ErrorActionPreference='Stop'; try { $response = Invoke-RestMethod -Uri 'http://%CODEX_BRIDGE_HOST%:%CODEX_BRIDGE_PORT%/v1/health' -TimeoutSec 2; if ($response.ok) { exit 0 } } catch { }; exit 1" >nul 2>nul
    if not errorlevel 1 (
        set "BRIDGE_READY=1"
        goto :eof
    )
    timeout /t 1 /nobreak >nul
)
exit /b 0
