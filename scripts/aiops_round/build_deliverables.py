"""Read-only reconstruction of the 037 round's audit artifacts.

The plan's deliverable list names `result-summary.json`, `decision-audit.json` and
`latest-state.json`. No repository script emits them for this round (they were built by
throwaway code in 034), so this rebuilds equivalents strictly from already-persisted
state: the read-API dump, the checkpoint store, the tool trace, and the cost ledger.
Nothing here writes into the round's product databases.
"""
import hashlib
import json
from pathlib import Path

import ormsgpack
import sqlite3
from rounddir import round_dir

D = round_dir()


def latest_thread() -> str:
    con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
    try:
        return con.execute('select thread_id from aiops_runs order by id desc limit 1').fetchone()[0]
    finally:
        con.close()


THREAD = latest_thread()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(blob):
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, (bytes, bytearray)):
        try:
            return ormsgpack.unpackb(bytes(blob))
        except Exception:
            return None
    return blob


run_detail = json.loads((D / 'run-detail.json').read_text(encoding='utf-8'))
tool_trace = json.loads((D / 'product/tool_trace.json').read_text(encoding='utf-8'))
knowledge_trace = json.loads((D / 'product/knowledge_trace.json').read_text(encoding='utf-8'))
cost = json.loads((D / 'product-model/cost.json').read_text(encoding='utf-8'))
manifest = json.loads((D / 'product-model/run-budget.json').read_text(encoding='utf-8'))
INHERITED = manifest['inherited_requests']
INHERITED_RESERVED = manifest['inherited_reserved_cny']
environment = json.loads((D / 'environment.json').read_text(encoding='utf-8'))

# ---------------------------------------------------------------- checkpoints
con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row
step_writes = []
for row in con.execute("select checkpoint_id, value from writes where channel='_step_progress' order by rowid"):
    decoded = decode(row['value'])
    if isinstance(decoded, dict):
        step_writes.append({'checkpoint_id': row['checkpoint_id'], **decoded})
past_rows = list(con.execute("select checkpoint_id, value from writes where channel='past_steps' order by rowid"))
mem_rows = list(con.execute("select checkpoint_id, value from writes where channel='investigation_memory' order by rowid"))
diag_rows = list(con.execute("select checkpoint_id, value from writes where channel='diagnosis' order by rowid"))
ckpt_total = con.execute('select count(*) from checkpoints').fetchone()[0]
write_total = con.execute('select count(*) from writes').fetchone()[0]
con.close()

past_steps = []
seen = set()
for row in past_rows:
    decoded = decode(row['value'])
    if not isinstance(decoded, list):
        continue
    for item in decoded:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        past_steps.append({'checkpoint_id': row['checkpoint_id'], 'step': item})

memories = []
for row in mem_rows:
    decoded = decode(row['value'])
    if isinstance(decoded, dict):
        memories.append({
            'checkpoint_id': row['checkpoint_id'],
            'hypothesis_id': decoded.get('hypothesis_id'),
            'next_check': decoded.get('next_check'),
            'discriminating_question': decoded.get('discriminating_question'),
            'root_cause_present': bool(decoded.get('root_cause')),
            'root_cause_code': decoded.get('root_cause_code'),
            'supporting_evidence_ids': [e.get('evidence_id') for e in decoded.get('supporting_evidence') or []],
        })

diagnosis_channel = None
if diag_rows:
    decoded = decode(diag_rows[-1]['value'])
    if isinstance(decoded, dict):
        diagnosis_channel = {
            'checkpoint_id': diag_rows[-1]['checkpoint_id'],
            'kind': decoded.get('kind'),
            'root_cause_code': decoded.get('root_cause_code'),
            'target_id': decoded.get('target_id'),
            'hypothesis_id': decoded.get('hypothesis_id'),
            'evidence_count': len(decoded.get('evidence') or []),
        }

