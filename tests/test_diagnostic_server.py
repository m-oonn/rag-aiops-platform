import json
import os
import sys
from unittest.mock import Mock
from pathlib import Path

from mcp_servers import diagnostic_server as server


def test_diagnostic_exec_fails_closed_when_boundary_is_disabled(monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_EXEC_ENABLED", raising=False)
    result = server._diagnostic_exec("printf should-not-run")
    assert result["data_source"] == "unavailable"


def test_diagnostic_exec_fails_closed_without_sandbox(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_EXEC_ENABLED", "true")
    monkeypatch.setattr(server, "_sandbox_command", lambda *_: None)
    result = server._diagnostic_exec("printf should-not-run")
    assert result["data_source"] == "unavailable"
    assert "未执行命令" in result["message"]


def test_diagnostic_exec_returns_auditable_real_output(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_EXEC_ENABLED", "true")
    if os.name == "nt":
        monkeypatch.setattr(server, "_sandbox_command", lambda command, _evidence: command)
    else:
        monkeypatch.setattr(server, "_sandbox_command", lambda command, _evidence: ["/bin/sh", "-lc", command])
    command = "echo healthy" if os.name == "nt" else "printf 'healthy'"
    result = server._diagnostic_exec(command, max_output=64)
    assert result["data_source"] == "diagnostic_analysis"
    assert result["stdout"].strip() == "healthy"
    assert result["exit_code"] == 0
    assert result["policy_version"] == "diagnostic-shell.1"
    assert result["started_at"] and result["finished_at"]


def test_diagnostic_exec_kills_timed_out_process(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_EXEC_ENABLED", "true")
    if os.name == "nt":
        monkeypatch.setattr(server, "_sandbox_command", lambda command, _evidence: command)
    else:
        monkeypatch.setattr(server, "_sandbox_command", lambda command, _evidence: ["/bin/sh", "-lc", command])
    command = "ping -n 5 127.0.0.1" if os.name == "nt" else "sleep 2"
    result = server._diagnostic_exec(command, timeout=0.1)
    assert result["data_source"] == "diagnostic_analysis"
    assert result["timed_out"] is True


def test_dependency_probe_only_uses_named_allowlist(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_LOCAL_TARGET_ID", "local-test")
    monkeypatch.setenv(
        "DIAGNOSTIC_ALLOWED_DEPENDENCIES",
        json.dumps({"local": {"host": "127.0.0.1", "port": 1}}),
    )
    denied = server._diagnostic_probe_dependency("unknown")
    assert denied["data_source"] == "unavailable"
    result = server._diagnostic_probe_dependency("local")
    assert result["data_source"] == "diagnostic_target"
    assert result["dependency"] == "local"


def test_evidence_read_is_confined_to_read_only_root(monkeypatch, tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "service.log").write_text("started", encoding="utf-8")
    (tmp_path / "secret").write_text("no", encoding="utf-8")
    monkeypatch.setenv("DIAGNOSTIC_EVIDENCE_DIR", str(evidence))

    listed = server.diagnostic_list_evidence.fn()
    assert listed["files"][0]["name"] == "service.log"
    read = server.diagnostic_read_evidence.fn("service.log")
    assert read["content"] == "started"
    denied = server.diagnostic_read_evidence.fn("../secret")
    assert denied["data_source"] == "unavailable"


def test_sandbox_startup_failure_is_unavailable(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_EXEC_ENABLED", "true")
    monkeypatch.setattr(server, "_sandbox_command", lambda *_: [sys.executable, "-c",
        "import sys; sys.stderr.write('bwrap: Operation not permitted'); sys.exit(1)"])
    result = server._diagnostic_exec("echo must-not-run")
    assert result["data_source"] == "unavailable"


def test_large_output_is_drained_with_bounded_retention(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_EXEC_ENABLED", "true")
    monkeypatch.setattr(server, "_sandbox_command", lambda *_: [sys.executable, "-c",
        "import sys; sys.stdout.write('x'*1000000); sys.stderr.write('y'*1000000)"])
    result = server._diagnostic_exec("unused", max_output=64)
    assert len(result["stdout"]) == len(result["stderr"]) == 64
    assert result["output_truncated"]
    assert result["exit_code"] == 0


def test_remote_query_verifies_target_identity_and_stores_provenance(monkeypatch, tmp_path):
    config = tmp_path / "target.json"
    config.write_text(json.dumps({"host": "test-target", "user": "collector", "target_id": "test-target",
        "identity_file": "/connection/key", "known_hosts": "/connection/known_hosts"}))
    monkeypatch.setenv("DIAGNOSTIC_SSH_CONFIG", str(config))
    monkeypatch.setenv("DIAGNOSTIC_EVIDENCE_DIR", str(tmp_path))
    query = Mock(return_value=type("Result", (), {"returncode": 0, "stdout": json.dumps({
        "data_source": "diagnostic_target", "target_id": "test-target", "operation": "catalog",
        "collected_at": "2026-10-14T00:00:00+00:00", "services": {}})})())
    monkeypatch.setattr(server.subprocess, "run", query)
    result = server._diagnostic_query("catalog")
    assert result["target_id"] == "test-target"
    assert (tmp_path / result["evidence_file"]).is_file()
    assert "StrictHostKeyChecking=yes" in query.call_args.args[0]
    query.return_value.stdout = query.return_value.stdout.replace("test-target", "wrong-target")
    assert server._diagnostic_query("catalog")["data_source"] == "unavailable"
