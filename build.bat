@echo off
REM ============================================================================
REM Build LabController.exe from the Python source using PyInstaller.
REM
REM Usage:  build.bat
REM Output: dist\LabController.exe  +  dist\config.json (editable)
REM ============================================================================
setlocal

REM Prefer the project virtualenv if it exists, otherwise fall back to PATH.
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Ensuring PyInstaller is installed...
"%PY%" -m pip install --quiet "pyinstaller>=6.0" || goto :error

echo Building LabController.exe...
"%PY%" -m PyInstaller --noconfirm --clean LabController.spec || goto :error

echo Copying editable config.json next to the executable...
copy /Y "src\configs\config.json" "dist\config.json" >nul || goto :error

echo.
echo Build complete:
echo   dist\LabController.exe   (double-click to run)
echo   dist\config.json         (edit COM ports / settings here)
echo.
echo Distribute the two files together.
goto :eof

:error
echo.
echo BUILD FAILED. See the output above.
exit /b 1
