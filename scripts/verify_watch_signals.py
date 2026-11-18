"""Free controlled HTTP/Probe/incident preflight; never starts a diagnosis."""
import argparse
import json
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.agent.aiops.continuous_monitor import classify_up_samples, record_observation, _diagnosis_trigger_samples
from src.agent.aiops.watch_signals import poll_probe_check
from src.database.models import OpsWatchIncident
from src.database.sql_session import Base
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import DependencyConfig, ProbeConfig, ServiceConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dsh-snapshot", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    trace = []
    result = {"model_calls": 0, "test_kind": "controlled_real_http_probe",
              "mall_acceptance": "not_run", "desktop_fresh_capture": "not_run"}
    state = {"status": 503, "delay": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(state["delay"])
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(b"controlled business response")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    engine = create_engine("sqlite:///" + str((args.output / "incidents.sqlite").resolve()))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    snapshot = args.dsh_snapshot.resolve() if args.dsh_snapshot else None
    config = ProbeConfig(target_id="watch-preflight", gateway_url="ws://127.0.0.1/unused",
        token_file=args.output / "unused-token",
        services={"dsh": ServiceConfig(service_name="dsh", text_logs=(str(snapshot),))} if snapshot else {},
        dependencies={"business": DependencyConfig("127.0.0.1", port, "http", "/business")})
    collector = WindowsCollector(config)
    check = {"kind": "http", "dependency": "business", "max_elapsed_ms": 500}

    def observe(label):
        payload = poll_probe_check(collector, "controlled-business", check)
        now = datetime.now(timezone.utc)
        with factory() as db:
            transition = record_observation(db, "controlled-business", payload, now)
        trace.append({"tool": "WindowsCollector.dependency_probe", "arguments": {"name": "business"},
                      "fixture_state": dict(state), "label": label, "result": payload,
                      "incident_transition": transition})
        return payload, transition

    try:
        for _ in range(3):
            _, opened = observe("real_http_503")
        assert opened["transition"] == "opened"
        state.update(status=200, delay=1.2)
        payload, slow = observe("real_http_latency")
        assert slow["observation"] == "unhealthy"
        assert payload["evidence"]["payload"]["http"]["status"] == 200
        state["delay"] = 0.0
        _, first = observe("real_http_recovery_1")
        _, second = observe("real_http_recovery_2")
        assert first["transition"] is None and second["transition"] == "resolved"
        if snapshot:
            desktop_check = {"kind": "desktop", "path": str(snapshot), "max_event_loop_lag_ms": 200}
            desktop = poll_probe_check(collector, "dsh", desktop_check)
            status, _, reason = classify_up_samples(desktop, datetime.now(timezone.utc), 120)
            trace.append({"tool": "WindowsCollector.text_logs",
                          "arguments": {"name": "dsh", "path": str(snapshot), "lines": 100},
                          "result": desktop, "classification": status, "reason": reason})
            result["historical_desktop_classification"] = status
            assert status == "unknown", "An archived snapshot must not prove present recovery"
        with factory() as db:
            incident = db.query(OpsWatchIncident).one()
            result["incident"] = {"id": incident.incident_uid, "status": incident.status,
                                  "evidence": incident.evidence}
            result["diagnosis_trigger_context"] = _diagnosis_trigger_samples(incident.evidence)
            assert result["diagnosis_trigger_context"][0]["measurement"]["http_status"] == 503
            assert result["diagnosis_trigger_context"][0]["rule"]["max_elapsed_ms"] == 500
        result["status"] = "passed"
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        engine.dispose()
        with socket.socket() as client:
            result["cleanup"] = {"server_thread_stopped": not thread.is_alive(),
                                 "port_released": client.connect_ex(("127.0.0.1", port)) != 0}
        (args.output / "tool-calls.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "incident"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
