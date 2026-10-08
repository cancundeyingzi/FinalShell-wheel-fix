@echo off
chcp 65001 >nul 2>nul
setlocal
set "SCRIPT_DIR=%~dp0"
echo ============================================
echo    FinalShell Mouse Wheel Patch - Restore
echo ============================================
echo.
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\python.exe")
if not defined PY (
    echo [X] Python not found. Install Python 3 first.
    pause
    exit /b 1
)
%PY% "%SCRIPT_DIR%patch_finalshell.py" --restore
echo.
pause
