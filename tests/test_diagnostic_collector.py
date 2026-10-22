import pytest

from mcp_servers.diagnostic_collector import collect


def test_collector_logs_only_accept_configured_service_and_path(tmp_path):
    log = tmp_path / "service.log"
    log.write_text("started\nconnection refused\n")
    config = {"target_id": "test-target", "services": {"api": {"logs": [str(log)]}}}
    result = collect({"operation": "logs", "service": "api", "lines": 1,
                      "path": "/etc/shadow", "command": "touch /tmp/unsafe"}, config)
    assert result["logs"][0]["content"] == "connection refused"
    assert result["target_id"] == "test-target" and result["collected_at"]
    with pytest.raises(ValueError):
        collect({"operation": "logs", "service": "unconfigured"}, config)


def test_collector_refuses_arbitrary_exec_or_network_target():
    config = {"target_id": "test-target", "services": {}}
    with pytest.raises(ValueError):
        collect({"operation": "exec", "command": "id"}, config)
    with pytest.raises(ValueError):
        collect({"operation": "dependency", "dependency": "unconfigured",
                 "host": "unapproved-host", "port": 22}, config)


def test_dependency_health_cannot_use_unconfigured_endpoint():
    config = {"target_id": "test-target", "services": {},
              "dependencies": {"cache": {"host": "127.0.0.1", "port": 1}}}
    with pytest.raises(ValueError):
        collect({"operation": "dependency", "dependency": "cache", "probe": "health",
                 "path": "/business/write"}, config)
    with pytest.raises(ValueError):
        collect({"operation": "dependency", "dependency": "cache", "probe": "exec"}, config)
