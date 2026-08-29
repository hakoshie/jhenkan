@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.pyw"
exit /b 0

:error
echo.
echo JHenkan no install ni shippai shimashita.
pause
exit /b 1
