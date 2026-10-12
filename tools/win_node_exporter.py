#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地 Windows 用的 node_exporter 兼容导出器(真实主机指标,非 Mock)。

为什么需要它: node_exporter 官方只发布 linux/darwin 等平台, **没有 Windows 构建**,
而本项目 settings.py 里的 PromQL 模板(instance 过滤 + node_cpu_seconds_total /
node_memory_*_bytes)是按 node_exporter 指标名写的。为了让"本地真实链路"与生产
Linux 环境保持**同一套 PromQL 模板**(无需改代码/改配置),这里用一个纯标准库
(ctypes 直接调 Windows API)的导出器,按 node_exporter 的指标名与语义暴露**真实**
的本机 CPU / 内存数据。

指标是真实的: CPU 来自 GetSystemTimes(累计各模式秒数),内存来自 GlobalMemoryStatusEx。
Prometheus 抓取本导出器两次并把 instance 重写成服务名,即可命中
instance=~"{service}.*" 的模板 —— 与 docker/prometheus/prometheus.yml 拓扑一致。

用法:
    python tools/win_node_exporter.py            # 默认 127.0.0.1:9100
    python tools/win_node_exporter.py 9101       # 指定端口
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Windows API 绑定 ────────────────────────────────────────────────────
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                    ctypes.POINTER(FILETIME)]
kernel32.GetSystemTimes.restype = wintypes.BOOL
kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL

_100NS_PER_SEC = 10_000_000.0


def _filetime_to_seconds(ft: FILETIME) -> float:
    ticks = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return ticks / _100NS_PER_SEC


def cpu_seconds_by_mode() -> dict:
    """累计 CPU 秒数(按模式),语义与 node_exporter 对齐。

    GetSystemTimes 的 kernel 时间**包含** idle,故 system = kernel - idle。
    返回值已按逻辑核数归一化: GetSystemTimes 给的是**所有核累加**的时间,直接暴露会让
    rate() 超过 1(8 核时约 8 倍),导致 PromQL 算出负的占用率。除以核数后,单条序列的
    rate 即"平均每核每秒",与 node_exporter 逐核序列做 avg() 的结果一致。
    """
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    cores = float(os.cpu_count() or 1)
    idle_s = _filetime_to_seconds(idle) / cores
    kernel_s = _filetime_to_seconds(kernel) / cores
    user_s = _filetime_to_seconds(user) / cores
    return {"idle": idle_s, "system": max(kernel_s - idle_s, 0.0), "user": user_s}


def memory_bytes() -> dict:
    """物理内存总量 / 可用量(字节)。"""
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"total": float(st.ullTotalPhys), "available": float(st.ullAvailPhys)}


def render_metrics() -> bytes:
    lines: list[str] = []

    lines.append("# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.")
    lines.append("# TYPE node_cpu_seconds_total counter")
    for mode, secs in cpu_seconds_by_mode().items():
        lines.append(f'node_cpu_seconds_total{{cpu="0",mode="{mode}"}} {secs:.6f}')

    mem = memory_bytes()
    lines.append("# HELP node_memory_MemTotal_bytes Memory information field MemTotal_bytes.")
    lines.append("# TYPE node_memory_MemTotal_bytes gauge")
    lines.append(f"node_memory_MemTotal_bytes {mem['total']:.0f}")
    lines.append("# HELP node_memory_MemAvailable_bytes Memory information field MemAvailable_bytes.")
    lines.append("# TYPE node_memory_MemAvailable_bytes gauge")
    lines.append(f"node_memory_MemAvailable_bytes {mem['available']:.0f}")

    lines.append("# HELP node_exporter_build_info A metric with a constant '1' value.")
    lines.append("# TYPE node_exporter_build_info gauge")
    lines.append('node_exporter_build_info{version="win-shim"} 1')

    return ("\n".join(lines) + "\n").encode("utf-8")


class MetricsHandler(BaseHTTPRequestHandler):
    server_version = "WinNodeExporter/1.0"

    def log_message(self, fmt, *args):  # 静音
        pass

    def do_GET(self):
        if self.path.split("?")[0] != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = render_metrics()
        except Exception as e:  # 采集失败如实报 500,不返回编造指标
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"# error: {e}\n".encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    server = HTTPServer(("127.0.0.1", port), MetricsHandler)
    print(f"node_exporter 兼容导出器已启动: http://127.0.0.1:{port}/metrics (真实主机指标)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()