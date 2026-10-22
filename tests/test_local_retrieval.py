from pathlib import Path

import pytest

from src.agent.aiops import local_retrieval


def test_chinese_probe_symptom_prefers_matching_handwritten_runbook(tmp_path, monkeypatch):
    runbooks = tmp_path / "runbooks"
    runbooks.mkdir()
    (runbooks / "generic.md").write_text("通用运维经验。", encoding="utf-8")
    (runbooks / "windows-port-conflict.md").write_text(
        "Windows 端口冲突时检查端口归属、PID、服务状态和启动失败日志。",
        encoding="utf-8",
    )
    imported = runbooks / "Incident-Playbook" / "Playbooks" / "MITRE-ATTACK"
    imported.mkdir(parents=True)
    for index in range(4):
        (imported / f"network-port-{index}.md").write_text(
            "Network port security incident", encoding="utf-8"
        )
    monkeypatch.setattr(local_retrieval, "_RUNBOOKS_DIR", runbooks)
    monkeypatch.setattr(local_retrieval, "_KAGGLE_SOURCES", [])
    monkeypatch.setattr(local_retrieval, "_retrieve_kaggle", lambda *args, **kwargs: [])
    monkeypatch.setattr(local_retrieval, "_retrieve_hf", lambda *args, **kwargs: [])
    monkeypatch.setattr(local_retrieval, "_jsonl_index", None)
    monkeypatch.setattr(local_retrieval, "_EXPERIENCE_TOP_K", 1)

    result = local_retrieval.retrieve_local("端口冲突")

    assert "windows-port-conflict" in result
    assert "端口归属" in result
    assert "network-port-" not in result


def test_imported_high_score_does_not_bypass_handwritten_priority(tmp_path, monkeypatch):
    local = tmp_path / "guide.md"
    local.write_text("只读排查方法", encoding="utf-8")
    imported = tmp_path / "Incident-Playbook" / "security.md"
    imported.parent.mkdir()
    imported.write_text("导入安全资料", encoding="utf-8")
    monkeypatch.setattr(local_retrieval, "_iter_runbook_files", lambda: [imported, local])
    monkeypatch.setattr(local_retrieval, "_score_file", lambda p, q: 100 if p == imported else 1)
    monkeypatch.setattr(local_retrieval, "_EXPERIENCE_TOP_K", 1)
    result = local_retrieval.retrieve_local("端口冲突")
    assert "只读排查方法" in result
    assert "导入安全资料" not in result


@pytest.mark.parametrize("query, guide", [
    ("端口冲突", "windows-port-conflict"),
    ("下游数据库不可达", "windows-dependency-unreachable"),
    ("HTTP 503 应用错误", "windows-http-5xx"),
    ("Windows 服务停止", "windows-service-stopped"),
    ("CPU 内存磁盘异常", "windows-resource-anomaly"),
    ("Windows Event Log 错误", "windows-event-log"),
    ("应用文本日志报错", "windows-text-log"),
])
def test_shipped_windows_guides_retrievable_without_external_services(query, guide, monkeypatch):
    directory = Path(__file__).resolve().parents[1] / "data/runbooks/windows-probe"
    monkeypatch.setattr(local_retrieval, "_RUNBOOKS_DIR", directory)
    monkeypatch.setattr(local_retrieval, "_retrieve_kaggle", lambda *a, **k: [])
    monkeypatch.setattr(local_retrieval, "_retrieve_hf", lambda *a, **k: [])
    result = local_retrieval.retrieve_local(query)
    assert f"windows-probe/{guide}】" in result
