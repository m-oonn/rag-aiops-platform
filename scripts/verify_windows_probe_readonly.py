"""Read-only acceptance check against the current Windows machine.

The script creates a temporary allow-list configuration and never installs a
service, opens a listener, changes ACLs, or sends a gateway request.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import ProbeConfigError, load_config
from src.probe.evidence import validate_evidence


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rag-aiops-probe-readonly-") as directory:
        root = Path(directory)
        token = root / "token"
        token.write_text("read-only-smoke-token", encoding="utf-8")
        log_directory = root / "allowed"
        log_directory.mkdir()
        log_file = log_directory / "application.log"
        log_file.write_text(
            "INFO startup\nAuthorization: Bearer local-secret\npassword=do-not-leak\nERROR probe smoke\n",
            encoding="utf-8",
        )
        config_file = root / "config.toml"
        config_file.write_text(
            "\n".join([
                "target_id = 'windows-local-readonly'",
                "gateway_url = 'ws://127.0.0.1:9/probe/ws'",
                f"token_file = '{token.as_posix()}'",
                "baseline_interval_seconds = 60",
                "",
                "[services.event_log]",
                "service_name = 'EventLog'",
                "process_names = ['svchost.exe']",
                "log_channels = ['Application']",
                f"text_logs = ['{log_file.as_posix()}']",
                "",
            ]),
            encoding="utf-8",
        )
        config = load_config(config_file)
        collector = WindowsCollector(config)
        baseline = collector.baseline()
        event_logs = collector.event_logs("event_log", since_minutes=60, limit=5)
        text_logs = collector.text_logs("event_log", str(log_file), lines=10)
        validate_evidence(event_logs, target_id=config.target_id)
        validate_evidence(text_logs, target_id=config.target_id)
        assert "local-secret" not in json.dumps(text_logs, ensure_ascii=False)
        assert "do-not-leak" not in json.dumps(text_logs, ensure_ascii=False)
        outside = root / "outside.log"
        outside.write_text("outside", encoding="utf-8")
        try:
            try:
                collector.text_logs("event_log", str(outside), lines=1)
            except ProbeConfigError:
                path_boundary = True
            else:
                path_boundary = False
        finally:
            outside.unlink(missing_ok=True)

    service = baseline["services"]["event_log"]
    resources = baseline["resources"]["payload"]
    processes = baseline["processes"]["payload"]
    ports = baseline["ports"]["payload"]
    summary = {
        "ok": True,
        "target_id": baseline["target_id"],
        "service": {
            "operation": service["operation"],
            "state": service["payload"].get("state"),
            "error": service["payload"].get("error"),
        },
        "resources": sorted(key for key in ("cpu_percent", "memory", "disks", "network") if key in resources),
        "process_count": len(processes.get("processes", [])),
        "port_count": len(ports.get("ports", [])),
        "truncated": bool(baseline["processes"].get("truncated") or baseline["ports"].get("truncated")),
        "event_logs": {
            "operation": event_logs["operation"],
            "event_count": len(event_logs["payload"].get("events", [])),
            "error": event_logs["payload"].get("error"),
        },
        "text_logs": {
            "operation": text_logs["operation"],
            "line_count": len(text_logs["payload"].get("lines", [])),
            "redacted": "local-secret" not in json.dumps(text_logs, ensure_ascii=False),
        },
        "text_path_boundary_rejected": path_boundary,
    }
    assert summary["text_logs"]["redacted"] and path_boundary
    assert summary["event_logs"]["error"] is None, summary["event_logs"]
    assert summary["service"]["error"] is None, summary["service"]
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
