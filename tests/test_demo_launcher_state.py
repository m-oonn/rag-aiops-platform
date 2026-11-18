from scripts import launch_demo


def test_launcher_creates_state_directory_and_reads_saved_pids(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime" / "demo" / "pids.json"
    monkeypatch.setattr(launch_demo, "PID_FILE", state_file)
    assert launch_demo.load_pids() == {}

    saved = {"api": {"pid": 123, "name": "API"}}
    launch_demo.save_pids(saved)

    assert state_file.is_file()
    assert launch_demo.load_pids() == saved
    assert not (tmp_path / ".demo_pids.json").exists()


def test_launcher_tolerates_corrupt_state_file(tmp_path, monkeypatch):
    state_file = tmp_path / "pids.json"
    state_file.write_text("invalid JSON", encoding="utf-8")
    monkeypatch.setattr(launch_demo, "PID_FILE", state_file)
    assert launch_demo.load_pids() == {}


def test_probe_runtime_uses_local_config_token_without_exposing_it(tmp_path, monkeypatch):
    probe_dir = tmp_path / "RagAIOpsProbe"
    probe_dir.mkdir()
    token_file = probe_dir / "token"
    token_file.write_text("local-test-token", encoding="utf-8")
    config_file = probe_dir / "config.toml"
    config_file.write_text(
        "target_id = 'windows-local-01'\n"
        "gateway_url = 'ws://127.0.0.1:18767/probe/ws'\n"
        f"token_file = '{token_file.as_posix()}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    env, token = launch_demo.probe_runtime()

    assert token == "local-test-token"
    assert env == {
        "PROBE_ENABLED": "true",
        "PROBE_TARGET_ID": "windows-local-01",
        "PROBE_TOKEN": "local-test-token",
        "MCP_PROBE_URL": "http://127.0.0.1:18767/mcp",
    }


def test_probe_runtime_rejects_non_loopback_gateway(tmp_path, monkeypatch):
    probe_dir = tmp_path / "RagAIOpsProbe"
    probe_dir.mkdir()
    (probe_dir / "token").write_text("local-test-token", encoding="utf-8")
    (probe_dir / "config.toml").write_text(
        "target_id = 'windows-local-01'\n"
        "gateway_url = 'wss://192.168.1.20:18767/probe/ws'\n"
        f"token_file = '{(probe_dir / 'token').as_posix()}'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    import pytest
    with pytest.raises(ValueError, match="只允许本机 Probe 网关"):
        launch_demo.probe_runtime()


def test_probe_gateway_compose_up_runs_detached(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return launch_demo.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launch_demo.subprocess, "run", fake_run)

    result = launch_demo.probe_compose("up", {"PROBE_TOKEN": "test-token"})

    assert result.returncode == 0
    assert captured["command"][-4:] == ["up", "--build", "-d", "probe-gateway"]
