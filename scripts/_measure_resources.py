"""临时资源占用测量: 包装一条子命令, 采样其**进程树**的 CPU / 内存峰值。

用途: 为论文 4.1.2「运行环境 / 运行时长 / CPU 与内存占用」提供一手实测数据。
注意: 本脚本是**测量装置**, 不属于项目交付资产; 仅按需运行, 产物落在 runtime/。

用法:
  python scripts/_measure_resources.py --interval 1.0 -- <cmd> [args...]

环境变量:
  MEASURE_LOG  产物 json 路径(默认 runtime/_resource_measure.json)
"""

import json
import os
import subprocess
import sys
import threading
import time

import psutil


def main() -> None:
    args = sys.argv[1:]
    interval = 1.0
    if "--interval" in args:
        i = args.index("--interval")
        interval = float(args[i + 1])
        del args[i : i + 2]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("usage: _measure_resources.py --interval 1.0 -- <cmd...>", file=sys.stderr)
        sys.exit(2)

    log_path = os.environ.get("MEASURE_LOG", "runtime/_resource_measure.json")

    t0 = time.time()
    proc = psutil.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=os.getcwd(),
    )

    # 预热 cpu_percent(首次调用恒为 0.0)
    psutil.cpu_percent(interval=None)
    try:
        proc.cpu_percent(interval=None)
    except Exception:
        pass

    out_lines: list[str] = []

    def _drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            out_lines.append(line.rstrip())

    th = threading.Thread(target=_drain, daemon=True)
    th.start()

    peak_rss = 0
    peak_cpu = 0.0
    cpu_sum = 0.0
    n = 0

    while proc.poll() is None:
        rss = 0
        cpu = 0.0
        try:
            tree = [proc] + proc.children(recursive=True)
        except Exception:
            tree = [proc]
        for p in tree:
            try:
                with p.oneshot():
                    rss += p.memory_info().rss
                    cpu += p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        peak_rss = max(peak_rss, rss)
        peak_cpu = max(peak_cpu, cpu)
        cpu_sum += cpu
        n += 1
        time.sleep(interval)

    th.join(timeout=5)
    elapsed = time.time() - t0
    vm = psutil.virtual_memory()

    report = {
        "cmd": args,
        "elapsed_s": round(elapsed, 2),
        "peak_rss_mb": round(peak_rss / 1024 / 1024, 1),
        "peak_cpu_percent_sum_of_cores": round(peak_cpu, 1),
        "avg_cpu_percent_sum_of_cores": round(cpu_sum / n, 1) if n else None,
        "samples": n,
        "interval_s": interval,
        "exit_code": proc.returncode,
        "host_logical_cpus": psutil.cpu_count(),
        "host_physical_cpus": psutil.cpu_count(logical=False),
        "host_total_mem_mb": round(vm.total / 1024 / 1024, 1),
    }

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(log_path.replace(".json", ".log"), "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("--- tail output (last 30 lines) ---")
    print("\n".join(out_lines[-30:]))


if __name__ == "__main__":
    main()
