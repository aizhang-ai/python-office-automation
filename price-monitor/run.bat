@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 price_monitor.py %*
) else (
  python price_monitor.py %*
)
echo.
pause
