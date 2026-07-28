@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not "%~1"=="" (
  python both_thesis_report.py %*
  set "REPORT_EXIT=!ERRORLEVEL!"
  pause
  exit /b !REPORT_EXIT!
)

echo Both-Thesis Paper Trade Report
echo.
echo 1. All trades
echo 2. Pick a saved date
echo 3. Type a date
echo.
set /p REPORT_CHOICE=Choose option [1]: 

if "%REPORT_CHOICE%"=="" set REPORT_CHOICE=1

if "%REPORT_CHOICE%"=="1" (
  python both_thesis_report.py
  goto done
)

if "%REPORT_CHOICE%"=="2" (
  echo.
  echo Saved dates:
  set "DATES_FILE=%TEMP%\both_thesis_dates_%RANDOM%.txt"
  python both_thesis_report.py --list-dates > "!DATES_FILE!"
  set COUNT=0
  for /f "usebackq delims=" %%D in ("!DATES_FILE!") do (
    set /a COUNT+=1
    set DATE_!COUNT!=%%D
    echo !COUNT!. %%D
  )
  del "!DATES_FILE!" >nul 2>nul
  if "!COUNT!"=="0" (
    echo No saved trade dates were found.
    goto done
  )
  echo.
  set /p DATE_CHOICE=Choose date number: 
  if "!DATE_CHOICE!"=="" goto done
  call set "REPORT_DATE=%%DATE_!DATE_CHOICE!%%"
  if "!REPORT_DATE!"=="" (
    echo Invalid date choice.
    goto done
  )
  python both_thesis_report.py --date !REPORT_DATE!
  goto done
)

if "%REPORT_CHOICE%"=="3" (
  echo.
  set /p REPORT_DATE=Enter date YYYY-MM-DD: 
  if "!REPORT_DATE!"=="" goto done
  python both_thesis_report.py --date !REPORT_DATE!
  goto done
)

echo Invalid option.

:done
pause
