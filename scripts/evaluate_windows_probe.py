"""Windows Probe preflight; real model mode requires separate user authorization."""
import asyncio
import argparse
import importlib
import json
import os
import math
import hashlib
from contextlib import contextmanager, asynccontextmanager, ExitStack
from unittest.mock import patch
from pathlib import Path
import sys
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def classify_report(report: str, diagnosis: dict | None = None) -> str:
    """Classify the report format; this does not grade diagnostic correctness."""
    if diagnosis and diagnosis.get('version') == 1 and diagnosis.get('kind') in {
            'confirmed_cause', 'localized_fault', 'healthy_within_scope', 'unlocated'}:
        return diagnosis['kind']
    text = report.strip()
    if not text:
        return 'none'
    if text.startswith('未定位根因：'):
        return 'unlocated'
    if text.startswith('当前检查范围内未发现故障'):
        return 'healthy_within_checked_scope'
    if text.startswith('根因：'):
        return 'root_cause_reported'
    if text.startswith('已定位故障层：'):
        return 'localized_fault'
    return 'unrecognized'


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous-cost', type=Path)
    parser.add_argument('--probe-config', type=Path)
    parser.add_argument('--symptom-file', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--local-runbooks', type=Path,
        help='Isolated local runbook retrieval; no embedding/rerank calls, not vector RAG validation')
    parser.add_argument('--knowledge-mcp-url', type=local_knowledge_url,
        help='Disposable loopback BM25 MCP service; only search_knowledge_base is accepted')
    parser.add_argument('--run-model', action='store_true',
        help='Paid mode; use only after explicit user authorization for this run')
    parser.add_argument('--knowledge-disabled', action='store_true',
        help='Disable planning references and knowledge tools for a matched control run')
    parser.add_argument('--limited-evidence', action='store_true',
        help='Controller-only case: withhold downstream and log observations without changing Probe permissions')
    return parser.parse_args(argv)