# ------------------------------------------------------------------- audit
diagnosis = run_detail['diagnosis']
investigation = run_detail.get('investigation') or {}
audit = {
    'thread_id': THREAD,
    'source': 'reconstructed_read_only_from_persisted_state',
    'note': ('本文件由已持久化状态重建（读取 API 结果、checkpoint 存储、工具轨迹、成本账本），'
             '不新增模型请求，不修改轮次数据；等价于 034 由临时脚本生成的决策审计。'),
    'references': {
        'run_detail.json': {'bytes': (D / 'run-detail.json').stat().st_size,
                            'sha256': sha256_file(D / 'run-detail.json')},
        'product/tool_trace.json': {'bytes': (D / 'product/tool_trace.json').stat().st_size,
                                    'sha256': sha256_file(D / 'product/tool_trace.json')},
        'product/checkpoints.sqlite': {'bytes': (D / 'product/checkpoints.sqlite').stat().st_size,
                                       'sha256': sha256_file(D / 'product/checkpoints.sqlite')},
        'product-model/cost.json': {'bytes': (D / 'product-model/cost.json').stat().st_size,
                                    'sha256': sha256_file(D / 'product-model/cost.json')},
    },
    'checkpoint_summary': {
        'checkpoints': ckpt_total,
        'writes': write_total,
        'step_progress': step_writes,
        'past_steps_distinct': len(past_steps),
        'investigation_memory_writes': len(memories),
        'diagnosis_channel': diagnosis_channel,
    },
    'tool_calls': [
        {
            'index': i + 1,
            'tool': item['tool'],
            'arguments': item['arguments'],
            'status': item['status'],
            'validated_live_evidence': item['validated_live_evidence'],
            'started_at': item['started_at'],
            'result_ref': f'{item["tool"]}#{i + 1}',
        }
        for i, item in enumerate(tool_trace)
    ],
    'past_steps': past_steps,
    'investigation_memory_trajectory': memories,
    'final_decision': {
        'kind': diagnosis.get('kind'),
        'root_cause_code': diagnosis.get('root_cause_code'),
        'target_id': diagnosis.get('target_id'),
        'hypothesis_id': diagnosis.get('hypothesis_id'),
        'mechanism_config': diagnosis.get('mechanism_config'),
        'evidence_ids': [e.get('evidence_id') for e in diagnosis.get('evidence') or []],
        'alternatives': [
            {'status': a.get('status'), 'explanation': a.get('explanation'),
             'evidence_ids': [e.get('evidence_id') for e in a.get('evidence') or []]}
            for a in diagnosis.get('alternatives') or []
        ],
        'validation_issues': [str(v) for v in diagnosis.get('validation_issues') or []],
        'unresolved_questions': [
            {'question': u.get('question'), 'limitation': u.get('limitation')}
            if isinstance(u, dict) else {'question': str(u)}
            for u in diagnosis.get('unresolved_questions') or []
        ],
        'contradictions': diagnosis.get('contradictions'),
        'observation_conflicts': diagnosis.get('observation_conflicts'),
        'stop_reason': diagnosis.get('stop_reason'),
    },
    'investigation_counts': {
        'candidates': len(investigation.get('candidates') or []),
        'events': len(investigation.get('events') or []),
        'identity_issues': len(investigation.get('identity_issues') or []),
        'validation_issues': len(investigation.get('validation_issues') or []),
        'leading_id': investigation.get('leading_id'),
        'blocked_reason': investigation.get('blocked_reason'),
    },
    'knowledge_trace': {
        'mode': knowledge_trace.get('mode'),
        'vector_rag_evaluated': knowledge_trace.get('vector_rag_evaluated'),
        'sources': knowledge_trace.get('sources'),
        'queries': [q.get('query') for q in knowledge_trace.get('queries') or []],
    },
    'budget': {
        'inherited_requests': INHERITED,
        'total_requests': len(cost['requests']),
        'new_request_numbers': [r['number'] for r in cost['requests'][INHERITED:]],
        'reserved_cny': cost['reserved_cny'],
        'limit_cny': cost['limit_cny'],
        'blocked_requests': len(cost.get('blocked_requests') or []),
        'models_used': sorted({r.get('model') for r in cost['requests'][INHERITED:]}),
    },
}
(D / 'decision-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')

