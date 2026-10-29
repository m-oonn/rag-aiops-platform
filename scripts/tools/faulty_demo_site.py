#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""带故障的演示网站（诊断 Agent 靶场）—— 2026-10-09 建立

故意埋入 4 类可被 check_website 探测到的**真实故障**，用于演示/验收诊断能力：

故障清单（按探测序号）：
  1. /logo.png            → 404（首页引用的资源丢失）
  2. /api/orders/slow     → 响应慢（故意 sleep 4.2s，触发"响应偏慢"判定）
  3. /api/orders/500      → HTTP 500（服务端错误）
  4. /health/ready        → HTTP 403（健康检查接口被误配为拒绝访问）
  5. 首页缺少安全响应头（X-Content-Type-Options / X-Frame-Options）
     → check_website 的 --deep 安全检查会报告

正常对照：/ 首页、/about、/api/orders/ok 均为 200 且快速响应。

用法：
    python scripts/tools/faulty_demo_site.py            # 默认 127.0.0.1:8090
    python scripts/tools/faulty_demo_site.py 8091       # 指定端口
"""
from __future__ import annotations

import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# 故意慢的接口等待秒数
SLOW_SECONDS = 4.2

HTML_HOME = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>星辰商城 · 演示站点</title>
  <link rel="icon" href="/logo.png">
</head>
<body>
  <h1>星辰商城（演示站点）</h1>
  <p>这是一个商城系统的演示站点，含商品浏览与订单服务。</p>
  <img src="/logo.png" alt="站点 Logo">
  <h2>功能入口</h2>
  <ul>
    <li><a href="/about">关于我们</a></li>
    <li><a href="/api/orders/ok">订单列表</a></li>
    <li><a href="/api/orders/slow">订单统计报表</a></li>
    <li><a href="/api/orders/500">订单导出</a></li>
    <li><a href="/health/ready">服务健康检查</a></li>
  </ul>
</body>
</html>"""


class FaultyHandler(BaseHTTPRequestHandler):
    server_version = "FaultyDemo/1.0"

    def log_message(self, fmt, *args):  # 静音默认日志
        pass

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/html; charset=utf-8",
              extra_headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # ⚠️ 故障 5：故意不发送安全响应头（X-Content-Type-Options / X-Frame-Options）
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]

        # ── 正常页面 ──
        if p in ("/", "/index.html"):
            return self._send(200, HTML_HOME.encode("utf-8"))
        if p == "/about":
            return self._send(200, b"<html><head><title>About</title></head><body>about</body></html>")
        if p == "/api/orders/ok":
            return self._send(200, b'{"status":"ok","orders":3}', "application/json")

        # ── 故障 1：资源丢失 ──
        if p == "/logo.png":
            return self._send(404, b"<html><body>404 Not Found</body></html>")

        # ── 故障 2：响应慢 ──
        if p == "/api/orders/slow":
            time.sleep(SLOW_SECONDS)
            return self._send(200, b'{"status":"ok","note":"slow"}', "application/json")

        # ── 故障 3：服务端错误 ──
        if p == "/api/orders/500":
            return self._send(500, b"<html><body>Internal Server Error</body></html>")

        # ── 故障 4：健康检查被拒 ──
        if p == "/health/ready":
            return self._send(403, b"<html><body>403 Forbidden</body></html>")

        return self._send(404, b"<html><body>404</body></html>")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    server = HTTPServer(("127.0.0.1", port), FaultyHandler)
    print(f"带故障的演示站点已启动: http://127.0.0.1:{port}/")
    print("已埋故障: /logo.png(404) | /api/orders/slow(慢4.2s) | /api/orders/500(500) | "
          "/health/ready(403) | 缺安全响应头")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()