def local_knowledge_url(value):
    parsed = urlsplit(value)
    try:
        valid = (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
            and parsed.port is not None and 0 < parsed.port < 65536
            and not parsed.username and not parsed.password
            and parsed.path == '/mcp' and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise argparse.ArgumentTypeError('knowledge MCP must use http://127.0.0.1:<port>/mcp')
    return value


@asynccontextmanager
async def load_evaluation_tools(cfg, knowledge_url=None):
    from src.agent.mcp_client import load_tools_for_config, close_client_for_config
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    configs = []
    try:
        probe_config = {'probe': {'transport': 'streamable_http', 'url': mcp_url(cfg.gateway_url),
            'tls_verify': True, 'headers': {'Authorization': 'Bearer ' + cfg.token_file.read_text(encoding='utf-8').strip()}}}
        configs.append(probe_config)
        tools, error = await load_tools_for_config(probe_config)
        assert error is None and len(tools) == 9, 'Probe tools unavailable'
        assert {tool.name for tool in tools} == set(PROBE_TOOL_OPERATIONS) | {'probe_list_evidence'}, 'unexpected Probe tools'
        if knowledge_url:
            knowledge_config = {'knowledge': {'transport': 'streamable_http',
                'url': local_knowledge_url(knowledge_url)}}
            configs.append(knowledge_config)
            knowledge, error = await load_tools_for_config(knowledge_config)
            if error or [tool.name for tool in knowledge] != ['search_knowledge_base']:
                raise RuntimeError('Unexpected or unavailable local knowledge MCP tools')
            tools = [*tools, *knowledge]
        yield tools
    finally:
        for config in reversed(configs):
            close_client_for_config(config)


def mcp_url(gateway_url):
    parsed = urlsplit(gateway_url)
    return urlunsplit(('https' if parsed.scheme == 'wss' else 'http', parsed.netloc, '/mcp', '', ''))


def target_catalog(cfg):
    """Expose configured query names, never the token, CA or gateway settings."""
    from dataclasses import asdict
    return json.dumps({'target_id': cfg.target_id,
        'services': {name: asdict(value) for name, value in cfg.services.items()},
        'dependencies': {name: asdict(value) for name, value in cfg.dependencies.items()}},
        ensure_ascii=False)


def business_catalog(cfg):
    """The disposable app is a process, not an installed Windows service."""
    dependencies = sorted(cfg.dependencies)
    entries = {}
    for name, dep in cfg.dependencies.items():
        if name == 'localapp' and dep.health_scheme:
            entries[f'{dep.health_scheme}://{dep.host}:{dep.port}{dep.health_path}'] = name
    return json.dumps({'version': 1, 'target_id': cfg.target_id, 'services': {
        'localapp': {'aliases': ['测试应用'], 'entries': entries,
            'log_refs': ['localapp'] if 'localapp' in cfg.services else [],
            'dependencies': dependencies}}}, ensure_ascii=False)


@contextmanager
def local_runbook_retrieval(directory, output):
    """Use the real local retriever, isolated from the existing knowledge corpus."""
    from src.agent.aiops import local_retrieval
    directory = Path(directory).resolve(strict=True)
    files = sorted(directory.rglob('*.md'))
    if not files:
        raise ValueError('local runbook directory contains no Markdown documents')
    sources = [{'path': path.relative_to(directory).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    trace = []
    def retrieve(query):
        context = local_retrieval.retrieve_local(query)
        trace.append({'query': query, 'context': context, 'retrieved': bool(context),
            'context_sha256': hashlib.sha256(context.encode('utf-8')).hexdigest()})
        (output / 'knowledge_trace.json').write_text(json.dumps({
            'mode': 'local_runbooks', 'vector_rag_evaluated': False,
            'sources': sources, 'queries': trace}, ensure_ascii=False, indent=2), encoding='utf-8')
        return context
    with ExitStack() as stack:
        for name, value in {'_RUNBOOKS_DIR': directory, '_KAGGLE_SOURCES': [],
                '_HF_DIR': directory / 'huggingface', '_jsonl_index': None}.items():
            stack.enter_context(patch.object(local_retrieval, name, value))
        yield retrieve


def read_cost_ledger(path):
    """Reject incomplete/corrupt accounting instead of resetting the budget."""
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    def amount(number):
        return isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) and 0 <= number <= 5
    if not isinstance(value, dict) or value.get('limit_cny') != 5:
        raise ValueError('invalid cumulative cost limit')
    rows, reserved = value.get('requests'), value.get('reserved_cny')
    if not isinstance(rows, list) or not amount(reserved):
        raise ValueError('invalid cumulative cost ledger')
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or row.get('number') != index or not amount(row.get('reserved_cny')):
            raise ValueError('invalid request reservation')
    if not math.isclose(math.fsum(row['reserved_cny'] for row in rows), reserved, abs_tol=1e-9, rel_tol=1e-9):
        raise ValueError('cumulative cost does not match request reservations')
    return value


async def preflight(cfg, output, knowledge_url=None):
    from src.probe.evidence import validate_tool_evidence
    rows = []
    async with load_evaluation_tools(cfg, knowledge_url) as tools:
        trace = []
        tools = trace_evaluation_tools(tools, cfg.target_id, output, trace)
        by_name = {tool.name: tool for tool in tools}
        knowledge_check = None
        if knowledge_url:
            from src.agent.aiops.evidence_sources import knowledge_context
            raw = await by_name['search_knowledge_base'].ainvoke({
                'query': 'localapp availability', 'kb_id': 14, 'top_k': 3})
            fragments = knowledge_context([('local knowledge', raw)])
            assert any(item['chunk_id'] == 'localapp-guide' for item in fragments), 'runbook not retrieved'
            knowledge_check = {'transport': 'streamable_http_loopback', 'fragments': fragments,
                'vector_rag_evaluated': False, 'autonomously_selected': False}
        checks = [('probe_inventory', {})]
        checks += [('probe_dependency_probe', {'dependency': name}) for name in cfg.dependencies]
        checks += [('probe_text_log', {'service': name, 'path': path, 'lines': 20})
            for name, service in cfg.services.items() for path in service.text_logs
            if not any(char in path for char in '*?[')]
        for name, arguments in checks:
            raw = validate_tool_evidence(await by_name[name].ainvoke(arguments),
                tool_name=name, target_id=cfg.target_id)
            rows.append({'tool': name, 'arguments': arguments, 'raw': raw})
        result = {'ok': True, 'mode': 'preflight', 'model_calls': 0,
            'autonomous_model_investigation': False, 'target_id': cfg.target_id,
            'evidence_count': len(rows), 'checks': rows, 'target_catalog': json.loads(target_catalog(cfg)),
            'tool_names': [tool.name for tool in tools], 'knowledge_mcp': knowledge_check}
        (output / 'preflight.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'output': str(output), 'mode': 'preflight', 'ok': True,
            'model_calls': 0, 'evidence_count': len(rows)}, ensure_ascii=False), flush=True)


