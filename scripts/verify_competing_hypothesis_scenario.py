"""Free same-503 fixture preflight through the existing Probe/MCP path; no model requests."""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.competing_hypothesis_fixture import CompetingFaultFixture
from scripts.verify_windows_local_faults import cleanup_owned, free_port, wait_listener, symptom_text, get_local
from src.probe.evidence import validate_tool_evidence, validate_observation_window, EvidenceValidationError
from src.probe.protocol import utc_now


def assert_answer_isolated(value, canary):
    encoded = json.dumps(value, ensure_ascii=False)
    for marker in (canary, 'hidden_fault', 'localapp_unavailable', 'downstream_unreachable', 'downstream_bind_failed', 'localapp_wrong_endpoint',
                   'localapp loaded an obsolete downstream endpoint at startup',
                   'controller_fixture_check_not_agent_evidence'):
        if marker in encoded:
            raise AssertionError('controller-only answer marker reached Agent input')


async def verify_controller_file_denied(tool, path, canary):
    try:
        value = await tool.ainvoke({'service': 'localapp', 'path': str(path), 'lines': 10})
    except Exception as exc:
        if 'ProbeConfigError' not in str(exc):
            raise
    else:
        encoded = json.dumps(value)
        assert canary not in encoded and 'ProbeConfigError' in encoded
    return 'ProbeConfigError'


class _InputCaptured(BaseException):
    pass


async def capture_decision_input(state):
    """Use the actual decision-input builder, stopping before structured/model invocation."""
    from src.agent.aiops.strategies import investigation as inv
    captured = {}

    async def intercept(llm, schema, prompt, inputs):
        captured.update(inputs=inputs, messages=[{'role': item.type, 'content': item.content}
            for item in prompt.format_messages(**inputs)], schema=schema.model_json_schema())
        raise _InputCaptured()

    with patch.object(inv, 'create_agent_llm', return_value=object()), \
            patch.object(inv, 'ainvoke_structured', side_effect=intercept):
        try:
            await inv.InvestigationStrategy().decide(state)
        except _InputCaptured:
            pass
    assert captured, 'actual decision input was not captured'
    return captured


