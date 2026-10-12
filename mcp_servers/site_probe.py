"""网站/服务真实探测引擎(纯标准库,无 MCP / 框架依赖)。

把"页面级 / 端口级 / 服务级 / 接口级"四层**真实**探测收敛到一个可复用模块:
  - probe_website(url, timeout_s)        页面可达性(真实 HTTP GET,含状态码/耗时/标题)
  - summarize_probe(url, result)         把探测结果转成一句人话结论
  - deep_check(base_url, home, timeout)  首页同源子资源逐个真实探测,汇总问题清单
  - tcp_connect(host, port, timeout_s)   端口监听探测(真实 TCP 连接)
  - probe_http_api(url, ...)             通用业务接口探测(方法/请求体/自定义头)
  - classify_network_error(e)            网络错误分层(dns / tcp / tls / unknown)

两个消费方共用同一套判定口径,避免"Agent 看到的"和"命令行看到的"不一致:
  - mcp_servers/monitor_server.py: 包成 MCP 工具暴露给运维 Agent;
  - scripts/probe_site.py:         命令行直接探测,给人和脚本用。

关键纪律(实测踩坑沉淀):
  - 默认**绕过系统代理直连**:诊断工具必须反映"网站本身是否可达",走代理时代理的
    502/超时会被误判成网站故障(本机曾踩坑:example.com 经代理返回 502 误报)。
    需要经代理时设环境变量 WEBSITE_CHECK_USE_PROXY=1。
  - 把"连接被拒绝(端口无监听→服务没起)"与"连接超时(网络层不可达)"严格分开,
    超时**不能**据此判断服务是否启动。
"""

import os
import re
import socket
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

HTTP_STATUS_TEXT: Dict[int, str] = {
    200: "正常", 204: "正常(无内容)", 301: "永久重定向", 302: "临时重定向",
    307: "临时重定向", 308: "永久重定向", 400: "错误请求", 401: "未授权",
    403: "禁止访问", 404: "页面不存在", 405: "方法不允许", 408: "请求超时",
    410: "已删除", 429: "请求过于频繁", 500: "服务器内部错误",
    502: "网关错误", 503: "服务不可用", 504: "网关超时",
}

DEFAULT_HEALTH_PATHS: Tuple[str, ...] = ("/health", "/healthz", "/ready", "/api/health", "/status")

PORT_HINTS: Dict[str, str] = {
    "open": "端口有进程监听(服务在运行)",
    "refused": "端口无监听: 该端口上的服务未启动或已退出",
    "timeout": "连接超时: 主机不可达或被防火墙丢弃, 无法判断服务是否启动",
}

_USER_AGENT = "AIOps-Agent/1.0 (+health check)"


def _build_opener() -> Any:
    """默认绕过系统代理直连;WEBSITE_CHECK_USE_PROXY=1 时走系统代理。"""
    if os.environ.get("WEBSITE_CHECK_USE_PROXY") == "1":
        return urlrequest.build_opener()
    return urlrequest.build_opener(urlrequest.ProxyHandler({}))


def classify_network_error(e: Exception) -> Tuple[str, str, str]:
    """把网络异常分类成 (错误类型, 人话提示, 失败层)。

    失败层(failure_layer): dns / tcp / tls / unknown。
    关键: 把"连接被拒绝"(端口无监听→服务没起)与"连接超时"(网络层不可达)分开,
    避免把"网络不通"误判成"服务未启动", 也避免反过来。
    """
    if isinstance(e, urlerror.URLError):
        inner = getattr(e, "reason", None)
        detail = str(inner) if inner else str(e)
    else:
        detail = str(e)
    dl = detail.lower()
    if "certificate" in dl or "ssl" in dl:
        return "TLS 证书校验失败", "HTTPS 证书无效或过期", "tls"
    if "name or service not known" in dl or "getaddrinfo" in dl or "解析" in detail:
        return "DNS 解析失败", "域名不存在或解析服务不可达", "dns"
    if "refused" in dl or "拒绝" in detail or "10061" in dl:
        return "连接被拒绝", "端口无监听: 该端口上的服务未启动或已退出", "tcp"
    if "timed out" in dl or "timeout" in dl or "超时" in detail:
        return "连接超时", "网络层不可达: 主机不可达或被防火墙丢弃, 或服务无响应——不能据此判断服务是否启动", "tcp"
    return f"网络错误({detail})", "", "unknown"