def trace_evaluation_tools(tools, target_id, output, trace):
    from src.probe.protocol import redact
    from src.probe.evidence import validate_tool_evidence, PROBE_TOOL_OPERATIONS
    from langchain_core.tools import StructuredTool
    def traced(tool):
        async def invoke(**kwargs):
            value = await tool.ainvoke(kwargs)
            valid = False
            if tool.name in PROBE_TOOL_OPERATIONS:
                validate_tool_evidence(value, target_id=target_id, tool_name=tool.name)
                valid = True
            trace.append({'tool': tool.name, 'arguments': kwargs, 'result': redact(value),
                'validated_live_evidence': valid,
                'source': 'knowledge_base' if tool.name == 'search_knowledge_base' else 'probe'})
            (output / 'tool_trace.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            return value
        return StructuredTool.from_function(coroutine=invoke, name=tool.name,
            description=tool.description, args_schema=tool.args_schema)
    return [traced(tool) for tool in tools]


async def main():
    args = parse_args()
    from scripts.windows_probe import _set_acl, config_path
    from src.probe.windows.config import load_config

    symptom_override = None
    if args.symptom_file:
        symptom_override = args.symptom_file.read_text(encoding='utf-8').strip()
        if not symptom_override:
            raise ValueError('symptom file is empty')
    output = (args.output_dir or ROOT / 'runtime' / ('windows-model-' + uuid4().hex)).resolve()
    output.mkdir(parents=True, exist_ok=False)
    _set_acl(output)
    if symptom_override:
        (output / 'symptom.txt').write_text(symptom_override, encoding='utf-8')
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output / 'runs.sqlite').as_posix()
    os.environ['AIOPS_CHECKPOINT_DB_PATH'] = str(output / 'checkpoints.sqlite')
    os.environ['ENABLE_EXPERIENCE_CONTEXT'] = 'false'
    if args.knowledge_disabled:
        args.local_runbooks = None
        args.knowledge_mcp_url = None
    cfg = load_config(args.probe_config or config_path())
    if cfg.tls_ca_file and cfg.gateway_url.startswith('wss://'):
        os.environ['SSL_CERT_FILE'] = str(cfg.tls_ca_file)
    if not args.run_model:
        await preflight(cfg, output, args.knowledge_mcp_url)
        if args.local_runbooks:
            with local_runbook_retrieval(args.local_runbooks, output) as retrieve:
                retrieve(symptom_override or 'Windows 主机运行概况')
        return
    async with load_evaluation_tools(cfg, args.knowledge_mcp_url) as tools:
        await run_model(args, cfg, output, tools, symptom_override)


