"""Disposable collector process: fixed operations only, no command execution."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Callable

from src.probe.protocol import OPERATIONS
from .collector import WindowsCollector
from .config import load_config


async def collect_isolated(config_path: Path, operation: str, params: dict,
                           should_stop: Callable[[], bool] = lambda: False,
                           *, timeout: float = 15.0) -> dict:
    if operation not in OPERATIONS | {"baseline"}:
        raise ValueError("unsupported collector operation")
    # pythonservice.exe hosts a service, not a Python command line interpreter.
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonservice.exe":
        executable = executable.with_name("python.exe")
    process = await asyncio.create_subprocess_exec(
        str(executable), "-m", "src.probe.windows.worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=0x08000000 if os.name == "nt" else 0,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    payload = json.dumps({"config": str(config_path), "operation": operation, "params": params}).encode()
    response = asyncio.create_task(process.communicate(payload))
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        while not response.done():
            if should_stop():
                raise InterruptedError("probe stopped during collection")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("collection exceeded time limit")
            await asyncio.wait({response}, timeout=0.1)
        output, _ = response.result()
        if process.returncode:
            raise RuntimeError("collector process failed")
        result = json.loads(output)
        if "error" in result:
            raise ValueError(result["error"])
        return result["result"]
    finally:
        if process.returncode is None:
            process.kill()
        await response


def main() -> None:
    request = json.load(sys.stdin)
    collector = WindowsCollector(load_config(request["config"]))
    try:
        operation = request["operation"]
        result = collector.baseline() if operation == "baseline" else collector.collect(operation, request["params"])
        output = {"result": result}
    except Exception as exc:
        output = {"error": type(exc).__name__}
    sys.stdout.buffer.write(json.dumps(output, ensure_ascii=False, default=str).encode("utf-8"))


if __name__ == "__main__":
    main()
