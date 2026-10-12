"""临时诊断脚本: 列出监听 8103/8104/8105 的进程与实验主进程。只读, 不做任何终止操作。"""

import datetime

import psutil

PORTS = (8103, 8104, 8105)

print("=== 监听 8103/8104/8105 的进程 ===")
found = False
for c in psutil.net_connections(kind="inet"):
    if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in PORTS:
        found = True
        try:
            p = psutil.Process(c.pid)
            cmd = " ".join(p.cmdline())[:110]
            print(f"port={c.laddr.port} pid={c.pid} mem={p.memory_info().rss // 1048576}MB")
            print(f"    cmd={cmd}")
        except Exception as e:
            print(f"port={c.laddr.port} pid={c.pid} (读取失败: {e})")
if not found:
    print("无进程监听这些端口")

print()
print("=== 实验主进程 ===")
KEYWORDS = ("run_explainability", "run_blind_eval", "_measure_resources", "cls_server", "monitor_server", "rag_server")
rows = []
for p in psutil.process_iter(["pid", "name", "memory_info", "cmdline", "create_time"]):
    try:
        name = (p.info["name"] or "").lower()
        if "python" not in name:
            continue
        cl = " ".join(p.info["cmdline"] or [])
        if any(k in cl for k in KEYWORDS):
            rows.append((p.info["pid"], p.info["memory_info"].rss // 1048576, p.info["create_time"], cl[:140]))
    except Exception:
        pass
for pid, mb, ct, cl in sorted(rows, key=lambda x: -x[1]):
    ts = datetime.datetime.fromtimestamp(ct).strftime("%H:%M:%S")
    print(f"pid={pid} {mb}MB started={ts}")
    print(f"    {cl}")
if not rows:
    print("无相关主进程")