def _normalize_url(url: str) -> str:
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return "https://" + url
    return url


def probe_website(url: str, timeout_s: float = 10.0) -> Dict[str, Any]:
    """真实发起一次 HTTP GET 探测,返回结构化的探测结果(不含判断,只给事实)。"""
    url = _normalize_url(url)
    req = urlrequest.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    opener = _build_opener()
    started = time.time()
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            elapsed_ms = int((time.time() - started) * 1000)
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read(65536)
            charset = resp.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
            m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            return {
                "reachable": True,
                "final_url": resp.geturl(),
                "http_status": int(status),
                "http_reason": HTTP_STATUS_TEXT.get(int(status), ""),
                "response_ms": elapsed_ms,
                "server": resp.headers.get("Server", ""),
                "title": title[:80],
                "failure_layer": None,
            }
    except urlerror.HTTPError as e:
        elapsed_ms = int((time.time() - started) * 1000)
        return {
            "reachable": True,
            "final_url": e.url,
            "http_status": e.code,
            "http_reason": HTTP_STATUS_TEXT.get(e.code, ""),
            "response_ms": elapsed_ms,
            "server": (e.headers.get("Server", "") if e.headers else ""),
            "title": "",
            "failure_layer": "http",
        }
    except Exception as e:
        elapsed_ms = int((time.time() - started) * 1000)
        reason, hint, layer = classify_network_error(e)
        return {
            "reachable": False,
            "final_url": url,
            "http_status": None,
            "response_ms": elapsed_ms,
            "error_type": reason,
            "error_hint": hint,
            "failure_layer": layer,
            "error": str(e)[:200],
        }


def summarize_probe(url: str, r: Dict[str, Any]) -> str:
    """把探测结果转成一句人话结论,供报告/CLI 引用。"""
    if not r.get("reachable"):
        hint = f"（{r['error_hint']}）" if r.get("error_hint") else ""
        return f"网站不可访问:{r.get('error_type', '未知错误')}{hint},耗时 {r['response_ms']} ms。"
    code = r.get("http_status")
    ms = r.get("response_ms")
    if code and 200 <= int(code) < 300:
        slow = ",响应偏慢,建议关注" if ms and ms > 3000 else ""
        return f"网站正常:HTTP {code},响应 {ms} ms{slow}。"
    if code and 300 <= int(code) < 400:
        return f"页面重定向:HTTP {code},最终地址 {r.get('final_url')}。"
    reason = r.get("http_reason") or ""
    return f"网站可访问但返回异常状态:HTTP {code} {reason},耗时 {ms} ms。"


def deep_check(base_url: str, home: Dict[str, Any], timeout_s: float = 10.0) -> Tuple[List[dict], List[dict]]:
    """深度检查:取首页 HTML → 抽取同源资源 → 逐个真实探测 → 汇总问题清单。

    只探测**同源**资源(图片/链接/脚本),避免把外部站点(如 CDN)的问题误报成本站问题。
    """
    from urllib.parse import urljoin, urlparse

    issues: List[dict] = []
    sub_checks: List[dict] = []
    origin = "{u.scheme}://{u.netloc}".format(u=urlparse(home.get("final_url") or base_url))

    try:
        req = urlrequest.Request(home.get("final_url") or base_url,
                                 headers={"User-Agent": _USER_AGENT})
        with _build_opener().open(req, timeout=timeout_s) as resp:
            html = resp.read(262144).decode(resp.headers.get_content_charset() or "utf-8",
                                            errors="replace")
    except Exception as e:
        issues.append({"url": base_url, "kind": "页面读取失败", "severity": "严重",
                       "detail": f"{type(e).__name__}: {str(e)[:80]}",
                       "suggestion": "确认首页可访问后再做深度检查"})
        return sub_checks, issues

    resources: List[str] = []
    seen = set()
    patterns = (
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\']',
        r'<script[^>]+src=["\']([^"\']+)["\']',
        r'<a[^>]+href=["\']([^"\']+)["\']',
    )
    for pat in patterns:
        for m in re.findall(pat, html, re.IGNORECASE):
            u = urljoin(home.get("final_url") or base_url, m)
            if urlparse(u).netloc != urlparse(origin).netloc:
                continue
            if u in seen or u.rstrip("/") in (base_url.rstrip("/"),
                                              (home.get("final_url") or "").rstrip("/")):
                continue
            seen.add(u)
            resources.append(u)
            if len(resources) >= 12:
                break
        if len(resources) >= 12:
            break

    for u in resources:
        r = probe_website(u, timeout_s)
        code = r.get("http_status")
        sub_checks.append({"url": u, "http_status": code,
                           "response_ms": r.get("response_ms"), "reachable": r.get("reachable")})
        if not r.get("reachable"):
            issues.append({"url": u, "kind": "资源不可访问", "severity": "严重",
                           "detail": f"{r.get('error_type')}",
                           "suggestion": "确认该资源是否已部署 / 链接是否正确"})
        elif isinstance(code, int) and code >= 500:
            issues.append({"url": u, "kind": "服务端错误", "severity": "严重",
                           "detail": f"HTTP {code} {r.get('http_reason', '')}",
                           "suggestion": "查服务端日志定位该接口异常原因"})
        elif isinstance(code, int) and code >= 400:
            issues.append({"url": u, "kind": "资源错误", "severity": "中等",
                           "detail": f"HTTP {code} {r.get('http_reason', '')}",
                           "suggestion": "静态资源确认是否缺失;接口确认权限/参数"})
        elif r.get("response_ms") and r["response_ms"] > 3000:
            issues.append({"url": u, "kind": "响应过慢", "severity": "中等",
                           "detail": f"{r['response_ms']} ms（>3s）",
                           "suggestion": "排查该接口/资源的性能瓶颈"})
    return sub_checks, issues


