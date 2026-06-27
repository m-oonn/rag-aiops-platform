#!/bin/bash
# 简历版 AIOps 一键启动: MCP 指标服务 + MCP 日志服务 + FastAPI 后端
# 用法: bash scripts/demo.sh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export USE_TORCH=0

echo "=== 启动 MCP Monitor Server (127.0.0.1:8004) ==="
.venv/Scripts/python.exe mcp_servers/monitor_server.py &
MONITOR_PID=$!
echo "  PID $MONITOR_PID"

echo "=== 启动 MCP CLS Server (127.0.0.1:8003) ==="
.venv/Scripts/python.exe mcp_servers/cls_server.py &
CLS_PID=$!
echo "  PID $CLS_PID"

sleep 2

echo "=== 启动 FastAPI 后端 (0.0.0.0:8000) ==="
echo "  SSE 诊断端点: POST http://localhost:8000/api/v1/aiops"
echo "  Swagger 文档:  http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止全部服务"

trap "echo '停止...'; kill $MONITOR_PID $CLS_PID 2>/dev/null; exit 0" INT TERM

.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

wait
