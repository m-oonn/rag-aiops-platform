"""Persistent loopback fixture and isolated production AIOps page. Free by default."""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch, PropertyMock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.competing_hypothesis_fixture import CompetingFaultFixture
from scripts.verify_competing_hypothesis_scenario import write_scenario_files, verify_controller_file_denied
from scripts.verify_windows_local_faults import cleanup_owned, free_port, wait_listener, stop
from src.probe.protocol import utc_now


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def archive_round(output, fixture, state):
    archive = output / 'rounds' / str(state['round'])
    archive.mkdir(parents=True, exist_ok=False)
    for path in fixture.output.glob('*'):
        if path.suffix in {'.log', '.json'}:
            (archive / path.name).write_bytes(path.read_bytes())
    for name in ('config.toml', 'controller-only.json'):
        path = output / name
        if path.is_file():
            (archive / name).write_bytes(path.read_bytes())
    save(archive / 'state.json', state)


def check_environment_round(output, expected_round):
    state = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
    if state['status'] != 'ready' or state['round'] != expected_round:
        raise ValueError('test environment stopped or changed round; restart backend before diagnosis')
    return state


async def start(output, duration, scenario):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    from scripts.windows_probe import _set_acl
    if os.name == 'nt':
        _set_acl(output)
    fault = {'endpoint': 'localapp_wrong_endpoint', 'stopped': 'downstream_unreachable', 'normal': 'normal'}[scenario]
    fixture = CompetingFaultFixture(fault, output / 'business', stop_mode='request', startup_configuration=True)
    target, token, canary = 'aiops-test-' + uuid.uuid4().hex[:12], uuid.uuid4().hex + uuid.uuid4().hex, uuid.uuid4().hex
    port = free_port()
    while port in (fixture.edge_port, fixture.localapp_port, fixture.downstream_port, fixture.obsolete_port):
        port = free_port()
    config, _ = write_scenario_files(output, fixture, port, target, token, canary, 'endpoint')
    (output / 'login.json').write_text(json.dumps({'username': 'environment-test', 'password': uuid.uuid4().hex + 'A1'}), encoding='utf-8')
    state = {'status': 'starting', 'target_id': target, 'scenario': scenario, 'started_at': utc_now(),
             'gateway_url': f'http://127.0.0.1:{port}/mcp', 'environment_model_calls': 0,
             'diagnosis_acceptance': 'not_run', 'frontend_acceptance': 'not_run', 'round': 1}
    state_path = output / 'environment.json'
    save(state_path, state)
    (output / 'product').mkdir()
    env = {**os.environ, 'PROBE_TOKEN': token, 'RAG_AIOPS_PROBE_CONFIG': str(config),
           'DATABASE_URL': 'sqlite:///' + (output / 'product/runs.sqlite').as_posix(),
           'PROBE_EVIDENCE_DIR': str(output / 'gateway-evidence'), 'PROBE_TARGET_ID': target}
    owned = []
    with ExitStack() as stack:
        def launch(args, name):
            log = stack.enter_context((output / (name + '.log')).open('wb'))
            process = subprocess.Popen([sys.executable, *args], cwd=ROOT, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            owned.append(process)
            return process
        try:
            with fixture:
                state['boundary'] = fixture.boundary
                state['business_request'] = fixture.trigger_business_request()
                state['business_url'] = f'http://127.0.0.1:{fixture.edge_port}/api/availability'
                gateway = launch(['-m', 'uvicorn', 'mcp_servers.probe_gateway:app', '--host', '127.0.0.1', '--port', str(port)], 'gateway')
                wait_listener(port, gateway)
                probe_args = ['-c', 'import asyncio; from pathlib import Path; from scripts.windows_probe import run_probe; '
                    f'asyncio.run(run_probe(lambda: Path({str(output / "stop-probe")!r}).exists()))']
                probe = launch(probe_args, 'probe')
                from langchain_mcp_adapters.client import MultiServerMCPClient
                from src.probe.evidence import validate_tool_evidence, validate_observation_window
                client = MultiServerMCPClient({'probe': {'transport': 'streamable_http',
                    'url': state['gateway_url'], 'headers': {'Authorization': 'Bearer ' + token}}})
                tools = {tool.name: tool for tool in await client.get_tools()}
                for attempt in range(40):
                    try:
                        inventory = validate_tool_evidence(await tools['probe_inventory'].ainvoke({}),
                            tool_name='probe_inventory', target_id=target)
                        break
                    except ValueError:
                        if attempt == 39:
                            raise
                        await asyncio.sleep(0.25)
                validation = [inventory]
                for name in ('edge', 'localapp'):
                    if name == 'localapp' and fault == 'localapp_unavailable':
                        continue
                    raw = validate_tool_evidence(await tools['probe_text_log'].ainvoke({'service': name,
                        'path': (fixture.output / (name + '.log')).as_posix(), 'lines': 100}),
                        tool_name='probe_text_log', target_id=target)
                    validate_observation_window(raw, state['boundary'])
                    if not any(state['business_request']['request_id'] == json.loads(line).get('request_id')
                               for line in raw['payload']['lines']):
                        raise RuntimeError('business request is not reachable through Probe/MCP')
                    validation.append(raw)
                await verify_controller_file_denied(tools['probe_text_log'], output / 'controller-only.json', canary)
                save(output / 'preflight.json', {'status': 'passed', 'model_calls': 0, 'observations': validation,
                    'controller_answer_denied': True, 'business_request': state['business_request']})
                state.update(status='ready', tool_names=sorted(tools), environment_acceptance='passed')
                save(state_path, state)
                print(json.dumps({'status': 'ready', 'output': str(output), 'business_url': state['business_url'],
                                  'duration_seconds': duration, 'model_calls': 0}), flush=True)
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline and not (output / 'stop').exists():
                    if gateway.poll() is not None or probe.poll() is not None:
                        raise RuntimeError('Probe or gateway exited unexpectedly')
                    for action in ('restore', 'inject', 'request'):
                        marker = output / action
                        if not marker.exists():
                            continue
                        marker.unlink()
                        if action in {'restore', 'inject'}:
                            state['status'] = 'changing'
                            save(state_path, state)
                            archive_round(output, fixture, state)
                            stop(probe)
                            state['boundary'] = fixture.reset('normal' if action == 'restore' else fault)
                            state['round'] += 1
                            write_scenario_files(output, fixture, port, target, token, canary, 'endpoint')
                            probe = launch(probe_args, 'probe-' + str(state['round']))
                        state['business_request'] = fixture.trigger_business_request()
                        for attempt in range(40):
                            try:
                                for service in ('edge', 'localapp'):
                                    current = validate_tool_evidence(await tools['probe_text_log'].ainvoke({
                                        'service': service, 'path': (fixture.output / (service + '.log')).as_posix(), 'lines': 100}),
                                        tool_name='probe_text_log', target_id=target)
                                    validate_observation_window(current, state['boundary'])
                                    if not any(json.loads(line).get('request_id') == state['business_request']['request_id']
                                               for line in current['payload']['lines']):
                                        raise ValueError('current request not yet reachable through Probe')
                                break
                            except ValueError:
                                if attempt == 39:
                                    raise
                                await asyncio.sleep(0.25)
                        state['last_action'] = action
                        state['status'] = 'ready'
                        save(state_path, state)
                    await asyncio.sleep(0.25)
                state['status'] = 'stopping'
                save(state_path, state)
                archive_round(output, fixture, state)
                fixture.reset('normal')
                recovery = fixture.observe_controller_side()
                if any(recovery[name]['http_status'] != 200 for name in ('edge', 'localapp', 'downstream')):
                    raise RuntimeError('business recovery failed')
                state.update(recovery='three_business_endpoints_200', status='stopped')
        except BaseException as exc:
            state.update(status='interrupted' if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)) else 'failed',
                         error_type=type(exc).__name__, recovery='not_verified')
            if fixture.output.exists() and not (output / 'rounds' / str(state['round'])).exists():
                archive_round(output, fixture, state)
            raise
        finally:
            state.update(cleanup_owned(owned + fixture.owned,
                [port, fixture.edge_port, fixture.localapp_port, fixture.downstream_port, fixture.obsolete_port]))
            state['ended_at'] = utc_now()
            if state['cleanup_errors'] or not state['ports_released'] or not state['owned_processes_stopped']:
                state['status'] = 'failed'
            save(state_path, state)


