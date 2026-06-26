"""批量从 Kaggle 下载 IT 故障诊断数据集到 data/runbooks/kaggle/。

无需 Kaggle API key: kagglehub 支持匿名下载公开数据集。
用法: .venv/Scripts/python.exe scripts/download_kaggle_datasets.py
"""

import os
import shutil
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
os.environ.setdefault("USE_TORCH", "0")

import kagglehub

OUT_DIR = project_root / "data" / "runbooks" / "kaggle"

DATASETS: dict[str, str] = {
    "it-incident-mgmt": "nalisha/it-incident-management-and-system-analysis-dataset",
    "root-cause-analysis": "anjolaoluwaajayi/root-cause-analysis-dataset",
    "incident-response-log": "vipulshinde/incident-response-log",
    "synthetic-tickets": "alexandermeau/synthetic-it-support-tickets",
    "synthetic-itsm": "avii3301/synthetic-itsm-ticket-dataset",
}


def download_one(label: str, handle: str) -> Path | None:
    target = OUT_DIR / label
    if target.exists() and list(target.iterdir()):
        print(f"  [{label}] 已存在,跳过")
        return target

    print(f"  [{label}] 下载中... handle={handle}")
    try:
        dl_path = Path(kagglehub.dataset_download(handle))
        target.mkdir(parents=True, exist_ok=True)
        for src in dl_path.iterdir():
            dest = target / src.name
            if not dest.exists():
                if src.is_dir():
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
        print(f"    -> {target}")
        return target
    except Exception as e:
        print(f"    ❌ 失败: {e}")
        return None


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"目标目录: {OUT_DIR}\n")

    ok = 0
    for label, handle in DATASETS.items():
        r = download_one(label, handle)
        if r:
            ok += 1
        print()

    total_size = sum(
        f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file()
    )
    print(f"完成: {ok}/{len(DATASETS)} 下载成功")
    print(f"总大小: {total_size / 1024 / 1024:.1f} MB")
    return 0 if ok == len(DATASETS) else 1


if __name__ == "__main__":
    sys.exit(main())
