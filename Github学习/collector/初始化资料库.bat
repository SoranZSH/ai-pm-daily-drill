@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ============================================================
echo  资料库初始化：回溯最近 90 天，按正常巡检 5 倍规模收录
echo  1. 现有采集记录、采集包、资料库移到 Github学习\采集备份_时间戳（不删除）
echo  2. 全新开始采集，预计 30-45 分钟，请保持联网、不要关闭窗口
echo  当前题库 不受影响。
echo ============================================================
echo.
if exist collect.lock (
  echo 发现 collect.lock：可能有采集正在运行。请稍后再试；
  echo 如果确定没有在运行，可以删除 collector\collect.lock 后重新双击。
  pause
  exit /b 1
)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%i
set BK=..\采集备份_%TS%
mkdir "%BK%"
if exist ..\state.db move /Y ..\state.db "%BK%\" >nul
if exist ..\state.db.bak-M5 move /Y ..\state.db.bak-M5 "%BK%\" >nul
mkdir "%BK%\采集包"
if exist ..\采集包\*.* move /Y ..\采集包\*.* "%BK%\采集包\" >nul
if exist ..\资料库 move ..\资料库 "%BK%\资料库" >nul
echo 旧记录已备份到 Github学习\采集备份_%TS%
echo.
python collect.py --init --days 90 --scale 5 --verbose
echo.
echo 退出码 %ERRORLEVEL%（0 = 成功）。结果见 Github学习\资料库 和 Github学习\采集包。
echo 完成后回到对话里告诉 Claude 一声，它会检查这次收录的质量。
pause
