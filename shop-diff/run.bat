@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   多店铺商品信息核对
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
    echo     已生成 config.json，本次按示例数据（input 目录下的两份演示表）跑。
    echo     要换成你自己的表：把 CSV 放进 input 目录，再用记事本改 config.json。
    echo.
)

python shop_diff.py %*
echo.
echo --------------------------------------------
echo 报告在 output\latest-report.txt
echo 逐条差异在 output\diff-detail.csv
echo 汇总在 output\summary.csv
echo --------------------------------------------
pause
