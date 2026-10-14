"""网站/服务真实探测引擎单测(mcp_servers/site_probe.py)。

全部用**本地回环**构造真实场景(起一个本地 HTTP 服务 + 监听/未监听端口),
不依赖外网, 可在 CI/离线环境稳定复跑:
  - 端口级: 未监听端口 → refused(服务未启动); 监听端口 → open;
  - 网络层: 不可达地址 → timeout(不能据此判断服务状态);
  - 页面级: 首页 200 → "网站正常"; 不可达 → reachable=False + failure_layer;
  - 接口级: 业务接口 500 → 识别为服务端异常("页面好、服务坏"的核心用例);
  - 深度检查: 首页引用的丢失资源(404) → 计入 issues。
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mcp_servers.site_probe import (
    classify_network_error,
    deep_check,
    probe_http_api,
    probe_website,
    summarize_probe,
    tcp_connect,
)

# 不可达地址(RFC 5737 TEST-NET-1, 保证不会被路由到真实主机)
UNREACHABLE_HOST = "192.0.2.1"

_HOME_HTML = """<html><head><title>探测靶场</title></head>
<body><img src="/missing.png"><a href="/about">about</a></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静音
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, _HOME_HTML.encode("utf-8"))
        if p == "/about":
            return self._send(200, b"<html><body>about</body></html>")
        if p == "/api/ok":
            return self._send(200, b'{"status":"ok"}', "application/json")
        if p == "/api/boom":
            return self._send(500, b"<html><body>Internal Server Error</body></html>")
        return self._send(404, b"<html><body>404</body></html>")


@pytest.fixture()
def live_server():
    """起一个本地 HTTP 服务(随机端口), 测试结束后关闭。"""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def closed_port():
    """拿到一个当前无进程监听的端口(绑定后立即关闭)。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestTcpConnect:
    def test_closed_port_is_refused(self, closed_port):
        """未监听端口 → refused, 提示"服务未启动"。

        超时给到 5s: 部分 Windows 环境对本地关闭端口的拒绝回包延迟约 2s
        (安全软件/防火墙拦截所致), 超时太紧会被误判成 timeout。
        """
        r = tcp_connect("127.0.0.1", closed_port, timeout_s=5.0)
        assert r["open"] is False
        assert r["status"] == "refused"
        assert "未启动" in r["hint"]

    def test_listening_port_is_open(self, live_server):
        """监听中的端口 → open。"""
        port = int(live_server.rsplit(":", 1)[1])
        r = tcp_connect("127.0.0.1", port, timeout_s=2.0)
        assert r["open"] is True
        assert r["status"] == "open"

    def test_unreachable_host_is_timeout(self):
        """不可达地址 → timeout, 且不得据此判断服务状态。"""
        r = tcp_connect(UNREACHABLE_HOST, 80, timeout_s=1.0)
        assert r["open"] is False
        assert r["status"] == "timeout"
        assert "无法判断服务是否启动" in r["hint"]


class TestClassifyNetworkError:
    def test_refused_is_tcp_layer(self):
        reason, hint, layer = classify_network_error(ConnectionRefusedError("refused"))
        assert layer == "tcp"
        assert "未启动" in hint

    def test_timeout_is_tcp_layer_but_not_conclusive(self):
        reason, hint, layer = classify_network_error(socket.timeout("timed out"))
        assert layer == "tcp"
        assert "不能据此判断服务是否启动" in hint

    def test_dns_failure(self):
        reason, hint, layer = classify_network_error(Exception("Name or service not known"))
        assert layer == "dns"


class TestProbeWebsite:
    def test_homepage_ok(self, live_server):
        r = probe_website(live_server + "/", timeout_s=5.0)
        assert r["reachable"] is True
        assert r["http_status"] == 200
        assert "网站正常" in summarize_probe(live_server, r)

    def test_not_found_is_reachable_but_4xx(self, live_server):
        r = probe_website(live_server + "/nope", timeout_s=5.0)
        assert r["reachable"] is True
        assert r["http_status"] == 404

    def test_unreachable_has_failure_layer(self):
        r = probe_website(f"http://{UNREACHABLE_HOST}:80/", timeout_s=1.0)
        assert r["reachable"] is False
        assert r["failure_layer"] == "tcp"


class TestProbeHttpApi:
    def test_api_ok(self, live_server):
        r = probe_http_api(live_server + "/api/ok", "GET", None, 5.0)
        assert r["reachable"] is True
        assert r["http_status"] == 200

    def test_api_500_detected(self, live_server):
        """核心用例: 页面能打开, 但业务接口 500 —— 页面检查看不见的那种故障。"""
        page = probe_website(live_server + "/", timeout_s=5.0)
        assert page["http_status"] == 200
        api = probe_http_api(live_server + "/api/boom", "GET", None, 5.0)
        assert api["reachable"] is True
        assert api["http_status"] == 500


class TestDeepCheck:
    def test_deep_check_finds_missing_resource(self, live_server):
        home = probe_website(live_server + "/", timeout_s=5.0)
        sub_checks, issues = deep_check(live_server, home, timeout_s=5.0)
        assert sub_checks, "应探测到首页引用的同源资源"
        urls = {i["url"] for i in issues}
        assert any(u.endswith("/missing.png") for u in urls), f"应报告丢失资源: {issues}"