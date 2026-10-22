"""Windows Service adapter for the outbound probe loop.

The collector and protocol remain usable in tests without importing pywin32;
the ServiceFramework subclass is defined only on Windows.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from .collector import WindowsCollector
from .config import ProbeConfig


SERVICE_NAME = "RagAIOpsProbe"


def collect_baseline(config: ProbeConfig) -> dict[str, Any]:
    """Synchronous smoke-test entry point used by installers and diagnostics."""
    return WindowsCollector(config).baseline()


if os.name == "nt":
    import win32service
    import win32serviceutil
    import win32event

    class ProbeService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "RAG AIOps Windows Probe"
        _svc_description_ = "Read-only Windows evidence collector for RAG AIOps"

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 1, 0, None)

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):
            # The CLI owns the full websocket loop.  Keeping this adapter small
            # avoids adding a second protocol implementation to the service DLL.
            from scripts.windows_probe import run_probe
            os.environ["RAG_AIOPS_PROBE_CONFIG"] = win32serviceutil.GetServiceCustomOption(
                self._svc_name_, "ConfigPath"
            )
            asyncio.run(run_probe(lambda: win32event.WaitForSingleObject(
                self.stop_event, 0
            ) == win32event.WAIT_OBJECT_0))
else:
    class ProbeService:
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "RAG AIOps Windows Probe"