def tcp_connect(host: str, port: int, timeout_s: float = 3.0) -> Dict[str, Any]:
    """对 host:port 做一次 TCP 连接探测,区分 开放 / 拒绝 / 超时。"""
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, int(port)))
        return {"port": int(port), "open": True, "status": "open",
                "latency_ms": int((time.time() - started) * 1000), "hint": PORT_HINTS["open"]}
    except socket.timeout:
        return {"port": int(port), "open": False, "status": "timeout",
                "latency_ms": int((time.time() - started) * 1000), "hint": PORT_HINTS["timeout"]}
    except ConnectionRefusedError:
        return {"port": int(port), "open": False, "status": "refused",
                "latency_ms": int((time.time() - started) * 1000), "hint": PORT_HINTS["refused"]}
    except OSError as e:
        dl = str(e).lower()
        if "refused" in dl or "10061" in dl:
            status = "refused"
        elif "timed out" in dl or "timeout" in dl:
            status = "timeout"
        else:
            status = "error"
        return {"port": int(port), "open": False, "status": status,
                "latency_ms": int((time.time() - started) * 1000),
                "hint": PORT_HINTS.get(status, f"连接失败: {str(e)[:80]}")}
    finally:
        sock.close()


def probe_http_api(url: str, method: str = "GET", payload: Optional[str] = None,
                   timeout_s: float = 10.0,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """通用 HTTP 探测(支持方法/请求体/自定义头),返回状态码/耗时/响应体摘要。"""
    url = _normalize_url(url)
    hdrs = {"User-Agent": _USER_AGENT, "Accept": "application/json, text/plain, */*"}
    if headers:
        hdrs.update({str(k): str(v) for k, v in headers.items()})
    data = payload.encode("utf-8") if payload else None
    if data and not any(k.lower() == "content-type" for k in hdrs):
        hdrs["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=hdrs, method=str(method).upper())
    opener = _build_opener()
    started = time.time()

    def _snippet(raw: bytes, charset: Optional[str]) -> str:
        return re.sub(r"\s+", " ", raw.decode(charset or "utf-8", errors="replace"))[:300]

    try:
        with opener.open(req, timeout=timeout_s) as resp:
            return {"reachable": True, "http_status": int(resp.getcode()),
                    "response_ms": int((time.time() - started) * 1000),
                    "body_snippet": _snippet(resp.read(8192), resp.headers.get_content_charset()),
                    "failure_layer": None}
    except urlerror.HTTPError as e:
        charset = e.headers.get_content_charset() if e.headers else None
        try:
            body = e.read(8192)
        except Exception:
            body = b""
        return {"reachable": True, "http_status": int(e.code),
                "response_ms": int((time.time() - started) * 1000),
                "body_snippet": _snippet(body, charset), "failure_layer": "http"}
    except Exception as e:
        reason, hint, layer = classify_network_error(e)
        return {"reachable": False, "http_status": None,
                "response_ms": int((time.time() - started) * 1000),
                "error_type": reason, "error_hint": hint, "failure_layer": layer,
                "error": str(e)[:200]}