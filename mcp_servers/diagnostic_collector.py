"""Fixed read queries on ONE target, suitable for an SSH forced command.

Run as the diagnostic account, never root. Configuration is operator-owned.
No shell commands, paths, addresses or process identifiers come from the agent.
"""

import json
import os
import socket
import subprocess
import sys
import http.client
from datetime import datetime, timezone
from pathlib import Path


def collect(request, config):
    operation = request.get("operation")
    service = request.get("service", "")
    services = config.get("services", {})
    entry = services.get(service) if service else None
    if service and not isinstance(entry, dict):
        raise ValueError("service not configured")
    result = {"data_source": "diagnostic_target", "target_id": config["target_id"],
              "collected_at": datetime.now(timezone.utc).isoformat(),
              "operation": operation, "service": service,
              "hostname": socket.gethostname()}
    if operation == "catalog":
        result["services"] = {name: {k: v for k, v in item.items()
                                     if k in {"entrypoint", "unit", "process_name", "dependencies"}}
                              for name, item in services.items()}
    elif operation == "resources":
        result["loadavg"] = Path("/proc/loadavg").read_text()
        result["meminfo"] = Path("/proc/meminfo").read_text()
        usage = os.statvfs("/")
        result["disk"] = {"total_bytes": usage.f_blocks * usage.f_frsize,
                          "available_bytes": usage.f_bavail * usage.f_frsize}
    elif operation == "processes":
        processes = []
        # comm omits command-line secrets. Container/user visibility is explicit.
        for path in Path("/proc").iterdir():
            if path.name.isdecimal():
                try:
                    name = (path / "comm").read_text().strip()
                    if not entry or name == entry.get("process_name"):
                        processes.append({"pid": int(path.name), "name": name})
                except OSError:
                    continue
                if len(processes) >= 256:
                    result["truncated"] = True
                    break
        result["processes"] = processes
    elif operation == "ports":
        # Kernel socket tables are read directly; no Docker/systemd management API.
        result["tcp"] = Path("/proc/net/tcp").read_text()[:16384]
        result["tcp6"] = Path("/proc/net/tcp6").read_text()[:16384]
    elif operation == "logs" and entry:
        # Only operator-configured files. No model-provided path is accepted.
        lines = min(200, max(1, int(request.get("lines", 100))))
        result["logs"] = []
        for name in entry.get("logs", [])[:8]:
            path = Path(name)
            with path.open("rb") as handle:
                handle.seek(max(0, os.fstat(handle.fileno()).st_size - 16384))
                content = handle.read(16384).decode("utf-8", errors="replace")
            result["logs"].append({"path": str(path), "content": "\n".join(content.splitlines()[-lines:])})
    elif operation == "service" and entry and entry.get("unit"):
        response = subprocess.run(["systemctl", "show", "--no-pager",
            "--property=Id,LoadState,ActiveState,SubState,MainPID,ExecMainStatus", "--", entry["unit"]],
            capture_output=True, text=True, timeout=5)
        result["status"] = response.stdout[:16384]
        result["exit_code"] = response.returncode
        if response.returncode:
            raise ValueError("service query unavailable to diagnostic account")
    elif operation == "dependency":
        dependency = config.get("dependencies", {}).get(request.get("dependency"))
        if not isinstance(dependency, dict):
            raise ValueError("dependency not configured")
        host, port = dependency["host"], int(dependency["port"])
        # DNS/TCP only, from the target's network. Outer caller limits full query time.
        result.update({"dependency": request["dependency"], "host": host, "port": port})
        result["probe"] = request.get("probe", "tcp")
        try:
            if result["probe"] == "dns":
                result["addresses"] = sorted({item[4][0] for item in socket.getaddrinfo(host, port)})
                return result
            if result["probe"] == "health":
                health = dependency.get("health")
                if not isinstance(health, dict) or health.get("scheme") not in {"http", "https"}:
                    raise ValueError("health endpoint not configured")
                connection_class = http.client.HTTPSConnection if health["scheme"] == "https" else http.client.HTTPConnection
                connection = connection_class(host, port, timeout=3)
                try:
                    connection.request("GET", health["path"])
                    response = connection.getresponse()
                    # No redirect following, model-provided URL, headers or request body.
                    body = response.read(8193)
                    result.update({"status_code": response.status,
                                   "body": body[:8192].decode("utf-8", errors="replace"),
                                   "truncated": len(body) > 8192})
                finally:
                    connection.close()
                return result
            if result["probe"] != "tcp":
                raise ValueError("probe not allowed")
            with socket.create_connection((host, port), timeout=3):
                result["reachable"] = True
        except OSError as error:
            result.update({"reachable": False, "error_type": type(error).__name__})
    else:
        raise ValueError("operation unavailable; request approval for additional access")
    return result


if __name__ == "__main__":
    try:
        # SSH forced-command deployment uses this operator-owned path. Agent cannot
        # choose an executable/config, or change this through SSH_ORIGINAL_COMMAND.
        config = json.loads(Path(os.environ.get("DIAGNOSTIC_COLLECTOR_CONFIG",
                              "/etc/aiops-diagnostic.json")).read_text())
        request = json.loads(sys.stdin.buffer.read(4097))
        print(json.dumps(collect(request, config), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"data_source": "unavailable", "error_type": type(error).__name__}))
        sys.exit(1)