async def verify_endpoint_round(fixture, tools, output, target, canary, symptom, report, observations):
    """Deterministic environment acceptance; these checks are not autonomous model choices."""
    from src.agent.aiops.executor import _run_tool_calls, _record_probe_evidence
    from src.agent.aiops.strategies import investigation as inv
    from scripts.evaluate_windows_probe import trace_evaluation_tools
    from scripts.evaluate_windows_probe import local_runbook_retrieval
    from scripts.knowledge_conditions import check_knowledge_conditions

    phase = output / 'round-1'
    phase.mkdir()
    boundary = fixture.boundary
    wrapped = {tool.name: tool for tool in trace_evaluation_tools(
        list(tools.values()), target, phase, [], boundary)}
    state = {'input': symptom, 'plan': [], 'past_steps': [], 'raw_evidence': [],
        'evidence_events': [], 'investigation_memory': {},
        'target_resolution': {'status': 'resolved', 'service': 'edge',
            'allowed_services': ['edge', 'localapp', 'downstream'],
            'allowed_dependencies': ['edge', 'localapp', 'downstream', 'localapp_upstream'],
            'dependency_services': {'edge': 'edge', 'localapp': 'localapp',
                'downstream': 'downstream', 'localapp_upstream': 'localapp'}},
        'investigation_tools': [{'name': name, 'description': tool.description, 'args': tool.args}
            for name, tool in tools.items()]}
    row = {'fault': 'localapp_wrong_endpoint', 'status': 'started', 'boundary': boundary}
    report['rounds'].append(row)
    check_knowledge_conditions(output / 'knowledge-manifest.json', output / 'runbooks', output, None, 'before')
    with local_runbook_retrieval(output / 'runbooks', output) as retrieve:
        context = retrieve(symptom)
    assert context and '启动' in context
    state['raw_evidence'].append(('local_runbooks', json.dumps({'data_source': 'knowledge_base',
        'results': [{'source': 'topology.md', 'chunk_id': 'topology-1', 'content': context}]}, ensure_ascii=False)))
    initial = await capture_decision_input(state)
    assert_answer_isolated(initial, canary)
    assert '启动' in initial['inputs']['knowledge']
    (phase / 'initial-decision-input.json').write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding='utf-8')
    evidence_ids = {}

    async def collect(label, name, args, *, add_to_state=True):
        contract = {'next_check': '环境验收：' + label, 'next_tools': [name],
            'next_arguments': {name: args}, 'discriminating_question': '核对该对象实际现场状态',
            'expected_observation': '返回对象绑定的当前证据；缺失或失败时不得判通过'}
        assert not inv.followup_check_error(contract, state), (label, inv.followup_check_error(contract, state))
        messages = await _run_tool_calls([{'id': uuid.uuid4().hex, 'name': name, 'args': args}], wrapped)
        assert messages[0].artifact['status'] == 'success', (label, messages[0].content)
        raw = validate_tool_evidence(messages[0].content, tool_name=name, target_id=target)
        validate_observation_window(raw, boundary)
        assert not raw.get('truncated') and not raw['payload'].get('error'), (label, raw)
        assert_answer_isolated(raw, canary)
        events = _record_probe_evidence({'thread_id': 'endpoint-environment-acceptance', 'user_id': 1},
            messages[0].content, raw['operation'])
        assert len(events) == 1
        ident = events[0]['evidence_id']
        evidence_ids[label] = ident
        observations.append({'round': 1, 'label': label, 'tool': name, 'arguments': args,
            'evidence_id': ident, 'raw': raw})
        if add_to_state:
            state['raw_evidence'].append((name, messages[0].content))
            state['evidence_events'].extend(events)
        return raw['payload']

    async def captured_stage(label, expected):
        captured = await capture_decision_input(state)
        assert_answer_isolated(captured, canary)
        text = json.dumps(captured['inputs'], ensure_ascii=False)
        for value in expected:
            assert str(value) in text, (label, value)
        (phase / (label + '-decision-input.json')).write_text(
            json.dumps(captured, ensure_ascii=False, indent=2), encoding='utf-8')

    inventory = await collect('inventory', 'probe_inventory', {})
    assert inventory['configured_services']['localapp']['configuration_available']
    edge = await collect('edge', 'probe_dependency_probe', {'dependency': 'edge'})
    downstream = await collect('downstream', 'probe_dependency_probe', {'dependency': 'downstream'})
    assert edge['http']['status'] == 503 and edge['http']['body_prefix'] == 'temporarily unavailable'
    assert downstream['http']['status'] == 200 and json.loads(downstream['http']['body_prefix'])['available']
    for service, port in (('localapp', fixture.localapp_port), ('downstream', fixture.downstream_port)):
        process = await collect(service + '_process', 'probe_process_snapshot', {'service': service})
        ports = await collect(service + '_port', 'probe_port_snapshot', {'local_port': port, 'listening_only': True})
        assert process['matched_count'] >= 1 and process['skipped_count'] == 0 and ports['ports']
        pids = {item['pid'] for item in process['processes']}
        assert all(item['pid'] in pids for item in ports['ports'])
        assert get_local(port, path='/live') == (200, 'alive')
    config = await collect('loaded_config_snapshot', 'probe_config_snapshot', {'service': 'localapp'})
    assert config['values']['downstream_port'] == fixture.obsolete_port
    log = await collect('localapp_log', 'probe_text_log', {'service': 'localapp',
        'path': (fixture.output / 'localapp.log').as_posix(), 'lines': 100})
    events = [json.loads(line) for line in log['lines']]
    startup, = [item for item in events if item.get('event') == 'service_started']
    failed = [item for item in events if item.get('detail') == 'upstream connection failed']
    assert failed and startup['configuration']['source_sha256'] == config['source_sha256']
    assert all(item['upstream']['port'] == fixture.obsolete_port
        and item['configuration']['source_sha256'] == config['source_sha256']
        and item['pid'] in fixture.process_pids['localapp'] and item.get('error_type') for item in failed)
    await captured_stage('cause', [evidence_ids['localapp_log'], evidence_ids['loaded_config_snapshot'],
        'upstream connection failed', config['source_sha256'], fixture.obsolete_port])
    obsolete = await collect('configured_upstream', 'probe_dependency_probe', {'dependency': 'localapp_upstream'})
    assert obsolete['tcp'] == 'failed'
    no_listener = await collect('obsolete_port', 'probe_port_snapshot',
        {'local_port': fixture.obsolete_port, 'listening_only': True})
    assert no_listener['ports'] == []
    edge_log = await collect('edge_log', 'probe_text_log', {'service': 'edge',
        'path': (fixture.output / 'edge.log').as_posix(), 'lines': 100})
    edge_events = [json.loads(line) for line in edge_log['lines']]
    edge_requests = {item.get('request_id') for item in edge_events if item.get('path') == '/api/availability'}
    assert any(item['request_id'] in edge_requests and item['path'] == '/api/availability' for item in failed)
    await captured_stage('symptom', [evidence_ids['edge_log'], evidence_ids['configured_upstream']])
    # Boundary rejection uses an actual observation preceding a new window.
    old = observations[0]['raw']
    try:
        validate_observation_window(old, utc_now())
    except EvidenceValidationError:
        row['prior_window_rejected'] = True
    else:
        raise AssertionError('prior-window evidence accepted')
    row['controller_file_denial'] = await verify_controller_file_denied(
        tools['probe_text_log'], output / 'controller-only.json', canary)
    fault_files = {name: (fixture.output / (name + '.log')).read_bytes()
        for name in ('edge', 'localapp', 'downstream')}
    for name, content in fault_files.items():
        (phase / (name + '-fault.log')).write_bytes(content)
    (phase / 'fault-configuration.json').write_bytes(fixture.connection_config.read_bytes())
    original = fixture.processes['localapp']
    downstream_process = fixture.processes['downstream']
    fixture.repair_endpoint(restart=False)
    edited = await collect('disk_config_after_edit', 'probe_config_snapshot', {'service': 'localapp'}, add_to_state=False)
    assert edited['values']['downstream_port'] == fixture.downstream_port
    still_failed = await collect('before_restart', 'probe_dependency_probe', {'dependency': 'edge'}, add_to_state=False)
    assert still_failed['http']['status'] == 503 and fixture.processes['localapp'] is original
    stale = await collect('before_restart_log', 'probe_text_log', {'service': 'localapp',
        'path': (fixture.output / 'localapp.log').as_posix(), 'lines': 100}, add_to_state=False)
    stale_events = [json.loads(line) for line in stale['lines']]
    assert stale_events[-1]['configuration']['source_sha256'] == config['source_sha256'] != edited['source_sha256']
    fixture.repair_endpoint(restart=True)
    assert original.poll() == 0 and fixture.processes['downstream'] is downstream_process
    restored = {}
    for name in ('downstream', 'localapp', 'edge'):
        restored[name] = await collect('restored_' + name, 'probe_dependency_probe', {'dependency': name}, add_to_state=False)
        assert restored[name]['http']['status'] == 200
        assert json.loads(restored[name]['http']['body_prefix']) == {'sku': 'demo-item', 'available': True}
    final_log = await collect('restored_localapp_log', 'probe_text_log', {'service': 'localapp',
        'path': (fixture.output / 'localapp.log').as_posix(), 'lines': 100}, add_to_state=False)
    final_events = [json.loads(line) for line in final_log['lines']]
    starts = [item for item in final_events if item.get('event') == 'service_started']
    assert len(starts) == 2 and starts[-1]['upstream']['port'] == fixture.downstream_port
    assert starts[-1]['configuration']['source_sha256'] == edited['source_sha256']
    assert starts[0]['instance_id'] != starts[1]['instance_id']
    assert any(item.get('event') == 'service_exited' for item in final_events)
    assert all((fixture.output / (name + '.log')).read_bytes().startswith(content) for name, content in fault_files.items())
    row.update(status='passed', process_identity_verified=True, current_log_window_verified=True,
        decision_input_verified=True, answer_markers_absent=True, disk_only_repair_still_failed=True,
        restart_repair_business_restored=True, historical_fault_logs_preserved=True, evidence_ids=evidence_ids,
        controller_file_denied=True, original_pid=original.pid, new_pid=fixture.processes['localapp'].pid,
        fault_config_sha256=config['source_sha256'], repaired_config_sha256=edited['source_sha256'])
    check_knowledge_conditions(output / 'knowledge-manifest.json', output / 'runbooks', output, None, 'after')
    row['knowledge_before_after_verified'] = True


