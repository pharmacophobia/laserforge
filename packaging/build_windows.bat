@echo off
REM =========================================================
REM  LaserForge Windows Standalone Executable Builder (x64)
REM =========================================================

echo ===================================================
echo  LaserForge Windows Portable Builder
echo ===================================================

cd /d "%~dp0\.."

REM Verify python is in PATH
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required but not found in PATH.
    echo Please install Python from https://www.python.org/
    pause
    exit /b 1
)

echo [1/3] Installing/updating build dependencies...
pip install -r requirements-core.txt
pip install pyinstaller

echo [2/3] Compiling standalone LaserForge.exe...
python -m PyInstaller --clean --noconfirm packaging\laserforge_windows.spec

echo [3/3] Finalizing distribution bundle...
if exist "dist\LaserForge-Windows-x64" (
    echo.
    echo ===================================================
    echo  Build Successful!
    echo  Standalone Folder: dist\LaserForge-Windows-x64\
    echo  Launch Executable: dist\LaserForge-Windows-x64\LaserForge.exe
    echo ===================================================
) else (
    echo [ERROR] Build failed. Check compiler log output above.
)

pause
