@echo off
chcp 936 >nul
title 运维诊断 Agent - 演示控制台
cd /d "%~dp0"
echo ============================================================
echo   运维诊断 Agent 演示环境（统一控制台）
echo ============================================================
echo.
echo   [1] 一键启动全部（基础服务 -^> 等待就绪 -^> 应用栈 + 界面）
echo   [2] 只启动应用层（基础服务已就绪时用，开界面）
echo   [3] 只启动后端（终端演示用，不起界面）
echo   [4] 只启动基础服务（Docker：Redis/MQ/Milvus/Prometheus/ES）
echo   [5] 停止全部（应用栈 -^> 基础服务，数据保留）
echo   [6] 查看状态总览（应用栈 + Docker）
echo.
set /p choice=请输入数字并回车: 
if "%choice%"=="1" goto do_up
if "%choice%"=="2" goto do_start
if "%choice%"=="3" goto do_backend
if "%choice%"=="4" goto do_infra
if "%choice%"=="5" goto do_down
if "%choice%"=="6" goto do_status
echo 输入无效
pause
exit /b

:do_up
python scripts\launch_demo.py up
goto done

:do_start
python scripts\launch_demo.py start
goto done

:do_backend
python scripts\launch_demo.py start --no-frontend --no-browser
goto done

:do_infra
python scripts\launch_demo.py infra up
goto done

:do_down
python scripts\launch_demo.py down
goto done

:do_status
python scripts\launch_demo.py status --all
goto done

:done
echo.
pause