def paid_endpoint_evaluation_command(*, config, symptom, runbooks, manifest, output,
                                     previous_cost, timeout_authorization, boundary, cumulative_limit):
    """Build the existing model evaluator invocation for the live wrong-endpoint fixture."""
    command = [sys.executable, str(ROOT / 'scripts/evaluate_windows_probe.py'),
        '--run-model', '--probe-config', str(config), '--symptom-file', str(symptom),
        '--local-runbooks', str(runbooks), '--knowledge-manifest', str(manifest),
        '--output-dir', str(output), '--previous-cost', str(previous_cost),
        '--budget-limit-cny', str(cumulative_limit), '--run-budget-cny', '5',
        '--max-output-tokens', '4096', '--isolate-history',
        '--observation-not-before', boundary, '--mechanism-group', 'G11']
    if timeout_authorization:
        command += ['--resume-timeout-authorization', str(timeout_authorization)]
    return command


async def run_paid_endpoint_evaluation(*, launch, output, config, symptom, runbooks,
                                       manifest, previous_cost, timeout_authorization, boundary):
    from scripts.evaluate_windows_probe import read_cost_ledger

    previous = read_cost_ledger(previous_cost, for_resume=False)
    model_output = (output / 'model').resolve()
    if model_output.exists():
        raise FileExistsError('model output directory must be new')
    command = paid_endpoint_evaluation_command(config=config, symptom=symptom,
        runbooks=runbooks, manifest=manifest, output=model_output,
        previous_cost=previous_cost, timeout_authorization=timeout_authorization,
        boundary=boundary, cumulative_limit=previous['limit_cny'])
    process = launch(command[1:], 'model-endpoint')
    code = await asyncio.to_thread(process.wait)
    summary_path = model_output / 'summary.json'
    cost_path = model_output / 'cost.json'
    summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else None
    cost = json.loads(cost_path.read_text(encoding='utf-8')) if cost_path.exists() else None
    prior_count = len(previous['requests'])
    return {'status': 'completed' if code == 0 else 'failed', 'exit_code': code,
        'output_dir': str(model_output), 'summary': summary,
        'new_request_count': max(0, len(cost.get('requests', [])) - prior_count) if cost else None,
        'reserved_cny': cost.get('reserved_cny') if cost else None,
        'cost_file': str(cost_path) if cost_path.exists() else None}


