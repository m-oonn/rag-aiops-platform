@echo off
chcp 936 >nul
title 运维诊断 Agent - 演示控制台
cd /d "%~dp0"
echo ============================================================
echo   运维诊断 Agent 演示环境
echo ============================================================
echo.
echo   [1] 启动全部服务（后端 + 前端界面）
echo   [2] 只启动后端（终端演示用，不开界面）
echo   [3] 停止全部服务
echo   [4] 查看运行状态
echo.
set /p choice=请输入数字并回车:
if "%choice%"=="1" goto startall
if "%choice%"=="2" goto startbe
if "%choice%"=="3" goto stop
if "%choice%"=="4" goto status
echo 输入无效
pause
exit /b

:startall
python scripts\launch_demo.py start
goto done

:startbe
python scripts\launch_demo.py start --no-frontend --no-browser
goto done

:stop
python scripts\launch_demo.py stop
goto done

:status
python scripts\launch_demo.py status
goto done

:done
echo.
pause
