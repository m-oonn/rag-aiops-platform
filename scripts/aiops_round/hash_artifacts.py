"""Read-only: hash the round's persisted artifacts so a restart can be compared."""
import hashlib
import json
import sys
from pathlib import Path
from rounddir import round_dir

D = round_dir()
phase = sys.argv[1] if len(sys.argv) > 1 else 'before-restart'

targets = [
    'product/runs.sqlite', 'product/runs.sqlite-wal', 'product/checkpoints.sqlite',
    'product/tool_trace.json', 'product/knowledge_trace.json',
    'product-model/cost.json', 'product-model/run-budget.json',
    'result-summary.json', 'environment.json',
]
record = {'phase': phase, 'files': {}}
for rel in targets:
    p = D / rel
    if not p.exists():
        record['files'][rel] = None
        continue
    data = p.read_bytes()
    record['files'][rel] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
ev = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((D / 'product/evidence').glob('*.json'))}
record['evidence_files'] = ev
record['evidence_count'] = len(ev)

out = D / f'artifacts-{phase}.json'
out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record['files'], ensure_ascii=False, indent=1))
print('evidence files:', record['evidence_count'])
print('written:', out)