async def verify(output, *, stop_mode='terminate', fault_pair='layers', run_model=False,
                 previous_cost=None, timeout_authorization=None):
    if fault_pair not in {'layers', 'causes', 'endpoint'} or (fault_pair in {'causes', 'endpoint'} and stop_mode != 'request'):
        raise ValueError('cause comparison requires request stop mode')
    if run_model and (fault_pair != 'endpoint' or not previous_cost):
        raise ValueError('paid evaluation requires the endpoint fault and an explicit previous cost ledger')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    target, token, canary = 'competing-fault-test', uuid.uuid4().hex + uuid.uuid4().hex, uuid.uuid4().hex
    from scripts.windows_probe import _set_acl
    if os.name == 'nt':
        _set_acl(output)
    os.environ.update(DATABASE_URL='sqlite:///' + (output / 'runs.sqlite').as_posix(),
        PROBE_EVIDENCE_DIR=str(output / 'evidence'), PROBE_TARGET_ID=target)
    # Import consumers after selecting the disposable database.
    from src.settings import settings
    from src.agent.aiops.executor import _run_tool_calls, _record_probe_evidence
    from src.agent.aiops.strategies import investigation as inv
    from scripts.evaluate_windows_probe import trace_evaluation_tools
    from langchain_mcp_adapters.client import MultiServerMCPClient
    settings.PROBE_TARGET_ID = target
    assert settings.DATABASE_URL == os.environ['DATABASE_URL']
    fixture = CompetingFaultFixture('localapp_wrong_endpoint' if fault_pair == 'endpoint' else 'normal',
        output / 'business', stop_mode=stop_mode)
    gateway_port = free_port()
    while gateway_port in (fixture.edge_port, fixture.localapp_port, fixture.downstream_port, fixture.obsolete_port):
        gateway_port = free_port()
    config = output / 'config.toml'
    (output / 'token').write_text(token, encoding='utf-8')
    (output / 'controller-only.json').write_text(json.dumps({'answer_canary': canary}), encoding='utf-8')
    if fault_pair == 'endpoint':
        (output / 'controller-only.json').write_text(json.dumps({'answer_canary': canary,
            'hidden_fault': 'localapp_wrong_endpoint',
            'root_cause': 'localapp loaded an obsolete downstream endpoint at startup',
            'actual_loaded_port': fixture.obsolete_port, 'registered_downstream_port': fixture.downstream_port,
            'unknown': ['who changed the configuration', 'why the obsolete value was deployed']},
            ensure_ascii=False, indent=2), encoding='utf-8')
    lines = [f"target_id = '{target}'", f"gateway_url = 'ws://127.0.0.1:{gateway_port}/probe/ws'",
        f"token_file = '{(output / 'token').as_posix()}'", 'baseline_interval_seconds = 60']
    for name in ('edge', 'localapp', 'downstream'):
        lines += [f'[services.{name}]', "kind = 'process'", "process_names = ['python.exe']",
            f'process_args = {json.dumps(list(fixture.process_identity(name)))}',
            f"text_logs = ['{(fixture.output / (name + '.log')).as_posix()}']"]
        if fault_pair == 'endpoint' and name == 'localapp':
            lines += [f"config_file = '{fixture.connection_config.as_posix()}'",
                "config_keys = ['downstream_port', 'upstream_timeout_seconds']"]
    for name, port in (('edge', fixture.edge_port), ('localapp', fixture.localapp_port),
                       ('downstream', fixture.downstream_port)):
        lines += [f'[dependencies.{name}]', "host = '127.0.0.1'", f'port = {port}', "health_scheme = 'http'"]
        if fault_pair == 'endpoint':
            lines += ["health_path = '/api/availability'"]
    if fault_pair == 'endpoint':
        lines += ['[dependencies.localapp_upstream]', "host = '127.0.0.1'", f'port = {fixture.obsolete_port}',
            "health_scheme = 'http'", "health_path = '/api/availability'"]
    config.write_text('\n'.join(lines), encoding='utf-8')
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    symptom = symptom_text('candidate-opportunity').replace('localapp', 'edge')
    if fault_pair == 'endpoint':
        symptom = 'edge 的 /api/availability 业务请求失败，请只读调查原因；引用证据，说明处理和复测方法及仍未知之处。'
        (output / 'runbooks').mkdir()
        (output / 'runbooks' / 'topology.md').write_text(
            '业务链路为 edge → localapp → downstream。/live 仅检查本进程存活；/api/availability 是业务接口。'
            '依赖登记中的 downstream 是当前服务地址；localapp_upstream 是应用配置的连接目标。'
            'localapp 连接配置在启动时加载，磁盘修改需要经人工审核后重启应用才生效。'
            '用日志中的进程实例、配置哈希和请求编号核对实际加载及请求。不要仅凭 HTTP 状态码归因。', encoding='utf-8')
        from scripts.knowledge_conditions import knowledge_conditions
        (output / 'knowledge-manifest.json').write_text(json.dumps(
            knowledge_conditions(output / 'runbooks', mode='local_runbooks'),
            ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'symptom.txt').write_text(symptom, encoding='utf-8')
    env = {**os.environ, 'PROBE_TOKEN': token, 'RAG_AIOPS_PROBE_CONFIG': str(config)}
    owned, observations = [], []
    report = {'status': 'started', 'started_at': utc_now(), 'model_calls': 0,
        'stop_mode': stop_mode, 'fault_pair': fault_pair,
        'autonomous_model_investigation': False, 'mechanism_effectiveness_verified': False,
        'config_sha256': config_hash, 'symptom_sha256': hashlib.sha256(symptom.encode()).hexdigest(),
        'rounds': [], 'recovery': 'pending', 'decision_input_capture': 'before model invocation'}
    report['controller_answer_sha256_before'] = hashlib.sha256((output / 'controller-only.json').read_bytes()).hexdigest()
    report['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'scripts/competing_hypothesis_fixture.py', 'scripts/verify_competing_hypothesis_scenario.py',
        'scripts/verify_windows_local_faults.py', 'src/agent/aiops/strategies/investigation.py',
        'src/agent/aiops/executor.py', 'mcp_servers/probe_gateway.py', 'src/probe/windows/collector.py')}

    def save():
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    with ExitStack() as stack:
        def launch(args, name):
            handle = stack.enter_context((output / (name + '.stderr')).open('wb'))
            process = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env,
                stdout=handle, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            owned.append(process)
            return process
        try:
            with fixture:
                gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host',
                    '127.0.0.1', '--port', str(gateway_port)], 'gateway')
                wait_listener(gateway_port, gateway)
                launch(['-c', 'import asyncio; from pathlib import Path; from scripts.windows_probe import run_probe; '
                    f'asyncio.run(run_probe(lambda: Path({str(output / "stop-probe")!r}).exists()))'], 'probe')
                client = MultiServerMCPClient({'probe': {'transport': 'streamable_http',
                    'url': f'http://127.0.0.1:{gateway_port}/mcp', 'headers': {'Authorization': 'Bearer ' + token}}})
                tools = {tool.name: tool for tool in await client.get_tools()}
                for attempt in range(30):
                    try:
                        validate_tool_evidence(await tools['probe_inventory'].ainvoke({}),
                            tool_name='probe_inventory', target_id=target)
                        break
                    except ValueError:
                        if attempt == 29:
                            raise
                        await asyncio.sleep(0.25)
                try:
                    if run_model:
                        model_result = await run_paid_endpoint_evaluation(
                            launch=launch, output=output, config=config, symptom=output / 'symptom.txt',
                            runbooks=output / 'runbooks', manifest=output / 'knowledge-manifest.json',
                            previous_cost=previous_cost, timeout_authorization=timeout_authorization,
                            boundary=fixture.boundary)
                        report['model_evaluation'] = model_result
                        save()
                    if fault_pair == 'endpoint':
                        await verify_endpoint_round(fixture, tools, output, target, canary, symptom, report, observations)
                    faults = (('downstream_unreachable', 'downstream_bind_failed') if fault_pair == 'causes'
                              else (() if fault_pair == 'endpoint' else ('localapp_unavailable', 'downstream_unreachable')))
                    for index, fault in enumerate(faults):
                        phase = output / f'round-{index + 1}'
                        phase.mkdir()
                        old = validate_tool_evidence(await tools['probe_dependency_probe'].ainvoke({'dependency': 'edge'}),
                            tool_name='probe_dependency_probe', target_id=target)
                        boundary = fixture.reset(fault)
                        try:
                            validate_observation_window(old, boundary)
                        except EvidenceValidationError:
                            pass
                        else:
                            raise AssertionError('prior-round evidence was accepted')
                        controller = fixture.observe_controller_side()
                        row = {'fault': fault, 'status': 'started', 'controller': controller,
                            'boundary': boundary, 'old_evidence_rejected': True}
                        report['rounds'].append(row)
                        save()
                        trace = []
                        wrapped = {tool.name: tool for tool in trace_evaluation_tools(
                            list(tools.values()), target, phase, trace, boundary)}
                        state = {'input': symptom, 'plan': [], 'past_steps': [], 'raw_evidence': [],
                            'evidence_events': [], 'investigation_memory': {},
                            'target_resolution': {'status': 'resolved', 'service': 'edge',
                                'allowed_services': ['edge', 'localapp', 'downstream'],
                                'allowed_dependencies': ['edge', 'localapp', 'downstream'],
                                'dependency_services': {'edge': 'edge', 'localapp': 'localapp', 'downstream': 'downstream'}},
                            'investigation_tools': [{'name': name, 'description': tool.description, 'args': tool.args}
                                for name, tool in tools.items()]}
                        assert_answer_isolated(state, canary)
                        initial = await capture_decision_input(state)
                        assert_answer_isolated(initial, canary)
                        (phase / 'initial-decision-input.json').write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding='utf-8')
                        checks = [('inventory', 'probe_inventory', {}),
                            ('edge', 'probe_dependency_probe', {'dependency': 'edge'}),
                            ('downstream', 'probe_dependency_probe', {'dependency': 'downstream'}),
                            ('localapp_process', 'probe_process_snapshot', {'service': 'localapp'}),
                            ('downstream_process', 'probe_process_snapshot', {'service': 'downstream'}),
                            ('localapp_port', 'probe_port_snapshot', {'local_port': fixture.localapp_port, 'listening_only': True}),
                            ('downstream_port', 'probe_port_snapshot', {'local_port': fixture.downstream_port, 'listening_only': True})]
                        if stop_mode == 'terminate' or fault != 'localapp_unavailable':
                            checks.append(('localapp_log', 'probe_text_log', {'service': 'localapp',
                                'path': (fixture.output / 'localapp.log').as_posix(), 'lines': 100}))
                        results = {}
                        for label, name, args in checks:
                            messages = await _run_tool_calls([{'id': uuid.uuid4().hex, 'name': name, 'args': args}], wrapped)
                            assert messages[0].artifact['status'] == 'success'
                            content = messages[0].content
                            raw = validate_tool_evidence(content, tool_name=name, target_id=target)
                            assert_answer_isolated(raw, canary)
                            events = _record_probe_evidence({'thread_id': f'free-round-{index + 1}', 'user_id': 1}, content, raw['operation'])
                            assert len(events) == 1
                            observations.append({'round': index + 1, 'tool': name, 'arguments': args,
                                'evidence_id': events[0]['evidence_id'], 'raw': raw})
                            state['raw_evidence'].append((name, content))
                            state['evidence_events'].extend(events)
                            results[label] = raw
                        for name in ('localapp', 'downstream'):
                            raw = results[name + '_process']
                            payload = raw['payload']
                            assert not raw.get('truncated') and not payload.get('error') and payload['skipped_count'] == 0
                            present = bool(payload['processes'])
                            expected = (name == 'downstream') if fault == 'localapp_unavailable' else (name == 'localapp')
                            assert present is expected
                            listeners = results[name + '_port']['payload']
                            assert not listeners.get('error') and bool(listeners['ports']) is expected
                            if present:
                                pids = {p['pid'] for p in payload['processes']}
                                assert all(p['pid'] in pids for p in listeners['ports'])
                        assert results['edge']['payload']['http']['status'] == 503
                        assert results['edge']['payload']['http']['body_prefix'] == 'temporarily unavailable'
                        assert results['downstream']['payload']['tcp'] == ('ok' if fault == 'localapp_unavailable' else 'failed')
                        if fault != 'localapp_unavailable':
                            assert results['localapp_log']['payload']['lines']
                        row['current_log_window_verified'] = True
                        if stop_mode == 'request':
                            service = 'localapp' if fault == 'localapp_unavailable' else 'downstream'
                            arguments = {'service': service,
                                'path': (fixture.output / (service + '.log')).as_posix(), 'lines': 100}
                            proposal = inv.InvestigationDecision(hypothesis='进程未观察到，停止或启动失败原因待查',
                                next_check='读取该进程允许日志，检查停止或启动失败记录',
                                next_tools=['probe_text_log'], next_arguments={'probe_text_log': arguments},
                                discriminating_question='日志是否记录停止请求或绑定失败，还是没有相关记录？',
                                expected_observation='日志原文中的事件、错误、时间和PID；无记录时原因保持未知')
                            planned = inv.decide_from_evidence(state, proposal, inv.evidence_index(state))
                            assert planned['plan'] and planned['investigation_memory']['next_arguments'] == {'probe_text_log': arguments}
                            state.update(planned)
                            messages = await _run_tool_calls([{'id': uuid.uuid4().hex,
                                'name': 'probe_text_log', 'args': arguments}], wrapped)
                            assert messages[0].artifact['status'] == 'success'
                            raw = validate_tool_evidence(messages[0].content, tool_name='probe_text_log', target_id=target)
                            validate_observation_window(raw, boundary)
                            assert_answer_isolated(raw, canary)
                            events = [json.loads(line) for line in raw['payload']['lines']]
                            event_name = 'bind_failed' if fault == 'downstream_bind_failed' else 'shutdown_requested'
                            event, = [event for event in events if event.get('error', event.get('event')) == event_name]
                            assert event['pid'] in fixture.process_pids[service]
                            assert event['at'] >= boundary
                            if event_name == 'shutdown_requested':
                                assert event['stop_request']['initiator'] == 'unknown'
                                assert fixture.processes[service].returncode == 0
                            else:
                                assert event['errno'] and event['port'] == fixture.downstream_port
                                assert fixture.processes[service].returncode != 0
                            recorded = _record_probe_evidence({'thread_id': f'free-round-{index + 1}',
                                'user_id': 1}, messages[0].content, raw['operation'])
                            assert len(recorded) == 1
                            ident = recorded[0]['evidence_id']
                            state['raw_evidence'].append((planned['plan'][0], messages[0].content))
                            state['evidence_events'].extend(recorded)
                            state['past_steps'].append((planned['plan'][0], messages[0].content))
                            observations.append({'round': index + 1, 'tool': 'probe_text_log',
                                'arguments': arguments, 'evidence_id': ident, 'raw': raw})
                            captured = await capture_decision_input(state)
                            assert_answer_isolated(captured, canary)
                            assert event_name in captured['inputs']['evidence']
                            assert ident in captured['inputs']['evidence']
                            memory = json.loads(captured['inputs']['memory'])
                            progress = [item for option in memory['decision_agenda']['checks']
                                        for item in option['progress']]
                            assert any(ident in item['evidence_ids'] and item['observation'].get('line_count') == len(events)
                                for item in progress)
                            renamed = proposal.model_copy(deep=True)
                            renamed.next_check = '换个名称再次读取同一退出日志'
                            stopped = inv.decide_from_evidence(state, renamed, inv.evidence_index(state))
                            assert not stopped['plan'] and stopped['diagnosis']['kind'] == 'localized_fault'
                            (phase / 'exit-log-decision-input.json').write_text(
                                json.dumps(captured, ensure_ascii=False, indent=2), encoding='utf-8')
                            (phase / 'fixed-exit-check.json').write_text(json.dumps({
                                'autonomous_model_choice': False, 'proposal': proposal.model_dump(),
                                'plan': planned['plan'], 'selection': planned['investigation_memory']['hypothesis_tracking'].get('policy_selected_check'),
                                'evidence_id': ident, 'repeat_stop_reason': stopped['diagnosis']['stop_reason']},
                                ensure_ascii=False, indent=2), encoding='utf-8')
                            row.update(exit_log_evidence_id=ident, exit_log_pid_matches=True,
                                exit_log_decision_input_verified=True, fixed_check_executed=True,
                                renamed_repeat_rejected=True, initiator='unknown', cause_event=event_name)
                        captured = await capture_decision_input(state)
                        assert_answer_isolated(captured, canary)
                        expected_count = len(checks) + (stop_mode == 'request')
                        assert len(inv.evidence_index(state)) == expected_count
                        assert len(json.loads(captured['inputs']['evidence'])) == min(8, expected_count)
                        paths = json.loads(captured['inputs']['text_log_paths'])
                        assert paths['evidence_id'] in inv.evidence_index(state)
                        assert all((fixture.output / (name + '.log')).as_posix() in paths['services'][name]
                            for name in ('edge', 'localapp', 'downstream'))
                        row['log_paths_retained_in_decision_input'] = True
                        (phase / 'observed-decision-input.json').write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding='utf-8')
                        row['controller_file_denial'] = await verify_controller_file_denied(
                            tools['probe_text_log'], output / 'controller-only.json', canary)
                        row['controller_file_denied'] = True
                        assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash
                        row.update(status='passed', current_evidence_count=len(checks) + (stop_mode == 'request'), process_identity_verified=True,
                            answer_markers_absent=True, config_unchanged=True)
                        save()
                    if fault_pair != 'endpoint':
                        initial_inputs = [json.loads((output / f'round-{i}/initial-decision-input.json').read_text(encoding='utf-8')) for i in (1, 2)]
                        assert initial_inputs[0] == initial_inputs[1]
                        report['initial_decision_inputs_equal'] = True
                    if fault_pair == 'causes':
                        assert [row['cause_event'] for row in report['rounds']] == ['shutdown_requested', 'bind_failed']
                        assert all(row['controller']['edge']['http_status'] == 503
                            and row['controller']['edge']['body'] == 'temporarily unavailable'
                            and row['controller']['downstream']['tcp'] == 'failed' for row in report['rounds'])
                        report['same_symptom_distinct_cause_logs'] = True
                except BaseException as exc:
                    report['preflight_error'] = {'type': type(exc).__name__, 'message': str(exc)[:300]}
                    if report['rounds'] and report['rounds'][-1]['status'] == 'started':
                        report['rounds'][-1]['status'] = 'failed'
                    raise
                finally:
                    try:
                        if fault_pair == 'endpoint':
                            fixture.repair_endpoint(restart=True)
                        else:
                            fixture.reset('normal')
                        recovery = fixture.observe_controller_side()
                        assert all(recovery[name]['http_status'] == 200 for name in ('edge', 'localapp', 'downstream'))
                        report['recovery_probe'] = []
                        for name in ('edge', 'localapp', 'downstream'):
                            raw = validate_tool_evidence(await tools['probe_dependency_probe'].ainvoke({'dependency': name}),
                                tool_name='probe_dependency_probe', target_id=target)
                            assert raw['payload']['http']['status'] == 200
                            report['recovery_probe'].append(raw)
                        report.update(recovery='normal_restored', recovery_controller=recovery)
                    except BaseException:
                        report['recovery'] = 'failed'
                        raise
            report['status'] = 'passed'
        except BaseException as exc:
            report.update(status='failed', error_type=type(exc).__name__, error=str(exc)[:300])
            raise
        finally:
            cleanup = cleanup_owned(owned + fixture.owned,
                [gateway_port, fixture.edge_port, fixture.localapp_port, fixture.downstream_port, fixture.obsolete_port])
            report.update(cleanup, ended_at=utc_now(), observation_count=len(observations))
            report['controller_answer_sha256_after'] = hashlib.sha256((output / 'controller-only.json').read_bytes()).hexdigest()
            if report['controller_answer_sha256_after'] != report['controller_answer_sha256_before']:
                report['status'] = 'failed'
            if cleanup['cleanup_errors'] or not cleanup['owned_processes_stopped'] or not cleanup['ports_released']:
                report['status'] = 'failed'
            (output / 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
            save()
    assert report['status'] == 'passed'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop-mode', choices=('terminate', 'request'), default='terminate')
    parser.add_argument('--fault-pair', choices=('layers', 'causes', 'endpoint'), default='layers')
    parser.add_argument('--run-model', action='store_true',
        help='Run one budgeted model evaluation in the live endpoint fault; requires separate authorization')
    parser.add_argument('--previous-cost', type=Path,
        help='Latest cumulative model cost ledger; required with --run-model')
    parser.add_argument('--timeout-authorization', type=Path,
        help='Single-run authorization for an inherited historical unknown-usage request')
    args = parser.parse_args()
    if args.timeout_authorization and not args.run_model:
        parser.error('--timeout-authorization requires --run-model')
    result = asyncio.run(verify(args.output, stop_mode=args.stop_mode, fault_pair=args.fault_pair,
        run_model=args.run_model, previous_cost=args.previous_cost,
        timeout_authorization=args.timeout_authorization))
    print(json.dumps({key: result.get(key) for key in (
        'status', 'model_calls', 'model_evaluation', 'observation_count', 'recovery', 'ports_released')}))
