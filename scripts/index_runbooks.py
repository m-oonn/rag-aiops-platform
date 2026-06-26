"""把所有 runbook .md + .jsonl 向量化后插 Milvus。

前提: Milvus 已通过 WSL2 Docker 启动在 localhost:19530。
用法: export USE_TORCH=0 && .venv/Scripts/python.exe scripts/index_runbooks.py
"""

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("USE_TORCH", "0")

from src.database.vector_db import MilvusClient
from src.embedding import get_embedding_service
from src.models.vector import VectorRecord
from src.utils.logger import logger

RUNBOOKS_DIR = project_root / "data" / "runbooks"
SKIP_DIRS = {".git", "__pycache__", "rca", "main", "camel", "chatdev", "faiss_index_postmortem", ".cache"}
SKIP_NAMES = {"README.md", "SECURITY.md", "LICENSE", "SUPPORT.md", "CODE_OF_CONDUCT.md"}
CHUNK_SIZE = 500  # 每条向量化文本的字符上限
BATCH_SIZE = 20


def iter_chunks():
    """遍历所有 runbook 文件,切成 <=500 字的块。"""
    for fp in RUNBOOKS_DIR.rglob("*"):
        if not fp.is_file():
            continue
        if any(part.name in SKIP_DIRS for part in fp.parents):
            continue
        if fp.name in SKIP_NAMES:
            continue

        if fp.suffix == ".md":
            text = fp.read_text(encoding="utf-8").strip()
            if not text:
                continue
            source = f"runbook:{fp.relative_to(RUNBOOKS_DIR)}"
            for i in range(0, len(text), CHUNK_SIZE):
                chunk = text[i : i + CHUNK_SIZE]
                yield source, chunk

        elif fp.suffix == ".jsonl":
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        rec = json.loads(line.strip())
                        text = json.dumps(rec, ensure_ascii=False, default=str)
                        if len(text) < 20:
                            continue
                        source = f"jsonl:{fp.relative_to(RUNBOOKS_DIR)}"
                        yield source, text[:CHUNK_SIZE]
            except Exception:
                pass


def main() -> int:
    client = MilvusClient()
    if not client._available:
        logger.error("Milvus 不可用,取消索引")
        return 1

    emb = get_embedding_service()
    logger.info(f"开始索引 runbooks (嵌入模型: {emb})")

    batch: list[VectorRecord] = []
    total = 0

    for source, text in iter_chunks():
        vector = emb.embed_query(text)
        if not vector or len(vector) != 1536:
            continue
        rec = VectorRecord(
            id=f"runbook_{abs(hash(text))}",
            values=vector,
            metadata={"text": text, "source": str(source), "kb_id": 0},
        )
        batch.append(rec)
        if len(batch) >= BATCH_SIZE:
            client.insert(batch)
            total += len(batch)
            print(f"  已插入 {total} 条...")
            batch = []

    if batch:
        client.insert(batch)
        total += len(batch)

    logger.info(f"索引完成,总计 {total} 条记录")
    print(f"\n完成: {total} 条 runbook 记录已索引到 Milvus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
