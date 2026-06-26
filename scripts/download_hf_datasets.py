"""批量从 HuggingFace 下载故障诊断数据集到 data/runbooks/huggingface/。

用法: .venv/Scripts/python.exe scripts/download_hf_datasets.py
"""

import json
import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("USE_TORCH", "0")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

DATASETS: dict[str, str] = {
    "sre-navigator": "Saksham-kaushish/sre-navigator-sft-data",
}


def download_one(label: str, ds_id: str) -> bool:
    target = OUT_DIR / label
    if target.exists() and list(target.iterdir()):
        print(f"  [{label}] 已存在,跳过")
        return True

    print(f"  [{label}] 下载中... {ds_id}")
    try:
        from datasets import load_dataset

        # HF 主站被墙,走镜像
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        ds = load_dataset(ds_id, cache_dir=str(OUT_DIR / ".cache" / label))


        target.mkdir(parents=True, exist_ok=True)

        if isinstance(ds, dict):
            for split_name, split_data in ds.items():
                out_file = target / f"{split_name}.jsonl"
                rows = 0
                with open(out_file, "w", encoding="utf-8") as f:
                    for row in split_data:
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        rows += 1
                print(f"    {split_name}: {rows} rows -> {out_file}")
        else:
            out_file = target / "data.jsonl"
            rows = 0
            with open(out_file, "w", encoding="utf-8") as f:
                for row in ds:
                    f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    rows += 1
            print(f"    {rows} rows -> {out_file}")

        return True
    except Exception as e:
        print(f"    ❌ 下载失败: {e}")
        return False


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"目标目录: {OUT_DIR}\n")

    ok = sum(1 for label, ds_id in DATASETS.items() if download_one(label, ds_id))

    total_size = sum(
        f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file() and ".cache" not in str(f)
    )
    print(f"\n完成: {ok}/{len(DATASETS)}")
    print(f"大小: {total_size / 1024 / 1024:.1f} MB")
    return 0 if ok == len(DATASETS) else 1


if __name__ == "__main__":
    sys.exit(main())
