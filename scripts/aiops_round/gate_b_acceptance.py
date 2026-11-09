"""Read-only: map every Gate-B evidence requirement to a real evidence id + raw_hash.

Sources: `product/runs.sqlite` (aiops_evidence), `product/evidence/*.json` (raw payloads),
`report.txt` (citations), and the two API acceptance reads (live / after-restart).
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from rounddir import round_dir, wrong_port

D = round_dir()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def payload_hash(payload):
    return 'sha256:' + hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()


con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
rows = con.execute('select evidence_id, kind, collected_at, raw_ref, raw_hash, summary_redacted '
                   'from aiops_evidence order by evidence_id').fetchall()
con.close()

report = (D / 'report.txt').read_text(encoding='utf-8')
raw = {}
for evidence_id, kind, collected_at, raw_ref, raw_hash, summary in rows:
    payload = json.loads(Path(raw_ref).read_text(encoding='utf-8'))
    raw[evidence_id] = {'kind': kind, 'collected_at': collected_at, 'raw_hash': raw_hash,
                        'payload': payload.get('payload'), 'cited_in_report': evidence_id in report}


def find(pred):
    return [eid for eid, meta in raw.items() if pred(meta)]


def contains(meta, *needles):
    text = json.dumps(meta['payload'], ensure_ascii=False)
    return all(n in text for n in needles)


requirements = {}

# 1. app-loaded downstream port + config hash (configuration snapshot of localapp)
cfg = find(lambda m: m['kind'] == 'configuration'
           and contains(m, 'downstream_port', wrong_port(), 'source_sha256'))
requirements['app_loaded_downstream_port_and_config_hash'] = {
    'evidence': cfg,
    'detail': [{'id': e, 'cited': raw[e]['cited_in_report'], 'raw_hash': raw[e]['raw_hash']} for e in cfg],
}

# 2. same-request application failure log (localapp log row with the business request_id)
req = json.loads((D / 'environment.json').read_text(encoding='utf-8'))
request_id = req['business_request']['request_id']
logs_localapp = find(lambda m: m['kind'] == 'text_logs' and contains(m, request_id, '"service": "localapp"')
                     or (m['kind'] == 'text_logs' and contains(m, request_id, 'localapp')))
requirements['same_request_app_failure_log'] = {
    'request_id': request_id,
    'evidence': logs_localapp,
    'detail': [{'id': e, 'cited': raw[e]['cited_in_report'],
                'has_request_id': request_id in json.dumps(raw[e]['payload'], ensure_ascii=False),
                'raw_hash': raw[e]['raw_hash']} for e in logs_localapp],
}

# 3. wrong port unreachable / not listening
not_listening = find(lambda m: contains(m, wrong_port()) and (m['kind'] in ('ports', 'dependency_probe')))
requirements['wrong_port_unreachable_or_not_listening'] = {
    'evidence': not_listening,
    'detail': [{'id': e, 'kind': raw[e]['kind'], 'cited': raw[e]['cited_in_report'],
                'raw_hash': raw[e]['raw_hash'],
                'payload_excerpt': canonical(raw[e]['payload'])[:220]} for e in not_listening],
}

# 4. registered downstream health
downstream_health = find(lambda m: m['kind'] == 'dependency_probe' and contains(m, 'downstream'))
requirements['registered_downstream_health'] = {
    'evidence': downstream_health,
    'detail': [{'id': e, 'cited': raw[e]['cited_in_report'],
                'payload_excerpt': canonical(raw[e]['payload'])[:220]} for e in downstream_health],
}

# 5. edge/localapp chain sharing one request_id
edge_logs = [e for e in raw if raw[e]['kind'] == 'text_logs' and e not in logs_localapp]
chain = sorted({*logs_localapp, *edge_logs})
requirements['edge_localapp_same_request_chain'] = {
    'evidence': chain,
    'detail': [{'id': e, 'cited': raw[e]['cited_in_report'],
                'has_request_id': request_id in json.dumps(raw[e]['payload'], ensure_ascii=False)}
               for e in chain],
}

# Integrity of every requirement: cited + payload hash recomputation.
all_ok = True
for name, block in requirements.items():
    ids = block.get('evidence') or ([block['evidence']] if isinstance(block.get('evidence'), str) else [])
    block['all_cited'] = all(raw[e]['cited_in_report'] for e in ids)
    block['all_hash_ok'] = all(payload_hash(raw[e]['payload']) == raw[e]['raw_hash'] for e in ids)
    block['ok'] = bool(ids) and block['all_cited'] and block['all_hash_ok']
    all_ok = all_ok and block['ok']

live = json.loads((D / 'acceptance-live.json').read_text(encoding='utf-8'))
after = json.loads((D / 'acceptance-after-restart.json').read_text(encoding='utf-8'))
persistence = {
    'live': {k: live.get(k) for k in ('run_status', 'report_sha256', 'diagnosis_kind',
                                      'root_cause_code', 'evidence_total', 'ledger_unchanged',
                                      'evidence_files_unchanged')},
    'after_restart': {k: after.get(k) for k in ('run_status', 'report_sha256', 'diagnosis_kind',
                                                'root_cause_code', 'evidence_total',
                                                'ledger_unchanged', 'evidence_files_unchanged')},
}
persistence['report_sha256_identical'] = live.get('report_sha256') == after.get('report_sha256')
persistence['evidence_total_identical'] = live.get('evidence_total') == after.get('evidence_total')
persistence['ledger_unchanged_both'] = bool(live.get('ledger_unchanged')
                                            and after.get('ledger_unchanged'))

record = {
    'thread_id': req.get('target_id'),
    'request_id': request_id,
    'evidence_rows': len(raw),
    'evidence_cited_in_report': sum(1 for m in raw.values() if m['cited_in_report']),
    'uncited_evidence': sorted(e for e, m in raw.items() if not m['cited_in_report']),
    'requirements': requirements,
    'all_requirements_satisfied': all_ok,
    'persistence': persistence,
}
(D / 'gate-b-acceptance.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in record.items() if k != 'requirements'}, ensure_ascii=False, indent=1))
for name, block in requirements.items():
    print(f'{name}: ok={block["ok"]} cited={block["all_cited"]} hash={block["all_hash_ok"]} '
          f'ids={block["evidence"]}')
