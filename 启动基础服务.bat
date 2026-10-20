@echo off
chcp 936 >nul
title 基础服务控制台（兼容入口）
cd /d "%~dp0"
echo ============================================
echo   基础服务（Docker）：Redis / RabbitMQ / Milvus
echo   可观测性：Prometheus / Elasticsearch
echo.
echo   提示：已并入 start_demo.bat 统一控制台，本脚本保留专用入口
echo   用法：双击=启动  ^|  stop=停止  ^|  status=只看状态
echo ============================================
set "ACT=up"
if /i "%~1"=="up" set "ACT=up"
if /i "%~1"=="stop" set "ACT=stop"
if /i "%~1"=="status" set "ACT=status"
python scripts\launch_demo.py infra %ACT%
set "RC=%errorlevel%"
if /i not "%~1"=="nopause" if /i not "%~2"=="nopause" pause
exit /b %RC%
