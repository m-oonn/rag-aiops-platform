"""网站/服务真实探测命令行工具(页面级 + 端口级 + 服务级 + 接口级)。

解决的核心盲区: **页面能打开,不代表背后的服务正常**。
用户/运维常遇到"网页 200,但点某个功能报错、任务提交后一直不返回"——
只看页面完全发现不了,本工具会实际去打端口、打健康端点、打业务接口。

用法示例:
  # 1) 页面可达性(默认)
  python scripts/probes/probe_site.py https://deeppub.keyanjia.com/document

  # 2) 页面 + 深度检查(逐个探测首页里的同源链接/图片)
  python scripts/probes/probe_site.py https://example.com --deep

  # 3) "页面好、服务坏"排查: 页面 + 健康端点 + 业务接口
  python scripts/probes/probe_site.py https://api.example.com \
      --health --api https://api.example.com/v1/tasks

  # 4) 端口监听探测(判断服务到底起没起)
  python scripts/probes/probe_site.py 127.0.0.1 --ports 8080,8000,8103

  # 5) 只探业务接口(POST + 请求体)
  python scripts/probes/probe_site.py --api https://api.example.com/v1/review \
      --method POST --payload '{"docId": 123}'

  # 6) 机器可读输出
  python scripts/probes/probe_site.py https://example.com --json

退出码: 0=未发现问题; 1=发现问题; 2=用法错误。

实现复用 mcp_servers/site_probe.py,与 MCP 工具同一套判定口径,保证结论一致。
"""

import argparse
import json
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp_servers.site_probe import (  # noqa: E402
    DEFAULT_HEALTH_PATHS,
    deep_check,
    probe_http_api,
    probe_website,
    summarize_probe,
    tcp_connect,
)


