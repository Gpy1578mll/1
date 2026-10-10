@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "ENTITY_PYTHON="
if exist ".venv312\Scripts\python.exe" set "ENTITY_PYTHON=.venv312\Scripts\python.exe"
if not defined ENTITY_PYTHON if exist ".venv\Scripts\python.exe" set "ENTITY_PYTHON=.venv\Scripts\python.exe"
if not defined ENTITY_PYTHON (
  echo Не найдено окружение .venv312 или .venv. Установите зависимости проекта.
  pause
  exit /b 1
)
"%ENTITY_PYTHON%" "scripts\start_gemini.py"
set "ENTITY_EXIT=%ERRORLEVEL%"
if not "%ENTITY_EXIT%"=="0" pause
exit /b %ENTITY_EXIT%
