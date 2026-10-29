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
