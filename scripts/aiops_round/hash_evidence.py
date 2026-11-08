"""Read-only: hash every 040 acceptance artifact for the acceptance record."""
import hashlib
import json
from pathlib import Path
from rounddir import round_dir

D = round_dir()
targets = [
    'environment.json', 'environment-ready.json', 'preflight.json', 'login.json', 'symptom.txt',
    'gateway.log', 'start.png', 'after-refresh.png', 'report.txt', 'report-headings.json',
    'acceptance-live.json', 'acceptance-after-restart.json', 'run-detail.json',
    'artifacts-before-restart.json', 'artifacts-after-restart.json',
    'logical-digest-after-restart.json', 'logical-digest-final.json', 'ckpt-decoded.json',
    'result-summary.json', 'decision-audit.json', 'latest-state.json',
    'event-trail-reconstructed.json', 'chain-equivalence.json',
    'gate-b-acceptance.json', 'gate-b-checks.json',
    'wal-attribution.json', 'heartbeat-drift.json', 'ledger-before.json',
    'product-model/cost.json', 'product-model/run-budget.json',
    'product/runs.sqlite', 'product/checkpoints.sqlite',
    'product/tool_trace.json', 'product/knowledge_trace.json',
]
record = {'dir': str(D.resolve()), 'files': {}}
for rel in targets:
    p = D / rel
    if not p.exists():
        record['files'][rel] = None
        continue
    data = p.read_bytes()
    record['files'][rel] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

ev_dir = D / 'product/evidence'
model_inputs = D / 'product-model/model-inputs'
record['evidence'] = {'count': len(list(ev_dir.glob('*.json'))),
                      'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(ev_dir.glob('*.json'))}}
record['model_inputs'] = {'count': len(list(model_inputs.glob('*.json'))) if model_inputs.exists() else 0,
                          'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(model_inputs.glob('*.json'))}
                          if model_inputs.exists() else {}}
record['rounds'] = sorted(p.name for p in (D / 'rounds').iterdir()) if (D / 'rounds').exists() else []

(D / 'evidence-hashes.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in record['files'].items()}, ensure_ascii=False, indent=1))
print('evidence count:', record['evidence']['count'], 'model_inputs:', record['model_inputs']['count'],
      'rounds:', record['rounds'])