def _print_header(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def _probe_page(url: str, timeout: float, deep: bool, as_json: bool) -> tuple[dict, bool]:
    """页面级探测。返回 (结果, 是否有问题)。"""
    result = probe_website(url, timeout)
    summary = summarize_probe(url, result)
    problems = bool(result.get("reachable") is False
                    or (isinstance(result.get("http_status"), int)
                        and result["http_status"] >= 400))

    if not as_json:
        _print_header(f"[页面级] {url}")
        print(f"  结论  : {summary}")
        print(f"  可达  : {'是' if result.get('reachable') else '否'}")
        if result.get("http_status") is not None:
            print(f"  状态码: HTTP {result['http_status']} {result.get('http_reason', '')}")
        print(f"  耗时  : {result.get('response_ms')} ms")
        if result.get("title"):
            print(f"  标题  : {result['title']}")
        if result.get("server"):
            print(f"  服务器: {result['server']}")
        if result.get("final_url") and result["final_url"] != url:
            print(f"  最终址: {result['final_url']}")
        if result.get("failure_layer"):
            print(f"  失败层: {result['failure_layer']}")
        if result.get("error_hint"):
            print(f"  提示  : {result['error_hint']}")

    if deep and result.get("reachable") and result.get("http_status") == 200:
        sub_checks, issues = deep_check(url, result, timeout)
        result["sub_checks"] = sub_checks
        result["issues"] = issues
        if issues:
            problems = True
        if not as_json:
            print(f"\n  [深度检查] 首页同源资源 {len(sub_checks)} 个, 问题 {len(issues)} 个")
            for i in issues[:10]:
                print(f"    - [{i['severity']}] {i['url']}  {i['kind']}: {i['detail']}")
    return result, problems


def _probe_ports(host: str, ports: str, timeout: float, as_json: bool) -> tuple[dict, bool]:
    """端口级探测。返回 (结果, 是否有问题)。"""
    port_list = [int(p.strip()) for p in str(ports).split(",") if p.strip().isdigit()]
    results = [tcp_connect(host, p, timeout) for p in port_list]
    open_ports = [r["port"] for r in results if r["open"]]
    refused = [r["port"] for r in results if r["status"] == "refused"]
    timeouts = [r["port"] for r in results if r["status"] == "timeout"]
    payload = {"host": host, "results": results, "open_ports": open_ports}

    if open_ports:
        summary = f"{host} 上 {open_ports} 端口有服务在监听。"
    elif refused and not timeouts:
        summary = f"{host} 上被探测的端口均无监听(连接被拒绝), 对应服务很可能未启动。"
    elif timeouts and not refused:
        summary = f"{host} 不可达(连接超时), 无法判断服务是否启动——请先确认网络与防火墙。"
    else:
        summary = f"{host} 端口探测: 拒绝 {refused}, 超时 {timeouts}。"
    payload["summary"] = summary

    # 有端口没监听 = 服务未启动,视为问题;纯超时 = 网络不可达,也算问题(需人工确认)
    problems = bool(refused or timeouts)

    if not as_json:
        _print_header(f"[端口级] {host}")
        print(f"  结论  : {summary}")
        for r in results:
            mark = "开放" if r["open"] else r["status"]
            print(f"    - 端口 {r['port']:<6} {mark:<8} {r.get('latency_ms')} ms  {r.get('hint', '')}")
    return payload, problems


def _probe_health(base_url: str, timeout: float, as_json: bool) -> tuple[dict, bool]:
    """服务级健康端点探测。返回 (结果, 是否有问题)。"""
    base = base_url.rstrip("/")
    checked = []
    for p in DEFAULT_HEALTH_PATHS:
        r = probe_http_api(base + p, "GET", None, timeout)
        checked.append({"endpoint": base + p, **r})
    healthy = [c for c in checked
               if isinstance(c.get("http_status"), int) and 200 <= c["http_status"] < 300]
    payload = {"base_url": base_url, "checked": checked, "healthy": bool(healthy)}

    if healthy:
        summary = f"服务健康检查通过: {healthy[0]['endpoint']} 返回 HTTP {healthy[0]['http_status']}。"
    else:
        detail = "; ".join(
            f"{c['endpoint']} -> "
            + (f"HTTP {c['http_status']}" if c.get("http_status") else str(c.get("error_type")))
            for c in checked)
        summary = f"未找到可用健康端点({detail})。没有健康端点不等于服务异常,需结合业务接口判断。"
    payload["summary"] = summary

    # 健康端点缺失不直接判死(很多服务不暴露 /health),只作提示,不计入问题
    if not as_json:
        _print_header(f"[服务级] {base_url}")
        print(f"  结论  : {summary}")
        for c in checked:
            code = c.get("http_status")
            state = f"HTTP {code}" if code is not None else str(c.get("error_type"))
            print(f"    - {c['endpoint']:<40} {state:<16} {c.get('response_ms')} ms")
    return payload, False


def _probe_api(url: str, method: str, payload: str, headers: str,
               timeout: float, as_json: bool) -> tuple[dict, bool]:
    """接口级业务探测。返回 (结果, 是否有问题)。"""
    extra = None
    if headers:
        try:
            extra = json.loads(headers)
        except Exception:
            print(f"  ⚠️ --header 不是合法 JSON,已忽略: {headers}", file=sys.stderr)
    r = probe_http_api(url, method, payload, timeout, extra)
    code = r.get("http_status")
    if not r.get("reachable"):
        summary = f"业务接口不可达: {r.get('error_type')}({r.get('error_hint') or '无'})。"
    elif isinstance(code, int) and 200 <= code < 300:
        summary = f"业务接口正常: HTTP {code}, 耗时 {r.get('response_ms')} ms。"
    elif isinstance(code, int) and code >= 500:
        summary = f"业务接口服务端异常: HTTP {code}, 后台服务在运行但处理失败(需查后台日志)。"
    elif isinstance(code, int) and code >= 400:
        summary = f"业务接口客户端错误: HTTP {code}(请求/权限问题)。"
    else:
        summary = f"业务接口返回 HTTP {code}。"
    out = {"url": url, "method": method.upper(), "summary": summary, **r}

    problems = bool(r.get("reachable") is False
                    or (isinstance(code, int) and code >= 500))

    if not as_json:
        _print_header(f"[接口级] {method.upper()} {url}")
        print(f"  结论  : {summary}")
        print(f"  耗时  : {r.get('response_ms')} ms")
        if r.get("body_snippet"):
            print(f"  响应体: {r['body_snippet'][:200]}")
    return out, problems


def _looks_like_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://")) or "." in s


def main() -> int:
    parser = argparse.ArgumentParser(
        description="网站/服务真实探测(页面级+端口级+服务级+接口级)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("target", nargs="?", default=None,
                        help="目标 URL(https://… 或 example.com)或主机名/IP(配 --ports 用)")
    parser.add_argument("--deep", action="store_true", help="深度检查: 逐个探测首页同源资源")
    parser.add_argument("--health", action="store_true", help="额外探测服务的健康检查端点")
    parser.add_argument("--ports", default=None, help="逗号分隔端口列表,如 8080,8000(对 target 主机探测)")
    parser.add_argument("--api", default=None, help="额外探测一个业务接口 URL")
    parser.add_argument("--method", default="GET", help="业务接口的 HTTP 方法(默认 GET)")
    parser.add_argument("--payload", default=None, help="业务接口请求体(JSON 字符串)")
    parser.add_argument("--header", default=None, help="业务接口额外请求头(JSON 字符串)")
    parser.add_argument("--timeout", type=float, default=10.0, help="超时秒数(默认 10)")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出(机器可读)")

    args = parser.parse_args()

    if not args.target and not args.api:
        parser.error("请给出目标: 位置参数 target(URL 或主机) 或 --api <接口URL>")

    report: dict = {}
    any_problem = False

    if args.target:
        if args.ports:
            # 端口探测超时夹到 [4s, 6s]: 至少 4s 兼容本地"拒绝回包延迟约 2s"的环境
            port_timeout = min(max(args.timeout, 4.0), 6.0)
            data, prob = _probe_ports(args.target, args.ports, port_timeout, args.json)
            report["ports"] = data
            any_problem = any_problem or prob
        elif _looks_like_url(args.target):
            data, prob = _probe_page(args.target, args.timeout, args.deep, args.json)
            report["page"] = data
            any_problem = any_problem or prob
            if args.health:
                hdata, hprob = _probe_health(args.target, args.timeout, args.json)
                report["health"] = hdata
                any_problem = any_problem or hprob
        else:
            # 纯主机名/IP 但没给端口: 默认探常见 Web 端口(超时 4s, 兼容本地拒绝回包延迟)
            data, prob = _probe_ports(args.target, "80,443,8000,8080,3000,5000", 4.0, args.json)
            report["ports"] = data
            any_problem = any_problem or prob

    if args.api:
        adata, aprob = _probe_api(args.api, args.method, args.payload, args.header,
                                  args.timeout, args.json)
        report["api"] = adata
        any_problem = any_problem or aprob

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 64)
        print("  总判定: " + ("⚠️ 发现异常,请见上方各项" if any_problem else "✅ 未发现问题"))
        print("=" * 64)

    return 1 if any_problem else 0


if __name__ == "__main__":
    sys.exit(main())