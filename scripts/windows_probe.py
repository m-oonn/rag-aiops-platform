"""Install/validate/run the Windows Probe service.

The command is intentionally small and safe: it never accepts a command from
the agent.  Service installation is available only on Windows with pywin32.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import subprocess
import shutil
import zipfile
import uuid
from typing import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.probe.protocol import RequestIdTracker, hello
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import DEFAULT_CONFIG_DIR, ProbeConfigError, load_config
from src.probe.windows.service import ProbeService
from src.probe.windows.worker import collect_isolated


def config_path() -> Path:
    return Path(os.environ.get("RAG_AIOPS_PROBE_CONFIG", DEFAULT_CONFIG_DIR / "config.toml"))


def _load_validated_config():
    cfg = load_config(config_path())
    try:
        token = cfg.token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProbeConfigError(f"cannot read token file: {cfg.token_file}") from exc
    if not token:
        raise ProbeConfigError("token file is empty")
    if cfg.gateway_url.startswith("wss://") and cfg.tls_ca_file and not cfg.tls_ca_file.is_file():
        raise ProbeConfigError(f"TLS CA file does not exist: {cfg.tls_ca_file}")
    return cfg


def validate() -> int:
    cfg = _load_validated_config()
    print(json.dumps({"target_id": cfg.target_id, "gateway": cfg.gateway_url,
                      "services": sorted(cfg.services), "dependencies": sorted(cfg.dependencies)}, ensure_ascii=False))
    return 0


def _set_acl(path: Path, *, writable: bool = False) -> None:
    rights = "(OI)(CI)M" if writable else "(OI)(CI)RX"
    if path.is_file():
        rights = "R"
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                    f"*S-1-5-19:{rights}", "*S-1-5-32-544:(OI)(CI)F" if path.is_dir() else "*S-1-5-32-544:F",
                    "*S-1-5-18:(OI)(CI)F" if path.is_dir() else "*S-1-5-18:F"],
                   check=True, capture_output=True, text=True)


def _deploy_runtime(destination: Path) -> Path:
    # Service code must not be loaded from a user-writable development checkout.
    import psutil
    import websockets
    import win32service
    base = Path(sys.base_prefix)
    site = Path(win32service.__file__).parent.parent
    destination.mkdir(exist_ok=False)
    _set_acl(destination)
    for source in (*base.glob("*.dll"), base / "python.exe"):
        shutil.copy2(source, destination / source.name)
    # Conda keeps OpenSSL outside DLLs; the service has no interactive PATH.
    for pattern in ("libssl*.dll", "libcrypto*.dll"):
        for source in (base / "Library" / "bin").glob(pattern):
            shutil.copy2(source, destination / source.name)
    shutil.copytree(base / "DLLs", destination / "DLLs")
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    with zipfile.ZipFile(destination / f"{version}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in (base / "Lib").rglob("*"):
            relative = source.relative_to(base / "Lib")
            if source.is_file() and not set(relative.parts).intersection({"site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter"}):
                archive.write(source, str(relative))
    packages = destination / "site-packages"
    packages.mkdir()
    for module in (psutil, websockets):
        shutil.copytree(Path(module.__file__).parent, packages / module.__name__, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(site / "win32", packages / "win32", ignore=shutil.ignore_patterns("__pycache__"))
    for source in site.glob("*.py"):
        if source.name in {"win32con.py", "winerror.py", "win32serviceutil.py", "pywintypes.py", "pythoncom.py"}:
            shutil.copy2(source, packages / source.name)
    for source in (site / "pywin32_system32").glob("*.dll"):
        shutil.copy2(source, destination / source.name)
    host = site / "win32" / "pythonservice.exe"
    if not host.exists():
        host = Path(sys.exec_prefix) / "pythonservice.exe"
    shutil.copy2(host, destination / "pythonservice.exe")
    app = destination / "app"
    (app / "src").mkdir(parents=True)
    (app / "src" / "__init__.py").touch()
    shutil.copytree(PROJECT_ROOT / "src" / "probe", app / "src" / "probe", ignore=shutil.ignore_patterns("__pycache__"))
    (app / "scripts").mkdir()
    (app / "scripts" / "__init__.py").touch()
    shutil.copy2(Path(__file__), app / "scripts" / "windows_probe.py")
    (destination / f"{version}._pth").write_text(
        f"{version}.zip\nDLLs\nsite-packages\nsite-packages/win32\nsite-packages/win32/lib\napp\n.\nimport site\n", encoding="utf-8")
    subprocess.run([str(destination / "python.exe"), "-c",
                    "import ssl, psutil, websockets; from src.probe.windows.service import ProbeService"], check=True)
    return destination / "pythonservice.exe"


def install_service() -> int:
    if os.name != "nt":
        raise RuntimeError("Windows Service installation is only available on Windows")
    import win32service
    import win32serviceutil
    # Validate before changing ACLs, creating directories, or registering
    # anything with the Service Control Manager.
    cfg = _load_validated_config()
    # Query without swallowing access errors; never replace an existing service.
    try:
        win32serviceutil.QueryServiceStatus(ProbeService._svc_name_)
    except win32service.error as exc:
        if exc.winerror != 1060:
            raise
    else:
        raise RuntimeError("Probe service is already installed")
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for child in (DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_DIR / "logs", DEFAULT_CONFIG_DIR / "spool"):
        child.mkdir(parents=True, exist_ok=True)
        _set_acl(child, writable=child.name == "spool")
    for secret in (cfg.token_file, cfg.tls_ca_file, config_path()):
        if secret is not None:
            _set_acl(secret)
    executable = _deploy_runtime(DEFAULT_CONFIG_DIR / f"runtime-{uuid.uuid4().hex[:12]}")
    win32serviceutil.InstallService(
        "src.probe.windows.service.ProbeService", ProbeService._svc_name_, ProbeService._svc_display_name_,
        description=ProbeService._svc_description_,
        startType=win32service.SERVICE_AUTO_START,
        userName=r"NT AUTHORITY\LocalService",
        exeName=str(executable),
    )
    win32serviceutil.SetServiceCustomOption(ProbeService._svc_name_, "ConfigPath", str(config_path().resolve()))
    return 0


def upgrade_service() -> int:
    """Stage a protected runtime, then switch only our LocalService service."""
    import win32service
    import win32serviceutil
    _load_validated_config()
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    handle = None
    was_running = False
    changed = False
    try:
        handle = win32service.OpenService(manager, ProbeService._svc_name_,
            win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_QUERY_STATUS)
        previous = win32service.QueryServiceConfig(handle)
        old_path = Path(previous[3].strip('"')).resolve()
        root = DEFAULT_CONFIG_DIR.resolve()
        if previous[7].lower() != r'nt authority\localservice' or not old_path.is_relative_to(root):
            raise RuntimeError('Refusing to upgrade an unexpected service account or runtime path')
        registered = Path(win32serviceutil.GetServiceCustomOption(ProbeService._svc_name_, 'ConfigPath')).resolve()
        if registered != config_path().resolve():
            raise RuntimeError('Upgrade must use the registered Probe configuration')
        executable = _deploy_runtime(root / f'runtime-{uuid.uuid4().hex[:12]}')
        was_running = win32serviceutil.QueryServiceStatus(ProbeService._svc_name_)[1] == win32service.SERVICE_RUNNING
        if was_running:
            win32serviceutil.StopService(ProbeService._svc_name_)
            win32serviceutil.WaitForServiceStatus(ProbeService._svc_name_, win32service.SERVICE_STOPPED, 30)
        win32service.ChangeServiceConfig(handle, win32service.SERVICE_NO_CHANGE,
            win32service.SERVICE_NO_CHANGE, win32service.SERVICE_NO_CHANGE, f'"{executable}"',
            None, 0, None, None, None, None)
        changed = True
        if was_running:
            win32serviceutil.StartService(ProbeService._svc_name_)
            win32serviceutil.WaitForServiceStatus(ProbeService._svc_name_, win32service.SERVICE_RUNNING, 30)
        print(json.dumps({'service': ProbeService._svc_name_, 'runtime': str(executable.parent), 'upgraded': True}))
        return 0
    except Exception:
        if changed:
            win32service.ChangeServiceConfig(handle, win32service.SERVICE_NO_CHANGE,
                win32service.SERVICE_NO_CHANGE, win32service.SERVICE_NO_CHANGE, previous[3],
                None, 0, None, None, None, None)
        if was_running and win32serviceutil.QueryServiceStatus(ProbeService._svc_name_)[1] == win32service.SERVICE_STOPPED:
            win32serviceutil.StartService(ProbeService._svc_name_)
        raise
    finally:
        if handle is not None:
            win32service.CloseServiceHandle(handle)
        win32service.CloseServiceHandle(manager)


async def _sleep_with_stop(delay: float, should_stop: Callable[[], bool]) -> bool:
    """Sleep in short slices so a Windows Service stop is noticed promptly."""
    deadline = asyncio.get_running_loop().time() + max(0.0, delay)
    while True:
        if should_stop():
            return True
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.2, remaining))


async def run_probe(should_stop: Callable[[], bool] | None = None) -> None:
    """Connect outbound and serve only fixed collector operations."""
    import ssl
    import websockets

    cfg = load_config(config_path())
    token = cfg.token_file.read_text(encoding="utf-8").strip()
    should_stop = should_stop or (lambda: False)
    ssl_context = None
    if cfg.gateway_url.startswith("wss://"):
        ssl_context = ssl.create_default_context(cafile=str(cfg.tls_ca_file) if cfg.tls_ca_file else None)
    delay = 1
    while not should_stop():
        try:
            async with websockets.connect(cfg.gateway_url, additional_headers={"Authorization": f"Bearer {token}"}, ssl=ssl_context, open_timeout=5, close_timeout=2) as ws:
                await ws.send(json.dumps(hello(target_id=cfg.target_id, hostname=socket.gethostname())))
                await asyncio.wait_for(ws.recv(), timeout=5)
                delay = 1
                request_ids = RequestIdTracker()
                next_baseline = 0.0
                while not should_stop():
                    now = asyncio.get_running_loop().time()
                    if now >= next_baseline:
                        baseline = await collect_isolated(config_path(), "baseline", {}, should_stop)
                        await ws.send(json.dumps({"type": "event", "method": "baseline.report", "params": baseline}))
                        next_baseline = now + cfg.baseline_interval_seconds
                    timeout = max(0.1, min(5.0, next_baseline - now))
                    try:
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                    except asyncio.TimeoutError:
                        if should_stop():
                            return
                        continue
                    if not isinstance(message, dict) or "id" not in message:
                        continue
                    try:
                        request_id, operation, params = __import__("src.probe.protocol", fromlist=["validate_request"]).validate_request(message)
                        if not request_ids.remember(request_id):
                            await ws.send(json.dumps({"id": request_id, "error": {
                                "code": "duplicate_request_id",
                                "message": "request id has already been processed",
                            }}))
                            continue
                        result = await collect_isolated(config_path(), operation, params, should_stop)
                        await ws.send(json.dumps({"id": request_id, "result": result}, ensure_ascii=False, default=str))
                    except Exception as exc:
                        await ws.send(json.dumps({"id": message.get("id"), "error": {"code": "collector_error", "message": str(exc)[:200]}}))
        except Exception:
            if await _sleep_with_stop(delay, should_stop):
                return
            delay = min(delay * 2, 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["install", "upgrade", "uninstall", "status", "validate", "run"])
    args = parser.parse_args(argv)
    if args.action == "validate":
        return validate()
    if args.action == "install":
        return install_service()
    if args.action == "upgrade":
        return upgrade_service()
    if args.action == "uninstall":
        if os.name != "nt":
            raise RuntimeError("Windows Service uninstallation is only available on Windows")
        import win32serviceutil
        win32serviceutil.RemoveService(ProbeService._svc_name_)
        return 0
    if args.action == "status":
        if os.name != "nt":
            print("offline: not running on Windows")
            return 0
        import win32serviceutil
        try:
            status = win32serviceutil.QueryServiceStatus(ProbeService._svc_name_)
            print(json.dumps({"service": ProbeService._svc_name_, "status": status[1]}))
        except Exception:
            print(json.dumps({"service": ProbeService._svc_name_, "status": "not_installed"}))
        return 0
    cfg = load_config(config_path())
    collector = WindowsCollector(cfg)
    print(json.dumps(collector.baseline(), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

