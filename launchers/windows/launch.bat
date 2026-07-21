@echo off
setlocal
cd /d "%~dp0\..\.."

rem Run uvicorn in background via PowerShell without opening a CMD console window
powershell -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -Command "Start-Process venv\Scripts\python.exe -ArgumentList '-m uvicorn rachel.proxy:app --host 0.0.0.0 --port 8000' -WindowStyle Hidden"

rem Wait 2 seconds for server boot then open browser
timeout /t 2 /nobreak >nul
start http://localhost:8000