def product_environment(output):
    state = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
    if state['status'] != 'ready':
        raise ValueError('test environment is not ready; start a new environment first')
    product = output / 'product'
    product.mkdir(exist_ok=True)
    for name in ('raw', 'processed', 'vectors'):
        (product / name).mkdir(exist_ok=True)
    return {'DATABASE_URL': 'sqlite:///' + (product / 'runs.sqlite').as_posix(),
        'UPLOAD_DIR': str(product / 'raw'), 'PROCESSED_DIR': str(product / 'processed'),
        'VECTOR_DIR': str(product / 'vectors'), 'API_PREFIX': '/api/v1', 'APP_ENV': 'development',
        'MILVUS_HOST': '127.0.0.1', 'MILVUS_PORT': str(free_port()),
        'MINIO_ENDPOINT': '127.0.0.1:' + str(free_port()),
        'AIOPS_CHECKPOINT_DB_PATH': str(product / 'checkpoints.sqlite'),
        'PROBE_EVIDENCE_DIR': str(product / 'evidence'), 'PROBE_ENABLED': 'true',
        'PROBE_TARGET_ID': state['target_id'], 'MCP_PROBE_URL': state['gateway_url'],
        'PROBE_TOKEN': (output / 'token').read_text(encoding='utf-8'),
        'TERMCP_ENABLED': 'false', 'ENABLE_HITL': 'false', 'ENABLE_LLM_RETRY': 'false',
        'SECRET_KEY': hashlib.sha256((output / 'token').read_bytes()).hexdigest()}


