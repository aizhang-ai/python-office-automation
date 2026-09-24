@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   文件自动整理归档
echo ==========================================
echo.
echo 第 1 步：先试跑（只出清单，不会动你的文件）
echo.
python file_tidy.py --dry-run
echo.
echo ------------------------------------------
echo 清单在 run-report.txt 里，也可以直接打开看。
echo.
set /p GO=清单没问题的话，输入 y 回车正式执行（默认复制模式，原文件不动）：
if /i not "%GO%"=="y" goto :end
echo.
python file_tidy.py
echo.
echo 完成。结果在 output 文件夹，报告在 run-report.txt
:end
echo.
pause
