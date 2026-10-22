"""Verify shipped Windows Probe runbooks with the real local retriever.

This is a free lexical retrieval check. It does not call embeddings, reranking,
or a dialogue model and it never treats the returned guide as live evidence.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.aiops import local_retrieval
from src.probe.storage import protect_evidence_path

GUIDE_DIR = ROOT / "data" / "runbooks" / "windows-probe"
CASES = (
    ("端口冲突", "windows-port-conflict"),
    ("下游数据库不可达", "windows-dependency-unreachable"),
    ("HTTP 503 应用错误", "windows-http-5xx"),
    ("Windows 服务停止", "windows-service-stopped"),
    ("CPU 内存磁盘异常", "windows-resource-anomaly"),
    ("Windows Event Log 错误", "windows-event-log"),
    ("应用文本日志报错", "windows-text-log"),
)


def main() -> None:
    output = ROOT / "runtime" / f"windows-runbook-verification-{uuid4().hex}"
    output.mkdir(parents=True)
    protect_evidence_path(output)
    rows = []
    for query, expected in CASES:
        started = time.perf_counter()
        context = local_retrieval.retrieve_local(query)
        labels = [line.strip() for line in context.splitlines()
                  if line.strip().startswith("【")]
        assert labels and expected in labels[0], (query, labels)
        source = GUIDE_DIR / f"{expected}.md"
        rows.append({
            "query": query,
            "expected": expected,
            "top_labels": labels,
            "context": context,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        })
    report = {
        "ok": True,
        "model_calls": 0,
        "scope": "local lexical retrieval; not vector search or model diagnosis",
        "cases": rows,
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": True, "directory": str(output),
                      "case_count": len(rows), "model_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
