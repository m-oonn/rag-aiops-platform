"""Read-only installed Probe checks; no model calls or whitelist changes."""
import asyncio
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executor-batch', action='store_true')
    args = parser.parse_args()
    from scripts.windows_probe import config_path, _set_acl
    from src.probe.windows.config import load_config
    from src.probe.evidence import validate_tool_evidence
    from src.agent.mcp_client import load_tools_for_config
    cfg = load_config(config_path())
    tools, error = await load_tools_for_config({'probe': {
        'transport': 'streamable_http', 'url': 'http://127.0.0.1:18767/mcp',
        'headers': {'Authorization': 'Bearer ' + cfg.token_file.read_text().strip()}}})
    if error:
        raise RuntimeError(
            'installed Probe gateway is unavailable at http://127.0.0.1:18767/mcp: '
            + str(error)
        )
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    if {tool.name for tool in tools} != set(PROBE_TOOL_OPERATIONS) | {'probe_list_evidence'}:
        raise RuntimeError('installed Probe gateway exposed an unexpected tool catalog')
    tool_map = {t.name: t for t in tools}

    def unwrap(value):
        if isinstance(value, str):
            return unwrap(json.loads(value))
        if isinstance(value, list):
            return unwrap(value[0])
        if isinstance(value, dict) and value.get('type') == 'text':
            return unwrap(value['text'])
        return value

    # The Windows service may still be in outbound reconnect backoff after a
    # gateway restart. Running state alone does not mean the target is online.
    # run_probe backs off up to 60 seconds after a gateway outage; cover one
    # complete retry period before reporting the installed service unavailable.
    deadline = time.monotonic() + 90
    status = None
    while time.monotonic() < deadline:
        status = unwrap(await tool_map['probe_list_evidence'].ainvoke({'limit': 1}))
        if (status.get('status') or {}).get('status') == 'online':
            break
        await asyncio.sleep(0.5)
    if (status or {}).get('status', {}).get('status') != 'online':
        raise RuntimeError('installed Probe did not reconnect to the gateway within 90 seconds')
    checks = [('probe_inventory', {}), ('probe_resource_snapshot', {}),
              ('probe_process_snapshot', {'sort_by': 'memory'}),
              ('probe_process_snapshot', {'sort_by': 'cpu'}), ('probe_port_snapshot', {})]
    for name in cfg.services:
        checks += [('probe_service_status', {'service': name}),
                   ('probe_event_log', {'service': name, 'limit': 5})]
    records = []
    durations = {}
    batch_results = None
    batch_elapsed = None
    if args.executor_batch:
        from src.agent.aiops.executor import _run_tool_calls
        from src.settings import settings
        settings.PROBE_TARGET_ID = cfg.target_id
        started = time.monotonic()
        batch_results = await _run_tool_calls([{'id': str(index), 'name': name, 'args': params}
            for index, (name, params) in enumerate(checks)], tool_map)
        batch_elapsed = round(time.monotonic() - started, 3)
        assert len(batch_results) == len(checks)
        assert all(result.artifact['status'] == 'success' for result in batch_results)
    for index, (name, params) in enumerate(checks):
        started = time.monotonic()
        if batch_results is None:
            result = await tool_map[name].ainvoke(params)
            durations[name + ':' + str(params)] = round(time.monotonic() - started, 3)
        else:
            assert batch_results[index].tool_call_id == str(index)
            result = batch_results[index].content
        value = validate_tool_evidence(result, tool_name=name, target_id=cfg.target_id)
        if name == 'probe_process_snapshot':
            payload = value['payload']
            assert payload['cpu_sample_interval_seconds'] in {0.1, None}
            assert payload['cpu_percent_basis'] == '100_per_logical_core'
            assert len(payload['processes']) <= 256
            assert payload['sort_by'] == params['sort_by']
            assert payload['selection'] == 'top_accessible_processes'
            assert payload['inspected_count'] >= payload['matched_count'] >= len(payload['processes'])
            assert bool(value.get('truncated')) == (payload['matched_count'] > 256)
            key = 'memory_bytes' if params['sort_by'] == 'memory' else 'cpu_percent'
            values = [row[key] for row in payload['processes'] if row[key] is not None]
            assert values == sorted(values, reverse=True)
            for row in payload['processes']:
                if row['pid'] == 0:
                    assert row['cpu_role'] == 'idle_time_not_workload'
            assert all(row['cpu_percent'] is not None or row.get('cpu_error')
                       for row in payload['processes'])
        if name == 'probe_event_log':
            collected = datetime.fromisoformat(value['collected_at'].replace('Z', '+00:00'))
            for event in value['payload'].get('events', []):
                stamp = datetime.fromisoformat(event['collected_at'].replace('Z', '+00:00'))
                assert stamp <= collected, 'event timestamp is in the future'
        records.append(value)
    listed = await tool_map['probe_list_evidence'].ainvoke({'limit': 5})
    summary = unwrap(listed)
    assert summary['data_source'] == 'gateway_summary'
    assert summary['status']['status'] == 'online'
    assert 'baseline' not in summary['status']
    history = summary['baseline_history']
    if len(history) < 2:
        # A fresh gateway database has only the baseline sent at connect time;
        # wait one configured interval so this check also proves periodic reports.
        interval = max(30, min(300, load_config(config_path()).baseline_interval_seconds))
        deadline = time.monotonic() + interval + 15
        while len(history) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(1)
            summary = unwrap(await tool_map['probe_list_evidence'].ainvoke({'limit': 5}))
            history = summary.get('baseline_history') or []
    assert summary['history_error'] is None
    assert 2 <= len(history) <= 5, 'need at least two persisted baselines for comparison'
    assert all(row['target_id'] == cfg.target_id and row['historical'] and not row['current']
               for row in history)
    assert all(history[index]['collected_at'] >= history[index + 1]['collected_at']
               for index in range(len(history) - 1))
    assert len(json.dumps(summary)) < 20000
    out = ROOT / 'runtime' / ('probe-final-' + uuid4().hex)
    out.mkdir(parents=True)
    _set_acl(out)
    (out / 'evidence.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    resources = next(v['payload'] for v in records if v['operation'] == 'resources')
    processes = next(v['payload'] for v in records if v['operation'] == 'processes')
    cpu_samples = [row['cpu_percent'] for row in processes['processes'] if row['cpu_percent'] is not None]
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'target_id': cfg.target_id,
        'operations': [v['operation'] for v in records], 'status': summary['status']['status'],
        'list_bytes': len(json.dumps(summary).encode()), 'resources': resources, 'model_calls': 0,
        'baseline_history': history,
        'executor_batch': args.executor_batch, 'batch_elapsed_seconds': batch_elapsed,
        'tool_durations_seconds': durations,
        'process_selection': [{key: value['payload'][key] for key in
            ('sort_by', 'selection', 'inspected_count', 'matched_count', 'skipped_count',
             'memory_unavailable_count', 'cpu_unavailable_count')}
            for value in records if value['operation'] == 'processes'],
        'process_cpu': {'interval_seconds': processes['cpu_sample_interval_seconds'],
                        'sampled_rows': len(cpu_samples), 'unavailable_rows': len(processes['processes']) - len(cpu_samples),
                        'nonzero_rows': sum(value > 0 for value in cpu_samples)}}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'directory': str(out), 'list_bytes': report['list_bytes'],
                      'operations': report['operations'], 'process_cpu': report['process_cpu'],
                      'process_selection': report['process_selection'],
                      'baseline_rows': len(history), 'model_calls': 0}))

if __name__ == '__main__':
    asyncio.run(main())
