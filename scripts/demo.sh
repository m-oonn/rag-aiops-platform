#!/bin/bash
# 全栈一键启动: MCP 指标 + MCP 日志 + FastAPI 后端 + Vue 前端
# 用法: bash scripts/demo.sh
#
# 前置: .venv 已建 + .env 已配 DASHSCOPE_API_KEY/SECRET_KEY + frontend/node_modules 已装
# 说明: Milvus/Redis 等 Docker 服务不是必需 —— 不可用时自动降级,不阻断演示。

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export USE_TORCH=0

PIDS=()

cleanup() {
    echo ""
    echo "停止全部服务..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    exit 0
}
trap cleanup INT TERM

echo "=== [1/4] MCP Monitor Server (127.0.0.1:8104) ==="
.venv/Scripts/python.exe mcp_servers/monitor_server.py &
PIDS+=($!)

echo "=== [2/4] MCP CLS Server (127.0.0.1:8103) ==="
.venv/Scripts/python.exe mcp_servers/cls_server.py &
PIDS+=($!)

sleep 2

echo "=== [3/4] FastAPI 后端 (0.0.0.0:8200) ==="
.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 8200 --reload &
PIDS+=($!)

echo "=== [4/4] Vue 前端 (5173) ==="
if [ -d frontend/node_modules ]; then
    ( cd frontend && npm run dev ) &
    PIDS+=($!)
else
    echo "  ⚠️ frontend/node_modules 缺失,跳过前端。先跑: cd frontend && npm install"
fi

sleep 3
echo ""
echo "════════════════════════════════════════════════"
echo "  前端界面 : http://localhost:5173"
echo "  API 文档 : http://localhost:8200/docs"
echo "  诊断端点 : POST http://localhost:8200/api/v1/aiops"
echo "════════════════════════════════════════════════"
echo "按 Ctrl+C 停止全部服务"

wait
