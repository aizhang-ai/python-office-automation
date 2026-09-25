@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   网站 / 接口可用性监控
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [!] 没找到 Python。
    echo     去 https://www.python.org/downloads/ 下载安装，
    echo     安装时一定勾选 "Add Python to PATH"，装完重新双击本文件。
    echo.
    pause
    exit /b 1
)

if not exist "config.json" (
    echo [!] 没有 config.json，先用示例配置跑一遍看看效果。
    copy /y "config.example.json" "config.json" >nul
    echo     已生成 config.json，本次按示例地址（example.com / 百度）演示。
    echo     要改成你自己的地址，用记事本打开 config.json 编辑即可。
    echo.
)

python uptime_monitor.py %*
echo.
echo --------------------------------------------
echo 报告在 output\latest-report.txt
echo 逐次明细在 output\uptime-日期.csv
echo --------------------------------------------
pause
