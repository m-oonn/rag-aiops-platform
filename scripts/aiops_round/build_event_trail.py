"""Read-only: reconstruct the diagnosis event trail for a round.

The whole round ran once through the official page; the browser step captured the
streaming POST (status 200) and a DOM snapshot but did **not** persist the raw SSE
frames. The authoritative record of what the stream carried is what LangGraph wrote
while streaming, so this rebuilds a chronological trail from:

  * `product/checkpoints.sqlite` — per-checkpoint timestamp + channel changes
  * `product/tool_trace.json`   — the tool executions
  * `product-model/cost.json`   — the model requests (redacted inputs on disk)
  * `run-detail.json`           — final diagnosis and response text

`raw_sse_frames_persisted` is reported honestly as false.
"""
import json
import sqlite3
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from rounddir import round_dir

D = round_dir()

serde = JsonPlusSerializer()

con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row
rows = list(con.execute('select checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata '
                        'from checkpoints order by rowid'))
con.close()

checkpoints = []
previous_channels = None
for row in rows:
    try:
        payload = serde.loads_typed((row['type'], row['checkpoint']))
    except Exception as exc:  # pragma: no cover
        checkpoints.append({'checkpoint_id': row['checkpoint_id'], 'error': str(exc)})
        continue
    channel_values = payload.get('channel_values') or {}
    channels = sorted(channel_values)
    changed = [] if previous_channels is None else sorted(set(channels) - set(previous_channels))
    entry = {
        'checkpoint_id': row['checkpoint_id'],
        'parent_checkpoint_id': row['parent_checkpoint_id'],
        'ts': payload.get('ts'),
        'channels': len(channels),
        'changed_channels': changed or channels,
        'has_diagnosis': 'diagnosis' in channel_values,
        'has_response': 'response' in channel_values,
        'step_progress': channel_values.get('_step_progress'),
        'plan_len': len(channel_values.get('plan') or []),
        'past_steps_len': len(channel_values.get('past_steps') or []),
        'evidence_events_len': len(channel_values.get('evidence_events') or []),
        'raw_evidence_len': len(channel_values.get('raw_evidence') or []),
    }
    checkpoints.append(entry)
    previous_channels = channels

tool_trace = json.loads((D / 'product/tool_trace.json').read_text(encoding='utf-8'))
cost = json.loads((D / 'product-model/cost.json').read_text(encoding='utf-8'))
run_detail = json.loads((D / 'run-detail.json').read_text(encoding='utf-8'))
manifest = json.loads((D / 'product-model/run-budget.json').read_text(encoding='utf-8'))
new_rows = cost['requests'][manifest['inherited_requests']:]

timeline = []
for c in checkpoints:
    if 'ts' in c:
        timeline.append({'kind': 'checkpoint', 'at': c['ts'], 'checkpoint_id': c['checkpoint_id'],
                         'changed_channels': c['changed_channels'],
                         'step_progress': c['step_progress'],
                         'plan_len': c['plan_len'], 'past_steps_len': c['past_steps_len'],
                         'evidence_events_len': c['evidence_events_len']})
for i, t in enumerate(tool_trace, 1):
    timeline.append({'kind': 'tool_call', 'at': t['started_at'], 'index': i, 'tool': t['tool'],
                     'arguments': t['arguments'], 'status': t['status'],
                     'validated_live_evidence': t['validated_live_evidence'],
                     'elapsed_ms': t['elapsed_ms']})
for r in new_rows:
    timeline.append({'kind': 'model_request', 'at': r['started_at'], 'number': r['number'],
                     'model': r.get('served_model') or r.get('model'),
                     'input_tokens': (r.get('usage') or {}).get('prompt_tokens'),
                     'output_tokens': (r.get('usage') or {}).get('completion_tokens'),
                     'reserved_cny': r['reserved_cny']})
timeline.sort(key=lambda item: item['at'] or '')

trail = {
    'thread_id': run_detail.get('thread_id'),
    'source': 'reconstructed_read_only_from_persisted_state',
    'raw_sse_frames_persisted': False,
    'sse_stream_confirmed_by': {
        'frontend_post_count': 1,
        'frontend_post_status': 200,
        'note': ('前端脚本记录了唯一一次 POST /api/v1/aiops 且返回 200（SSE 已建立）；'
                 '原始 SSE 帧未落盘，事件轨迹由 checkpoint 写入、工具轨迹和账本重建。'
                 '中间件对再次 POST 返回 403，因此本轮只可能有一次流。'),
    },
    'counts': {
        'checkpoints': len([c for c in checkpoints if 'ts' in c]),
        'tool_calls': len(tool_trace),
        'model_requests': len(new_rows),
        'evidence': len(run_detail['diagnosis'].get('evidence') or []),
    },
    'span': {
        'first': timeline[0]['at'] if timeline else None,
        'last': timeline[-1]['at'] if timeline else None,
    },
    'checkpoints': checkpoints,
    'timeline': timeline,
    'final_state': {
        'status': run_detail.get('status'),
        'diagnosis_kind': run_detail['diagnosis'].get('kind'),
        'root_cause_code': run_detail['diagnosis'].get('root_cause_code'),
        'response_head': (run_detail.get('report') or '')[:200],
    },
}

(D / 'event-trail-reconstructed.json').write_text(
    json.dumps(trail, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'counts': trail['counts'], 'span': trail['span'],
                  'bytes': (D / 'event-trail-reconstructed.json').stat().st_size},
                 ensure_ascii=False))
