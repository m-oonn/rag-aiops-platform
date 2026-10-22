"""受限现场诊断 MCP 服务。

这个服务是 Agent 的自动检查边界：Agent 可以自由组合命令，但命令只能在
部署时指定的诊断容器/账户中运行。需要宿主管理权限的检查不在这里伪装成只读，
由部署方提供现场快照或转 Termcp 审批。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier


_token = os.getenv("DIAGNOSTIC_TOKEN", "")
mcp = FastMCP("Diagnostic", auth=StaticTokenVerifier(tokens={
    _token: {"client_id": "aiops", "scopes": ["diagnostic"]},
}, required_scopes=["diagnostic"]) if _token else None)
_MAX_COMMAND = 4000
_MAX_OUTPUT = 16384
_MAX_TIMEOUT = 15.0
_POLICY_VERSION = "diagnostic-shell.1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "data_source": "unavailable",
        "message": f"未取得现场数据：{reason}",
        "policy_version": _POLICY_VERSION,
    }


def _enabled() -> bool:
    return os.getenv("DIAGNOSTIC_EXEC_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _validate_command(command: str) -> str | None:
    if not isinstance(command, str) or not command.strip():
        return "命令不能为空"
    if len(command) > _MAX_COMMAND:
        return f"命令超过 {_MAX_COMMAND} 字符限制"
    if "\x00" in command or any(ord(ch) < 32 and ch not in "\t" for ch in command):
        return "命令包含被禁止的控制字符"
    return None


def _limit(value: int | float | None, default: int | float, maximum: int | float) -> int | float:
    try:
        parsed = default if value is None else value
        parsed = float(parsed)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(0.1, min(parsed, float(maximum)))


def _sandbox_command(command: str, evidence_dir: str | None = None) -> list[str] | None:
    """Build a read-only, no-network command sandbox; absence is a hard failure."""
    bwrap = shutil.which("bwrap")
    if not bwrap or os.name == "nt" or not evidence_dir:
        return None
    argv = [
        bwrap, "--die-with-parent", "--unshare-all", "--new-session",
        "--cap-drop", "ALL", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--chdir", "/tmp",
    ]
    # Expose executable/runtime files only, never the service root, credentials,
    # management sockets, or host mounts. /proc belongs to the new PID namespace.
    for name in ("usr", "bin", "lib", "lib64", "sbin"):
        if Path(f"/{name}").exists():
            argv.extend(["--ro-bind", f"/{name}", f"/{name}"])
    if evidence_dir:
        source = Path(evidence_dir).resolve()
        if not source.is_dir():
            return None
        # A read-only bind still exposes active UNIX sockets; this directory must
        # contain collector evidence only, never symlinks, sockets or devices.
        import stat
        for path in source.rglob("*"):
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                return None
        argv.extend(["--ro-bind", str(source), "/evidence"])
    argv.extend(["--", "/bin/sh", "-lc", command])
    return argv


def _diagnostic_exec(command: str, timeout: float = 10.0, max_output: int = 8192) -> dict[str, Any]:
    """在受部署策略约束的诊断环境执行一条现场检查命令。

    命令可自由使用 grep/awk/管道分析现场数据。服务本身不判断命令语义是否只读；
    只依赖运行账户、容器文件系统、能力和网络隔离。隔离未启用时返回 unavailable。
    """
    error = _validate_command(command)
    if error:
        return _unavailable(error)
    if not _enabled():
        return _unavailable("自动诊断执行边界未启用")

    evidence_dir = os.getenv("DIAGNOSTIC_EVIDENCE_DIR", "").strip() or None
    argv = _sandbox_command(command, evidence_dir)
    if argv is None:
        return _unavailable("bubblewrap 隔离或只读现场目录未就绪；未执行命令")

    timeout_s = float(_limit(timeout, 10.0, _MAX_TIMEOUT))
    output_limit = int(_limit(max_output, 8192, _MAX_OUTPUT))
    started = _now()
    started_monotonic = time.monotonic()
    shell_mode = os.name == "nt" and isinstance(argv, str)
    env = {
        "PATH": os.getenv("DIAGNOSTIC_PATH", os.environ.get("PATH", "/usr/bin:/bin")),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    if os.name == "nt":
        env.update({key: os.environ[key] for key in ("ComSpec", "SystemRoot") if key in os.environ})
    cwd = os.getenv("DIAGNOSTIC_WORKDIR") or None
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell_mode,
            start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0),
        )
        # Drain both pipes but retain only bounded bytes. communicate() would
        # buffer unlimited output before truncation, letting 'yes' exhaust memory.
        buffers = [bytearray(), bytearray()]
        truncated = [False, False]
        def drain(pipe, index):
            while chunk := pipe.read(4096):
                remaining = output_limit - len(buffers[index])
                buffers[index].extend(chunk[:max(0, remaining)])
                truncated[index] |= len(chunk) > remaining
        readers = [threading.Thread(target=drain, args=(pipe, index), daemon=True)
                   for index, pipe in enumerate((process.stdout, process.stderr))]
        for reader in readers:
            reader.start()
        try:
            process.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=1)
        output, error_output = [bytes(buffer).decode("utf-8", errors="replace") for buffer in buffers]
        if process.returncode != 0 and error_output.startswith("bwrap:"):
            return _unavailable("隔离启动失败；未执行调查命令")
        return {
            "data_source": "diagnostic_analysis",
            "policy_version": _POLICY_VERSION,
            "command": command,
            "evidence_origin": "sandbox analysis; target facts require diagnostic_query provenance",
            "started_at": started,
            "finished_at": _now(),
            "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000),
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "stdout": output,
            "stderr": error_output,
            "output_truncated": any(truncated),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return _unavailable(type(exc).__name__)


def _allowed_dependencies() -> dict[str, dict[str, Any]]:
    raw = os.getenv("DIAGNOSTIC_ALLOWED_DEPENDENCIES", "{}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _evidence_root() -> Path | None:
    raw = os.getenv("DIAGNOSTIC_EVIDENCE_DIR", "").strip()
    if not raw:
        return None
    root = Path(raw).resolve()
    return root if root.is_dir() else None


def _safe_evidence_path(name: str) -> tuple[Path | None, str | None]:
    if not isinstance(name, str) or not name or "\x00" in name:
        return None, "证据名称无效"
    root = _evidence_root()
    if root is None:
        return None, "现场证据目录未就绪"
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None, "证据路径越界"
    if not path.is_file():
        return None, "证据文件不存在"
    return path, None


@mcp.tool()
def diagnostic_list_evidence() -> dict[str, Any]:
    """列出部署方只读挂载的现场证据文件及其时间/大小元数据。"""
    root = _evidence_root()
    if root is None:
        return _unavailable("现场证据目录未就绪")
    files = []
    for path in root.rglob("*"):
        if len(files) >= 256:
            break
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root):
            stat = path.stat()
            files.append({
                "name": path.relative_to(root).as_posix(),
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
    return {"data_source": "diagnostic_analysis", "policy_version": _POLICY_VERSION, "files": files}


@mcp.tool()
def diagnostic_read_evidence(name: str, max_bytes: int = 16384) -> dict[str, Any]:
    """读取一个白名单目录内的现场证据文件，拒绝路径穿越并限制输出。"""
    path, error = _safe_evidence_path(name)
    if error:
        return _unavailable(error)
    limit = int(_limit(max_bytes, 16384, _MAX_OUTPUT))
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
            size = os.fstat(handle.fileno()).st_size
    except OSError as exc:
        return _unavailable(type(exc).__name__)
    # Raw file reads are analysis context. Only collector-authenticated results
    # can serve as target evidence, not an arbitrary manually mounted JSON file.
    return {
        "data_source": "diagnostic_analysis",
        "policy_version": _POLICY_VERSION,
        "name": name,
        "content": data[:limit].decode("utf-8", errors="replace"),
        "output_truncated": len(data) > limit,
        "size": size,
    }


def _diagnostic_probe_dependency(name: str, timeout: float = 3.0, probe: str = "tcp") -> dict[str, Any]:
    """探测配置中允许的依赖地址，只做 DNS/TCP 连通性检查。"""
    if os.getenv("DIAGNOSTIC_SSH_CONFIG"):
        return _diagnostic_query("dependency", dependency=name, probe=probe)
    # A local-network probe must never masquerade as evidence from the SSH target.
    if not os.getenv("DIAGNOSTIC_LOCAL_TARGET_ID"):
        return _unavailable("未配置目标端查询；不能用诊断服务网络冒充目标网络")
    dependencies = _allowed_dependencies()
    entry = dependencies.get(name)
    if not isinstance(entry, dict):
        return _unavailable("依赖未列入允许配置")
    host = entry.get("host")
    port = entry.get("port")
    if not isinstance(host, str) or not isinstance(port, int) or not 1 <= port <= 65535:
        return _unavailable("依赖配置无效")
    started = _now()
    try:
        with socket.create_connection((host, port), timeout=float(_limit(timeout, 3.0, 5.0))):
            reachable = True
    except OSError as exc:
        return {
            "data_source": "diagnostic_target",
            "policy_version": _POLICY_VERSION,
            "dependency": name,
            "host": host,
            "port": port,
            "reachable": False,
            "error_type": type(exc).__name__,
            "checked_at": started,
        }
    return {
        "data_source": "diagnostic_target",
        "policy_version": _POLICY_VERSION,
        "dependency": name,
        "host": host,
        "port": port,
        "reachable": reachable,
        "checked_at": started,
    }


def _diagnostic_query(operation: str, service: str = "", lines: int = 100,
                      dependency: str = "", probe: str = "tcp") -> dict[str, Any]:
    """SSH forced command: model chooses a query, never a host/command/path."""
    if operation not in {"catalog", "resources", "processes", "ports", "logs", "service", "dependency"}:
        return _unavailable("现场查询类型未授权")
    config_path = os.getenv("DIAGNOSTIC_SSH_CONFIG", "")
    if not config_path:
        return _unavailable("未配置单目标现场采集连接")
    try:
        config = json.loads(Path(config_path).read_text())
        # The mounted config and SSH key belong to the operator, not shell sandbox.
        argv = ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", "ClearAllForwardings=yes",
                "-o", "ConnectTimeout=3", "-o", "LogLevel=ERROR",
                "-o", f"UserKnownHostsFile={config['known_hosts']}",
                "-i", config["identity_file"], "-p", str(int(config.get("port", 22))),
                "--", f"{config['user']}@{config['host']}"]
        # stdin is bounded; server's forced command ignores SSH_ORIGINAL_COMMAND.
        request = {"operation": operation, "service": service,
                   "lines": min(200, max(1, int(lines))), "dependency": dependency, "probe": probe}
        response = subprocess.run(argv, input=json.dumps(request), capture_output=True,
                                  text=True, timeout=10)
        if len(response.stdout) > 65536:
            return _unavailable("采集端输出超过契约限制")
        payload = json.loads(response.stdout)
        if (response.returncode or payload.get("data_source") != "diagnostic_target"
                or payload.get("target_id") != config["target_id"]
                or payload.get("operation") != operation or not payload.get("collected_at")):
            return _unavailable("采集端身份/来源/时间或查询结果核验失败")
        root = _evidence_root()
        if root:
            name = f"query-{uuid.uuid4().hex}.json"
            path = root / name
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            payload["evidence_file"] = name
        return payload
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return _unavailable("现场采集未取得数据；可申请终端审批")


@mcp.tool()
def diagnostic_query(operation: str, service: str = "", lines: int = 100) -> dict[str, Any]:
    """从唯一授权目标实时查询 catalog/resources/processes/ports/logs/service。

    先 catalog 确认服务及依赖；只接受配置服务名，禁止自定义命令、文件路径或主机。
    返回目标身份和真实采集时间，证据保存供 diagnostic_exec 自由分析。
    权限不可见的服务/容器必须申请审批，不能用诊断容器自身状态代替。
    """
    return _diagnostic_query(operation, service, lines)


@mcp.tool()
def diagnostic_exec(command: str, timeout: float = 10.0, max_output: int = 8192) -> dict[str, Any]:
    return _diagnostic_exec(command, timeout, max_output)


@mcp.tool()
def diagnostic_probe_dependency(name: str, timeout: float = 3.0, probe: str = "tcp") -> dict[str, Any]:
    """从授权目标做配置依赖的 dns/tcp/health 探测；health 仅固定 GET、禁止跳转。"""
    return _diagnostic_probe_dependency(name, timeout, probe)


if __name__ == "__main__":
    import sys

    if not _token:
        raise RuntimeError("DIAGNOSTIC_TOKEN must be configured")
    mcp.run(
        transport="streamable-http",
        host=os.getenv("DIAGNOSTIC_HOST", "127.0.0.1"),
        port=int(os.getenv("DIAGNOSTIC_PORT", "8107")),
        path="/mcp",
    )