async def run_model(args, cfg, output, tools, symptom_override=None):
    import httpx
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
    from src.settings import settings
    from src.agent.aiops_llm import create_agent_llm as factory
    from src.agent.aiops.graph import AIOpsService
    from src.probe.protocol import redact
    if getattr(args, 'knowledge_disabled', False):
        args.local_runbooks = None
        args.knowledge_mcp_url = None
        tools = [t for t in tools if t.name not in {'search_knowledge_base', 'list_knowledge_bases', 'get_document_info'}]

    settings.PROBE_ENABLED = True
    settings.PROBE_TARGET_ID = cfg.target_id
    settings.DIAGNOSTIC_TARGET_CATALOG = business_catalog(cfg) if 'localapp' in cfg.dependencies else target_catalog(cfg)
    settings.PROBE_EVIDENCE_DIR = str(output / 'evidence')
    settings.TERMCP_ENABLED = False
    settings.ENABLE_HITL = False
    settings.ENABLE_LLM_RETRY = False
    budget = PaidRequestBudget(output, max_output_tokens=4096)
    budget_stopped = False
    if args.previous_cost:
        previous = read_cost_ledger(args.previous_cost)
        budget.reserved = previous['reserved_cny']
        budget.ledger = previous['requests']

    class BudgetTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.AsyncHTTPTransport()
        async def handle_async_request(self, request):
            nonlocal budget_stopped
            if request.url.host != 'api.deepseek.com' or not request.url.path.endswith('/chat/completions'):
                raise RuntimeError('Evaluation permits only priced model chat requests')
            body = json.loads(await request.aread())
            input_dir = output / 'model-inputs'
            input_dir.mkdir(exist_ok=True)
            (input_dir / (uuid4().hex + '.json')).write_text(json.dumps(redact(body), ensure_ascii=False, indent=2), encoding='utf-8')
            try:
                row = budget.reserve(body)
            except EvaluationBudgetExceeded:
                budget_stopped = True
                return httpx.Response(402, request=request, json={'error': {
                    'message': 'Evaluation stopped before exceeding the cumulative 5 CNY reservation',
                    'type': 'evaluation_budget_exceeded', 'code': 'evaluation_budget_exceeded'}})
            revised = httpx.Request(request.method, request.url,
                headers={k: v for k, v in request.headers.items() if k.lower() != 'content-length'},
                content=json.dumps(body).encode(), extensions=request.extensions)
            try:
                response = await self.inner.handle_async_request(revised)
                await response.aread()
                row.update(status='returned', http_status=response.status_code)
                if response.status_code == 200:
                    data = response.json()
                    row.update(usage=data.get('usage', {}), served_model=data.get('model'))
                return response
            except Exception as exc:
                row['status'] = type(exc).__name__
                raise
            finally:
                budget.save()
        async def aclose(self):
            await self.inner.aclose()

    http = httpx.AsyncClient(transport=BudgetTransport(), timeout=60)
    def bounded_factory(**kwargs):
        llm = factory(**kwargs)
        llm.max_tokens = 4096
        llm.max_retries = 0
        llm.http_async_client = http
        llm.root_async_client._client = http
        return llm
    for module in ('planner', 'executor', 'strategies.investigation'):
        importlib.import_module('src.agent.aiops.' + module).create_agent_llm = bounded_factory
    trace = []
    wrapped = trace_evaluation_tools(tools, cfg.target_id, output, trace)
    if getattr(args, 'limited_evidence', False):
        from langchain_core.tools import StructuredTool
        narrowed = []
        for candidate in wrapped:
            if candidate.name == 'probe_text_log':
                continue
            if candidate.name == 'probe_dependency_probe':
                original = candidate
                async def entry_only(dependency: str):
                    if dependency != 'localapp':
                        raise PermissionError('This observation is unavailable in the current run')
                    return await original.ainvoke({'dependency': dependency})
                candidate = StructuredTool.from_function(coroutine=entry_only, name=original.name,
                    description=original.description, args_schema=original.args_schema)
            narrowed.append(candidate)
        wrapped = narrowed
    async def tool_loader(*args, **kwargs):
        return wrapped, None
    for module in ('planner', 'executor'):
        importlib.import_module('src.agent.aiops.' + module).load_agent_tools = tool_loader
    executor = importlib.import_module('src.agent.aiops.executor')
    executor._tools_cache.clear()
    executor._tools_cache_at.clear()
    knowledge_stack = ExitStack()
    if args.local_runbooks:
        retrieve = knowledge_stack.enter_context(local_runbook_retrieval(args.local_runbooks, output))
        knowledge_stack.enter_context(patch.object(importlib.import_module('src.agent.aiops.planner'),
            '_retrieve_experience', retrieve))
    service = AIOpsService()
    events = []
    symptom = ('只读验收这台 Windows 电脑的运行概况，没有预设故障。请自主选择检查，'
        '核实资源、允许查询的系统服务、进程和端口，并按证据决定是否需要补查。'
        '不要修改或重启。结论只覆盖实际看到的范围；部分或截断快照不能证明所有业务正常。'
        '报告实际数值、目标、采集时间、证据引用，以及缺失数据和无法排除的解释。'
        '服务清单之外的服务、完整进程路径、完整端口普查不在此次可检查范围；'
        '如工具无相应能力，应明确 unavailable，不反复请求同样数据。')
    if symptom_override:
        symptom = symptom_override
    scenario = 'provided_symptom' if args.symptom_file else 'local_overview'
    try:
        print(json.dumps({'stage': 'started', 'scenario': scenario, 'output': str(output)}), flush=True)
        execution_error = None
        try:
            async for event in service.execute(symptom, session_id='windows-overview', user_id=1, terminal_enabled=False):
                events.append(event)
                (output / 'events.json').write_text(json.dumps(redact(events), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
                print(json.dumps({'stage': event.get('type'), 'paid_requests': len(budget.ledger),
                                  'reserved_cny': budget.reserved}), flush=True)
        except Exception as exc:
            execution_error = type(exc).__name__
            events.append({'type': 'error', 'stage': 'evaluation_execution_failed', 'exception_type': execution_error})
            (output / 'events.json').write_text(json.dumps(redact(events), ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        final = next((e.get('response', '') for e in reversed(events) if e.get('type') == 'complete'), '')
        diagnosis = next((e.get('diagnosis') for e in reversed(events) if e.get('type') == 'complete'), None)
        (output / 'report.txt').write_text(final, encoding='utf-8')
        summary = {'scenario': scenario, 'scenarios_in_this_process': 1,
            'tool_calls': [t['tool'] for t in trace], 'validated_live_returns': sum(t['validated_live_evidence'] for t in trace),
            'has_final_report': bool(final), 'report_kind': classify_report(final, diagnosis), 'diagnosis': diagnosis,
            'error_events': sum(event.get('type') == 'error' for event in events),
            'requires_manual_review': bool(final), 'model_requests': len(budget.ledger),
            'budget_stopped': budget_stopped,
            'execution_error': execution_error,
            'reserved_cny': budget.reserved, 'actual_estimated_cny_peak': budget.actual_cost_cny(),
            'limit_cny': 5, 'knowledge_base_evaluated': False, 'fault_location_evaluated': False,
            'knowledge_mode': 'local_bm25_mcp' if args.knowledge_mcp_url else ('local_runbooks' if args.local_runbooks else 'disabled'),
            'knowledge_mcp_calls': sum(t['tool'] == 'search_knowledge_base' for t in trace),
            'vector_rag_evaluated': False}
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        budget.save()
        await service.close()
        await http.aclose()
        knowledge_stack.close()


if __name__ == '__main__':
    asyncio.run(main())