# ------------------------------------------------------------ latest state
latest = {
    'thread_id': THREAD,
    'captured_from': 'persisted state only (read API dump + sqlite + ledger)',
    'run': {
        'status': run_detail.get('status'),
        'created_at': run_detail.get('created_at'),
        'updated_at': run_detail.get('updated_at'),
        'report_sha256': hashlib.sha256((run_detail.get('report') or '').encode('utf-8')).hexdigest(),
        'report_chars': len(run_detail.get('report') or ''),
    },
    'diagnosis': diagnosis,
    'investigation': investigation,
    'environment': {
        'status': environment.get('status'),
        'scenario': environment.get('scenario'),
        'target_id': environment.get('target_id'),
        'round': environment.get('round'),
        'recovery': environment.get('recovery'),
        'ports_released': environment.get('ports_released'),
        'owned_processes_stopped': environment.get('owned_processes_stopped'),
        'cleanup_errors': environment.get('cleanup_errors'),
        'environment_model_calls': environment.get('environment_model_calls'),
        'ended_at': environment.get('ended_at'),
    },
}
(D / 'latest-state.json').write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding='utf-8')

# --------------------------------------------------------- result summary
manifest = json.loads((D / 'product-model/run-budget.json').read_text(encoding='utf-8'))
inherited_rows = manifest['inherited_requests']
inherited_reserved = manifest['inherited_reserved_cny']
new_rows = cost['requests'][inherited_rows:]
environment_block = {
    'status': environment.get('status'),
    'recovery': environment.get('recovery'),
    'owned_processes_stopped': environment.get('owned_processes_stopped'),
    'ports_released': environment.get('ports_released'),
    'cleanup_errors': environment.get('cleanup_errors') or [],
}
summary = {
    'scenario': environment.get('scenario'),
    'thread_id': THREAD,
    'status': run_detail.get('status'),
    'diagnosis_kind': diagnosis.get('kind'),
    'root_cause_code': diagnosis.get('root_cause_code'),
    'model_calls': len(new_rows),
    'request_numbers': [r['number'] for r in new_rows],
    'all_new_requests_returned_usage': all(
        (r.get('usage') or {}).get('total_tokens') is not None for r in new_rows
    ),
    'inherited_requests': inherited_rows,
    'inherited_reserved_cny': inherited_reserved,
    'round_reserved_cny': round(cost['reserved_cny'] - inherited_reserved, 6),
    'cumulative_reserved_cny': cost['reserved_cny'],
    'historical_or_current_unknown_usage': [710],
    'unpriced_request_count': sum(1 for r in cost['requests'] if r.get('pricing_verified') is False),
    'cumulative_actual_cost': 'unknown',
    'environment': environment_block,
    'artifact_sha256': {
        'run-detail.json': sha256_file(D / 'run-detail.json'),
        'product-model/cost.json': sha256_file(D / 'product-model/cost.json'),
        'decision-audit.json': sha256_file(D / 'decision-audit.json'),
        'latest-state.json': sha256_file(D / 'latest-state.json'),
    },
    'note': (f'由已持久化状态重建；model_calls 为账本新增行数（{new_rows[0]["number"]}–'
             f'{new_rows[-1]["number"]}），读取阶段与重建过程均未发起模型请求。'),
}
(D / 'result-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

print(json.dumps({
    'decision-audit.json': (D / 'decision-audit.json').stat().st_size,
    'latest-state.json': (D / 'latest-state.json').stat().st_size,
    'result-summary.json': (D / 'result-summary.json').stat().st_size,
}, ensure_ascii=False))
