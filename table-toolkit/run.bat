@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 table_tool.py %*
) else (
  python table_tool.py %*
)
echo.
pause
