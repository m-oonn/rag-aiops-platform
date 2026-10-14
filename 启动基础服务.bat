@echo off
chcp 936 >nul
title 基础服务控制台
cd /d "%~dp0"
echo ============================================
echo   基础服务控制台
echo   基础栈: Redis / RabbitMQ / Milvus / MinIO
echo   可观测性: Prometheus / Elasticsearch
echo ============================================
echo.
docker info >nul 2>&1
if errorlevel 1 (
    echo [X] Docker 引擎未运行。
    echo     请先启动 Docker Desktop（开始菜单搜索 Docker Desktop）,
    echo     等鲸鱼图标稳定后, 再重新双击本脚本。
    echo.
    if not "%~1"=="nopause" pause
    exit /b 1
)
if /i "%~1"=="stop" goto do_stop
if /i "%~1"=="status" goto do_status
:do_start
echo [1/3] 启动基础服务(首次会自动下载镜像, 需要等待)...
docker compose -f docker/docker-compose.yml up -d redis rabbitmq milvus-standalone
echo.
echo [2/3] 启动可观测性栈(Prometheus / Elasticsearch)...
docker compose -f docker/docker-compose.observability.yml up -d
echo.
echo [3/3] 当前状态:
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.observability.yml ps
echo.
echo 用法: 双击=启动并查看状态  ^|  命令行 "%0 stop"=停止  ^|  "%0 status"=只看状态
echo 提示: 演示系统(前端/后端)用 start_demo.bat 启动。
if not "%~1"=="nopause" pause
exit /b 0
:do_stop
docker compose -f docker/docker-compose.yml stop
docker compose -f docker/docker-compose.observability.yml stop
echo 已停止全部基础服务(数据保留在卷里, 下次启动仍在)。
if not "%~1"=="nopause" pause
exit /b 0
:do_status
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.observability.yml ps
if not "%~1"=="nopause" pause
exit /b 0
