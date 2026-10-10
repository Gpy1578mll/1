@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist ".venv312\Scripts\python.exe" goto use_venv312
if exist ".venv\Scripts\python.exe" goto use_venv
echo Python environment not found. Expected .venv312 or .venv in the project folder.
pause
exit /b 1
:use_venv312
set "ENTITY_PYTHON=%~dp0.venv312\Scripts\python.exe"
goto run_app
:use_venv
set "ENTITY_PYTHON=%~dp0.venv\Scripts\python.exe"
:run_app
set "PYTHONUTF8=1"
"%ENTITY_PYTHON%" "%~dp0scripts\start_yandex.py"
set "ENTITY_EXIT=%ERRORLEVEL%"
if not "%ENTITY_EXIT%"=="0" pause
exit /b %ENTITY_EXIT%