def backend(args):
    output = args.output.resolve()
    os.environ.update(product_environment(output))
    if args.run_model:
        if not args.previous_cost:
            raise ValueError('real diagnosis requires the latest previous-cost ledger')
        from scripts.with_agent_test_env import profile_environment
        os.environ.update(profile_environment(args.profile))
    from src.settings import settings
    from scripts.evaluate_windows_probe import business_catalog, local_runbook_retrieval
    from src.probe.windows.config import load_config
    settings.DIAGNOSTIC_TARGET_CATALOG = business_catalog(load_config(output / 'config.toml'))
    from src.main import app
    from src.database.sql_session import SessionLocal
    from src.database.models import User
    from src.utils.security import get_password_hash
    login = json.loads((output / 'login.json').read_text(encoding='utf-8'))
    with SessionLocal() as db:
        if not db.query(User).filter_by(username=login['username']).first():
            db.add(User(username=login['username'], email='environment-test@example.invalid',
                        password_hash=get_password_hash(login['password']), is_active=True, role='user'))
            db.commit()
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    dist = ROOT / 'frontend/dist'
    if not (dist / 'index.html').is_file():
        raise ValueError('build frontend first: npm --prefix frontend run build')
    used = False
    expected_round = json.loads((output / 'environment.json').read_text(encoding='utf-8'))['round']

    @app.middleware('http')
    async def local_test_routes(request, call_next):
        nonlocal used
        path = request.url.path
        if request.method == 'POST' and path == '/api/v1/aiops':
            if not args.run_model or used:
                return JSONResponse({'detail': '本次环境仅预览，或单场真实诊断已经使用。'}, status_code=403)
            from src.api.dependencies import get_current_user
            from fastapi import HTTPException
            token = request.headers.get('Authorization', '').removeprefix('Bearer ')
            with SessionLocal() as db:
                try:
                    get_current_user(token=token, db=db)
                except HTTPException as exc:
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
            try:
                check_environment_round(output, expected_round)
            except ValueError:
                return JSONResponse({'detail': '测试环境已停止或切换轮次，请重启测试后端。'}, status_code=503)
            used = True
        elif path.startswith('/api/') and not (
            request.method == 'GET' and path.startswith('/api/v1/aiops/') or
            request.method == 'POST' and path == '/api/v1/auth/login/access-token'
        ):
            return JSONResponse({'detail': '该独立环境只开放诊断、读取报告与登录。'}, status_code=403)
        return await call_next(request)

    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='environment-assets')

    @app.get('/{path:path}')
    async def frontend(path: str):
        if path.startswith('api/'):
            return JSONResponse({'detail': 'not found'}, status_code=404)
        return FileResponse(dist / 'index.html')

    with ExitStack() as stack:
        probe = settings.MCP_SERVERS['probe']
        stack.enter_context(patch.object(type(settings), 'MCP_SERVERS', new_callable=PropertyMock,
                                         return_value={'probe': probe}))
        retrieve = stack.enter_context(local_runbook_retrieval(output / 'runbooks', output / 'product'))
        import src.agent.aiops.planner as planner
        stack.enter_context(patch.object(planner, '_retrieve_experience', retrieve))
        asyncio.run(serve_product(app, args, stack))


