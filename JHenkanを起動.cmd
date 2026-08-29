@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  start "" "%~dp0install.cmd"
  exit /b
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.pyw"
