"""临时诊断脚本: 只读采样一个正在运行的实验进程树的 CPU / 内存占用。

不向目标进程发送任何信号, 不做任何写操作 —— 仅读取 /proc 等价的进程指标。
用途: 为论文 4.1.2 的「CPU / 内存占用」提供一手实测数据。

用法:
  python scripts/_watch_proc.py <pid_or_keyword> [--interval 2.0] [--out runtime/_proc_watch.json]
"""

import json
import os
import sys
import time

import psutil


def find_targets(keyword: str) -> list:
    """按命令行关键字匹配进程; 若 keyword 是纯数字则按 pid 匹配。"""
    out = []
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if keyword.isdigit():
                if p.info["pid"] == int(keyword):
                    out.append(p)
            elif keyword in cl:
                out.append(p)
        except Exception:
            pass
    return out


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: _watch_proc.py <pid_or_keyword> [--interval S] [--out PATH]", file=sys.stderr)
        sys.exit(2)
    keyword = sys.argv[1]
    interval = 2.0
    out_path = "runtime/_proc_watch.json"
    if "--interval" in sys.argv:
        interval = float(sys.argv[sys.argv.index("--interval") + 1])
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    targets = find_targets(keyword)
    if not targets:
        print(f"[watch] 未找到匹配 '{keyword}' 的进程")
        sys.exit(1)

    # 选择内存占用最大者作为主进程
    main_proc = max(targets, key=lambda p: p.memory_info().rss)
    started = main_proc.create_time()
    print(f"[watch] 监控主进程 pid={main_proc.pid} started={time.strftime('%H:%M:%S', time.localtime(started))}")
    print(f"[watch] 采样间隔 {interval}s，按 Ctrl-C 结束")

    # 预热
    psutil.cpu_percent(interval=None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(interval=None)
        except Exception:
            pass

    peak_rss = 0
    peak_cpu = 0.0
    samples = []
    t0 = time.time()

    while True:
        try:
            tree = [main_proc] + main_proc.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            break
        rss = 0
        cpu = 0.0
        for p in tree:
            try:
                with p.oneshot():
                    rss += p.memory_info().rss
                    cpu += p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        peak_rss = max(peak_rss, rss)
        peak_cpu = max(peak_cpu, cpu)
        samples.append(
            {
                "t_s": round(time.time() - t0, 1),
                "rss_mb": round(rss / 1048576, 1),
                "cpu": round(cpu, 1),
                "n_proc": len(tree),
            }
        )
        try:
            if not main_proc.is_running():
                break
        except Exception:
            break
        time.sleep(interval)

    elapsed = time.time() - t0
    report = {
        "target_keyword": keyword,
        "main_pid": main_proc.pid,
        "proc_uptime_s_at_watch_start": round(t0 - started, 1),
        "watched_s": round(elapsed, 1),
        "peak_rss_mb": round(peak_rss / 1048576, 1),
        "peak_cpu_percent_sum_of_cores": round(peak_cpu, 1),
        "samples": len(samples),
        "interval_s": interval,
        "host_logical_cpus": psutil.cpu_count(),
        "host_total_mem_mb": round(psutil.virtual_memory().total / 1048576, 1),
        "series": samples[-240:],
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "series"}, ensure_ascii=False, indent=2))
    print(f"[watch] 明细已写入 {out_path}")


if __name__ == "__main__":
    main()