async def serve_product(app, args, stack):
    import uvicorn
    import src.agent.aiops.tools as tools_module
    from scripts.evaluate_windows_probe import trace_evaluation_tools
    output = args.output.resolve()
    state = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
    original_loader = tools_module.load_mcp_tools_safe
    tools, error = await original_loader()
    if error or not any(tool.name == 'probe_inventory' for tool in tools):
        raise RuntimeError('product backend could not connect to the fixture Probe')
    trace = []
    wrapped = trace_evaluation_tools([tool for tool in tools if tool.name != 'probe_list_evidence'],
        state['target_id'], output / 'product', trace, state['boundary'])

    async def fixture_tools():
        check_environment_round(output, state['round'])
        return wrapped, None

    stack.enter_context(patch.object(tools_module, 'load_mcp_tools_safe', fixture_tools))
    http = install_budget(args, stack) if args.run_model else None
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False))

    async def watch_stop():
        while not server.should_exit:
            if (output / 'stop-backend').exists():
                (output / 'stop-backend').unlink()
                server.should_exit = True
                return
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if http is not None:
            await http.aclose()


def install_budget(args, stack):
    """Use existing reservation, timeout and response-accounting implementations."""
    import httpx
    import importlib
    from copy import deepcopy
    from scripts.evaluate_windows_probe import read_cost_ledger, validate_timeout_authorization, _evaluation_request_api_base
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget
    from scripts.model_request_diagnostics import record_model_response
    from src.agent.aiops_llm import create_agent_llm
    from src.settings import settings
    from src.probe.protocol import redact
    output = args.output.resolve() / 'product-model'
    model_max_output_tokens = int(getattr(args, 'model_max_output_tokens', 4096))
    if model_max_output_tokens < 1024:
        raise ValueError('model max output tokens must be at least 1024')
    resume_cost = output / 'cost.json'
    resuming = resume_cost.exists()
    ledger_path = resume_cost if resuming else args.previous_cost
    # Keep the original baseline across backend restarts, including its unknowns.
    baseline = read_cost_ledger(args.previous_cost, for_resume=False)
    baseline_hash = hashlib.sha256(args.previous_cost.read_bytes()).hexdigest()
    manifest_path = output / 'run-budget.json'
    manifest = {'version': 1, 'previous_sha256': baseline_hash,
                'inherited_requests': len(baseline['requests']),
                'inherited_reserved_cny': baseline['reserved_cny'], 'run_limit_cny': 5}
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
        raise ValueError('run budget baseline changed; cannot reset this round')
    previous = read_cost_ledger(ledger_path, for_resume=False, output=output,
        timeout_authorization=None if resuming else args.timeout_authorization, run_limit_cny=5)
    if resuming and (previous['requests'][:len(baseline['requests'])] != baseline['requests']
            or previous.get('request_limits', {}).get('inherited_requests') != len(baseline['requests'])):
        raise ValueError('resumed ledger does not match the original run baseline')
    cumulative_limit = baseline['reserved_cny'] + 5
    # A backend restart in the same round must reuse the existing ledger and
    # persisted run data so the frontend can restore the completed report.
    output.mkdir(exist_ok=True)
    save(manifest_path, manifest)
    budget = PaidRequestBudget(output, max_output_tokens=model_max_output_tokens, limit_cny=cumulative_limit,
        run_limit_cny=5, api_base=settings.RESOLVED_LLM_API_BASE,
        fallback_api_base=settings.LLM_FALLBACK_API_BASE if settings.LLM_FALLBACK_ENABLED else None,
        fallback_model=settings.LLM_FALLBACK_MODEL if settings.LLM_FALLBACK_ENABLED else None)
    budget.ledger = deepcopy(previous['requests'])
    budget.reserved = previous['reserved_cny']
    budget.inherited_reserved = baseline['reserved_cny']
    budget.inherited_requests = len(baseline['requests'])
    budget.allow_inherited_unknown = True
    budget.blocked_requests = deepcopy(previous.get('blocked_requests', []))
    if args.timeout_authorization:
        if resuming:
            # Revalidate the immutable authorization against the original
            # ledger, then bind the same historical row in the resumed ledger.
            original = read_cost_ledger(args.previous_cost, for_resume=False)
            _, authorized = validate_timeout_authorization(args.timeout_authorization, args.previous_cost,
                                                           original, output, previous['limit_cny'], 5)
            row = next((item for item in previous['requests']
                        if item.get('number') == authorized.get('number')), None)
            if row is None or row.get('status') != authorized.get('status'):
                raise ValueError('timeout authorization row is missing from resumed ledger')
        else:
            _, row = validate_timeout_authorization(args.timeout_authorization, args.previous_cost, previous,
                                                   output, previous['limit_cny'], 5)
        budget.authorized_historical_timeouts = [deepcopy(row)]
        save(output / 'timeout-authorization-use.json', {'path': str(args.timeout_authorization.resolve()),
             'sha256': hashlib.sha256(args.timeout_authorization.read_bytes()).hexdigest()})
    budget.save()

    class Transport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            check_environment_round(args.output.resolve(), expected_round)
            endpoint = _evaluation_request_api_base(request.url, budget.api_base, budget.fallback_api_base)
            if endpoint is None:
                raise ValueError('model endpoint outside the configured evaluation scope')
            body = json.loads(await request.aread())
            row = budget.reserve(body, require_known_usage=True, api_base=endpoint)
            directory = output / 'model-inputs'
            directory.mkdir(exist_ok=True)
            path = directory / (str(row['number']) + '.json')
            save(path, redact(body))
            row.update(input_file=path.relative_to(output).as_posix(), input_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            budget.save()
            revised = httpx.Request(request.method, request.url,
                headers={k: v for k, v in request.headers.items() if k.lower() != 'content-length'},
                content=json.dumps(body).encode(), extensions=request.extensions)
            return await record_model_response(self.inner, revised, row, budget.save)

        async def aclose(self):
            await self.inner.aclose()

    expected_round = json.loads((args.output.resolve() / 'environment.json').read_text(encoding='utf-8'))['round']
    client = httpx.AsyncClient(transport=Transport(), timeout=60)

    def bounded_factory(**kwargs):
        llm = create_agent_llm(**kwargs)
        leaves = [llm.runnable] if hasattr(llm, 'runnable') else [llm]
        for item in leaves + (getattr(llm, 'fallbacks', []) or []):
            item.max_tokens, item.max_retries = model_max_output_tokens, 0
            item.http_async_client = client
            for name in ('root_async_client', 'root_client'):
                root = getattr(item, name, None)
                if root is not None:
                    root.max_retries = 0
            if getattr(item, 'root_async_client', None) is not None:
                item.root_async_client._client = client
        return llm

    for name in ('planner', 'executor', 'strategies.investigation', 'strategies.default', 'reporting'):
        stack.enter_context(patch.object(importlib.import_module('src.agent.aiops.' + name),
                                         'create_agent_llm', bounded_factory))
    stack.enter_context(patch.object(importlib.import_module('src.agent.aiops_llm'),
                                     'create_agent_llm', bounded_factory))
    return client


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start_parser = sub.add_parser('start', help='Free persistent business fixture, Probe and gateway')
    start_parser.add_argument('--output', required=True, type=Path)
    start_parser.add_argument('--duration-seconds', type=int, default=3600)
    start_parser.add_argument('--scenario', choices=['endpoint', 'stopped', 'normal'], default='endpoint')
    product_parser = sub.add_parser('backend', help='Production API and built frontend, isolated database')
    product_parser.add_argument('--output', required=True, type=Path)
    product_parser.add_argument('--port', type=int, default=8200)
    product_parser.add_argument('--run-model', action='store_true', help='Explicitly enable one paid diagnosis')
    product_parser.add_argument('--profile', type=Path, default=ROOT / '.env.agent-test')
    product_parser.add_argument('--previous-cost', type=Path)
    product_parser.add_argument('--timeout-authorization', type=Path)
    product_parser.add_argument('--model-max-output-tokens', type=int, default=4096,
                                help='Maximum output tokens per model request (default: 4096)')
    args = parser.parse_args()
    if args.command == 'start':
        if not 1 <= args.duration_seconds <= 43200:
            parser.error('duration must be between 1 and 43200 seconds')
        asyncio.run(start(args.output, args.duration_seconds, args.scenario))
    else:
        if not args.run_model and (args.previous_cost or args.timeout_authorization):
            parser.error('cost ledger and timeout authorization require --run-model')
        backend(args)
