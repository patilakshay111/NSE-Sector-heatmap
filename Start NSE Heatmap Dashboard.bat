@echo off
cd /d "%~dp0"

set "DASHBOARD_URL="
set "DASHBOARD_HOST="
set "PORT="

for /f "usebackq tokens=1,* delims==" %%A in (`python -c "import sys; from pathlib import Path; from urllib.parse import urlparse; sys.path.insert(0, str(Path('src').resolve())); from nse_heatmap_dashboard.config import DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_URL; parsed = urlparse(DASHBOARD_URL); print('DASHBOARD_URL=' + str(DASHBOARD_URL)); print('DASHBOARD_HOST=' + str(parsed.hostname or DASHBOARD_HOST)); print('PORT=' + str(parsed.port or DASHBOARD_PORT))"`) do set "%%A=%%B"

if "%PORT%"=="" (
  echo Could not read DASHBOARD_URL from src\nse_heatmap_dashboard\config.py.
  exit /b 1
)

echo Closing any existing NSE Heatmap Dashboard on %DASHBOARD_URL%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  echo Stopping process %%P
  taskkill /F /PID %%P >nul 2>nul
)

echo Starting NSE Heatmap Dashboard at %DASHBOARD_URL%...
python run.py
