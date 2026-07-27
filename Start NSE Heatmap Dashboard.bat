@echo off
cd /d "%~dp0"

set "PORT=8775"

echo Closing any existing NSE Heatmap Dashboard on port %PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo Stopping process %%P
  taskkill /F /PID %%P >nul 2>nul
)

echo Starting NSE Heatmap Dashboard...
python run.py
