"""Read-only pre/post click snapshot of a round ledger and budget manifest."""
import hashlib
import json
from pathlib import Path

from rounddir import round_dir

ROOT = Path(__file__).resolve().parents[2]
RUN = round_dir()


def digest(path: Path) -> dict:
    content = path.read_bytes()
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def ledger() -> dict:
    path = RUN / "product-model" / "cost.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["requests"]
    return {
        "file": digest(path),
        "requests": len(rows),
        "last_number": rows[-1]["number"] if rows else None,
        "reserved_cny": data["reserved_cny"],
        "limit_cny": data["limit_cny"],
        "blocked_requests": len(data.get("blocked_requests") or []),
        "request_limits": data.get("request_limits"),
        "unknown_usage_rows": [r["number"] for r in rows
                               if (r.get("usage") or {}).get("total_tokens") is None],
        "unpriced_rows": [r["number"] for r in rows if not r.get("pricing_verified")],
    }


def main(phase: str) -> None:
    inputs = sorted((RUN / "product-model" / "model-inputs").glob("*.json"))
    payload = {
        "phase": phase,
        "manifest": json.loads((RUN / "product-model" / "run-budget.json").read_text(encoding="utf-8")),
        "ledger": ledger(),
        "model_inputs": {"count": len(inputs),
                         "sha256": hashlib.sha256(b"".join(
                             hashlib.sha256(p.read_bytes()).digest() for p in inputs)).hexdigest()},
        "environment": {key: json.loads((RUN / "environment.json").read_text(encoding="utf-8")).get(key)
                        for key in ("status", "round", "target_id", "scenario", "business_request")},
    }
    out = RUN / f"ledger-{phase}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else 'before')
