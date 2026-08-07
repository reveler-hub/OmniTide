@echo off
REM Sets up a Python virtual environment and installs OmniTide's dependencies.
setlocal

set "SCRIPT_DIR=%~dp0"
set "ENV_DIR=%SCRIPT_DIR%OmniTide_Env"

echo Creating virtual environment at %ENV_DIR%...
python -m venv "%ENV_DIR%"
if errorlevel 1 (
    echo Failed to create virtual environment. Is Python installed and on PATH?
    exit /b 1
)

echo Installing dependencies...
call "%ENV_DIR%\Scripts\pip.exe" install --upgrade pip
call "%ENV_DIR%\Scripts\pip.exe" install -r "%SCRIPT_DIR%requirements.txt"

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo Warning: ffmpeg not found on PATH.
    echo Download it from ffmpeg.org so downloads remux correctly.
)

echo.
echo Setup complete.
echo Activate the environment with:
echo   %ENV_DIR%\Scripts\activate
echo Then log in to Tidal with:
echo   python OmniTide.py login

endlocal
