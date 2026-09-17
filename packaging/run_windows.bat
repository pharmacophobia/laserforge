@echo off
REM =========================================================
REM  LaserForge Windows Direct Launcher
REM =========================================================

cd /d "%~dp0\.."
set PYTHONPATH=%CD%;%PYTHONPATH%

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    pause
    exit /b 1
)

python -m laserforge.main %*
