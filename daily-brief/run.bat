@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo   每日经营数据简报
echo ==========================================
echo.
echo 第 1 步：先试算（只打印，不写文件，不动你的数据）
echo.
python daily_brief.py --dry-run
echo.
echo ------------------------------------------
echo 上面这版就是会发到群里的样子。
echo.
set /p GO=没问题的话，输入 y 回车正式生成日报（写到 output 文件夹）：
if /i not "%GO%"=="y" goto :end
echo.
python daily_brief.py
echo.
echo 完成。日报在 output\daily-brief.txt（可直接复制到群里）
echo.
set /p PUSH=要不要推到群里？（需要先在 config.json 里填好 webhook 地址）y/n：
if /i not "%PUSH%"=="y" goto :end
python daily_brief.py --push
:end
echo.
pause
