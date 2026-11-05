"""Real-model acceptance; each paid run requires explicit authorization."""
import asyncio
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_diagnostic_boundary import SETUP, docker

FLASH_PRICING = {
    'input_cny_per_million': 2, 'output_cny_per_million': 8,
    'verified_on': '2026-11-01',
    'source': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing',
    'basis': 'Flash peak, cache miss; official legacy v4-flash alias billed as Flash',
}
ALIYUN_FLASH_MODEL = 'deepseek-v4.1-flash-1017'
ALIYUN_FLASH_BASE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
ALIYUN_FLASH_PRICING = {
    'input_cny_per_million': 2, 'output_cny_per_million': 8,
    'verified_on': '2026-11-03',
    'source': 'https://help.aliyun.com/zh/model-studio/model-pricing',
    'basis': 'DashScope Beijing, peak, cache miss; deepseek-v4.1-flash-1017',
}


class EvaluationBudgetExceeded(RuntimeError):
    def __init__(self, reason_code, message):
        super().__init__(message)
        self.reason_code = reason_code


def model_usage_known(row):
    usage = row.get('usage')
    return (row.get('http_status') == 200 and isinstance(usage, dict)
        and all(type(usage.get(key)) is int and usage[key] >= 0
                for key in ('prompt_tokens', 'completion_tokens')))


class PaidRequestBudget:
    # Reserve input UTF-8 bytes + 8192 for token/protocol overhead, then settle usage.
    def __init__(self, output, max_output_tokens=2048, limit_cny=5, run_limit_cny=None,
                 allow_unpriced_models=False, max_requests=None, run_max_requests=None, api_base=None,
                 fallback_api_base=None, fallback_model=None):
        self.api_base = (api_base or 'https://api.deepseek.com').rstrip('/')
        self.pricing = ALIYUN_FLASH_PRICING if self.api_base == ALIYUN_FLASH_BASE else FLASH_PRICING
        candidate_fallback = (fallback_api_base or '').rstrip('/')
        self.fallback_api_base = (candidate_fallback if candidate_fallback == 'https://api.deepseek.com'
                                  and fallback_model in {'deepseek-v4-flash', 'deepseek-flash'} else None)
        self.fallback_model = fallback_model if self.fallback_api_base else None
        if isinstance(limit_cny, bool) or not isinstance(limit_cny, (int, float)) or not math.isfinite(limit_cny) or limit_cny <= 0:
            raise ValueError('invalid cumulative cost limit')
        self.output = output
        self.limit_cny = limit_cny
        self.max_output_tokens = max_output_tokens
        if run_limit_cny is not None and (type(run_limit_cny) not in (int, float)
                or not math.isfinite(run_limit_cny) or run_limit_cny <= 0):
            raise ValueError('invalid per-run reservation limit')
        self.run_limit_cny = run_limit_cny
        self.allow_unpriced_models = bool(allow_unpriced_models)
        for cap in (max_requests, run_max_requests):
            if cap is not None and (type(cap) is not int or cap <= 0):
                raise ValueError('request caps must be positive integers')
        self.max_requests = max_requests
        self.run_max_requests = run_max_requests
        self.inherited_requests = 0
        self.inherited_reserved = 0.0
        self.reserved = 0.0
        self.ledger = []
        self.blocked_requests = []
        self.authorized_historical_timeouts = []

    def usage_unknown_without_authorization(self, row):
        return (not model_usage_known(row) and not (
            type(row.get('number')) is int and 0 < row['number'] <= self.inherited_requests
            and row in self.authorized_historical_timeouts))

    def reject(self, body, reason_code, message):
        self.blocked_requests.append({'request_number': len(self.ledger) + 1,
            'model': body.get('model', ''), 'reason_code': reason_code, 'reason': message,
            'sent': False})
        self.save()
        raise EvaluationBudgetExceeded(reason_code, message)

    def reserve(self, body, *, require_known_usage=False, api_base=None):
        # Real transports must stop even when a planner/executor swallowed the last error.
        if require_known_usage and any(self.usage_unknown_without_authorization(row) for row in self.ledger):
            self.reject(body, 'previous_request_usage_unknown',
                'A prior model request failed or has unknown usage; stopping further sends')
        if any(row.get('budget_bound_exceeded') for row in self.ledger):
            self.reject(body, 'usage_exceeded_reservation_bound',
                'Reported model usage exceeded the reserved token bound; stopping further sends')
        model = body.get('model', '')
        endpoint = (api_base or self.api_base).rstrip('/')
        # Known DeepSeek aliases stay priced even when unknown models are explicitly allowed.
        primary_aliyun = endpoint == ALIYUN_FLASH_BASE
        official_fallback = (endpoint == self.fallback_api_base and model == self.fallback_model
                             and endpoint is not None)
        official_primary = (endpoint == self.api_base
                            and endpoint in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'})
        if primary_aliyun and model != ALIYUN_FLASH_MODEL:
            self.reject(body, 'model_not_allowed', 'Aliyun evaluation is locked to the selected model')
        priced_model = ((primary_aliyun and model == ALIYUN_FLASH_MODEL)
            or (official_fallback)
            or (official_primary
                and model in {'deepseek-v4-flash', 'deepseek-flash'}))
        if not priced_model and not self.allow_unpriced_models:
            self.reject(body, 'unpriced_model', 'Pricing not verified for configured model')
        if self.max_requests is not None and len(self.ledger) >= self.max_requests:
            self.reject(body, 'max_requests', 'Model request cap reached')
        if self.run_max_requests is not None and len(self.ledger) - self.inherited_requests >= self.run_max_requests:
            self.reject(body, 'per_run_request_limit', 'Per-run model request cap reached')
        input_upper = len(json.dumps(body, ensure_ascii=False).encode()) + 8192
        output_upper = min(int(body.get('max_tokens') or body.get('max_completion_tokens') or self.max_output_tokens), self.max_output_tokens)
        body.pop('max_completion_tokens', None)
        body['max_tokens'] = output_upper
        body['stream'] = False
        rates = ALIYUN_FLASH_PRICING if primary_aliyun else FLASH_PRICING
        reserve = (input_upper * rates['input_cny_per_million']
                   + output_upper * rates['output_cny_per_million']) / 1_000_000 if priced_model else 0.0
        if (self.run_limit_cny is not None
                and self.reserved - self.inherited_reserved + reserve > self.run_limit_cny):
            self.reject(body, 'per_run_cost_limit', 'Per-run reservation limit reached')
        if self.reserved + reserve > self.limit_cny:
            self.reject(body, 'cumulative_cost_limit',
                f'{self.limit_cny:g} CNY request reservation limit reached')
        self.reserved += reserve
        row = {'number':len(self.ledger)+1,'model':model,'api_base':endpoint,'input_token_upper':input_upper,
               'output_token_upper':output_upper,'reserved_cny':reserve,'status':'reserved',
               'pricing_verified': priced_model}
        if priced_model:
            row.update(pricing=dict(rates), reservation_upper_cny=reserve)
        self.ledger.append(row)
        self.save()
        return row

    def request_limits(self):
        return {'max_requests': self.max_requests, 'run_max_requests': self.run_max_requests,
            'inherited_requests': self.inherited_requests}

    def save(self):
        for row in self.ledger[self.inherited_requests:]:
            # Historical rows keep their original accounting; unknown usage keeps its reserve.
            if 'reservation_upper_cny' in row and row.get('pricing_verified') and model_usage_known(row):
                usage, rates = row['usage'], row['pricing']
                row['reserved_cny'] = (usage['prompt_tokens'] * rates['input_cny_per_million']
                    + usage['completion_tokens'] * rates['output_cny_per_million']) / 1_000_000
                row['budget_bound_exceeded'] = (usage['prompt_tokens'] > row['input_token_upper']
                    or usage['completion_tokens'] > row['output_token_upper'])
                row['reservation_status'] = 'settled_at_peak_rates'
        self.reserved = math.fsum(row['reserved_cny'] for row in self.ledger)
        (self.output / 'cost.json').write_text(json.dumps({
            'reserved_cny':self.reserved,'limit_cny':self.limit_cny,'requests':self.ledger,
            'blocked_requests': self.blocked_requests,
            'request_limits': self.request_limits(),
            'rate_basis':'New priced rows use per-row CNY peak rates; historical rates and unknown costs remain unchanged',
            'pricing_source': self.pricing['source'],
        },ensure_ascii=False,indent=2),encoding='utf-8')

    def cost_summary(self, start_index=0):
        rows = self.ledger[start_index:]
        known, unknown, unpriced = 0.0, 0, False
        for row in rows:
            usage_known = model_usage_known(row)
            if not usage_known:
                unknown += 1
            # Older ledgers predate the explicit pricing_verified/model fields.
            # Treat those rows as legacy DeepSeek-priced entries so a resume
            # does not turn known historical usage into an unknown supplier bill.
            pricing_verified = row.get('pricing_verified')
            if pricing_verified is None:
                pricing_verified = row.get('model') in (None, 'deepseek-v4-flash', 'deepseek-flash')
            if pricing_verified is False:
                unpriced = True
                continue
            usage = row.get('usage')
            if not usage_known:
                continue
            rates = row.get('pricing') or {'input_cny_per_million': .30 * 8,
                                          'output_cny_per_million': 1.20 * 8}
            known += (usage['prompt_tokens'] * rates['input_cny_per_million']
                      + usage['completion_tokens'] * rates['output_cny_per_million']) / 1_000_000
        return {'requests': len(rows), 'usage_unknown_requests': unknown,
            'pricing_unknown_requests': sum(1 for row in rows if (
                row.get('pricing_verified') is False or (
                    row.get('pricing_verified') is None and row.get('model') not in
                    (None, 'deepseek-v4-flash', 'deepseek-flash')))),
            'known_estimated_cny_peak': known, 'estimated_cny_peak': None if unknown or unpriced else known,
            'reserved_cny': math.fsum(row['reserved_cny'] for row in rows),
            'supplier_bill_verified': False, 'pricing_verified': not unpriced}

    def actual_cost_cny(self):
        return self.cost_summary()['estimated_cny_peak']


APP = r'''
import ctypes, http.server, json, os, socket
from datetime import datetime, timezone
ctypes.CDLL(None).prctl(15,b'api-worker',0,0,0)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        endpoint=('127.0.0.1',int(os.environ['DB_PORT']))
        try:
            with socket.create_connection(endpoint,timeout=1): pass
            code=200; result={'status':'ok','database':'connected'}
        except OSError as error:
            code=503; result={'status':'unavailable','database':'connection failed'}
            with open('/tmp/api.log','a') as log:
                log.write(datetime.now(timezone.utc).isoformat()+' ERROR database connect '+str(endpoint)+': '+str(error)+'\n')
        self.send_response(code); self.end_headers(); self.wfile.write(json.dumps(result).encode())
        with open('/tmp/api.log','a') as log:
            log.write(datetime.now(timezone.utc).isoformat()+' request '+self.path+' status='+str(code)+'\n')
    def log_message(self,*args): pass
with open('/tmp/api.pid','w') as pid: pid.write(str(os.getpid()))
with open('/tmp/api.log','a') as log: log.write(datetime.now(timezone.utc).isoformat()+' api listening=18080 database=127.0.0.1:'+os.environ['DB_PORT']+'\n')
http.server.HTTPServer(('0.0.0.0',18080),Handler).serve_forever()
'''
DB = r'''
import ctypes, os, socket
ctypes.CDLL(None).prctl(15,b'db-worker',0,0,0)
with open('/tmp/db.pid','w') as pid: pid.write(str(os.getpid()))
server=socket.socket(); server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
server.bind(('127.0.0.1',15432)); server.listen()
while True:
    client,_=server.accept(); client.close()
'''
HELPER = r'''
import ast,json,pathlib,sys,os
tree=ast.parse(pathlib.Path('/opt/diagnostic_server.py').read_text()); nodes=[]
for node in tree.body:
    if isinstance(node,ast.ImportFrom) and node.module.startswith('fastmcp'): continue
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='mcp' for t in node.targets): continue
    if isinstance(node,(ast.Import,ast.ImportFrom,ast.Assign,ast.FunctionDef)):
        if isinstance(node,ast.FunctionDef): node.decorator_list=[]
        nodes.append(node)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'production_helpers','exec'))
os.environ.update(DIAGNOSTIC_EXEC_ENABLED='true',DIAGNOSTIC_EVIDENCE_DIR='/verification/evidence',DIAGNOSTIC_SSH_CONFIG='/verification/target.json')
request=json.loads(sys.stdin.read())
allowed={'diagnostic_query':_diagnostic_query,'diagnostic_exec':_diagnostic_exec,'diagnostic_probe_dependency':_diagnostic_probe_dependency,
         'diagnostic_list_evidence':diagnostic_list_evidence,'diagnostic_read_evidence':diagnostic_read_evidence}
print(json.dumps(allowed[request['tool']](**request['arguments']),ensure_ascii=False))
'''


async def main():
    output = ROOT / 'data' / 'autonomous-model-evaluation' / uuid4().hex
    output.mkdir(parents=True)
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output/'runs.sqlite').as_posix()
    os.environ['AIOPS_CHECKPOINT_DB_PATH'] = str(output/'checkpoints.sqlite')
    from src.settings import settings
    from src.agent.aiops_llm import create_agent_llm as factory
    from src.agent.aiops.graph import AIOpsService
    from fastmcp import FastMCP
    from langchain_mcp_adapters.client import MultiServerMCPClient
    import httpx
    import uvicorn
    settings.TERMCP_ENABLED = True
    settings.ENABLE_HITL = False
    settings.ENABLE_STEP_SNAPSHOTS = True
    settings.DIAGNOSTIC_TARGET_CATALOG = json.dumps({'target_id':'test-target','services':{'orders':{'entrypoint':'http://test-target:18080/health','dependencies':['database']}}})
    budget=PaidRequestBudget(output, api_base=settings.RESOLVED_LLM_API_BASE)
    class BudgetTransport(httpx.AsyncBaseTransport):
        def __init__(self): self.inner=httpx.AsyncHTTPTransport()
        async def handle_async_request(self,request):
            body=json.loads(await request.aread())
            row=budget.reserve(body, require_known_usage=True)
            revised=httpx.Request(request.method,request.url,headers={k:v for k,v in request.headers.items() if k.lower()!='content-length'},
                                  content=json.dumps(body).encode(),extensions=request.extensions)
            from scripts.model_request_diagnostics import record_model_response
            return await record_model_response(self.inner, revised, row, budget.save)
        async def aclose(self): await self.inner.aclose()
    http=httpx.AsyncClient(transport=BudgetTransport(),timeout=60)
    def bounded_factory(**kwargs):
        llm=factory(**kwargs)
        llm.max_tokens=2048;llm.max_retries=0
        for client_name in ('root_async_client', 'root_client'):
            client = getattr(llm, client_name, None)
            if client is not None:
                client.max_retries = 0
        llm.http_async_client=http
        llm.root_async_client._client=http
        return llm
    planner=importlib.import_module('src.agent.aiops.planner')
    executor=importlib.import_module('src.agent.aiops.executor')
    investigation=importlib.import_module('src.agent.aiops.strategies.investigation')
    planner.create_agent_llm=bounded_factory;executor.create_agent_llm=bounded_factory;investigation.create_agent_llm=bounded_factory
    # 默认评测只验证隔离诊断工具；联合知识库验收通过环境变量开启，
    # 保留 planner 的经验检索并把真实四类业务 MCP 一并装载。
    joint_mcp = os.environ.get('JOINT_MCP', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if not joint_mcp:
        planner._retrieve_experience=lambda *_args,**_kwargs:''
    network='aiops-model-'+uuid4().hex[:8]; target=network+'-target'; analyzer=network+'-analysis'
    image='aiops-diagnostic-verification-base:local'
    shared=output/'shared';shared.mkdir()
    setup=SETUP.replace('"api":{"process_name":"sshd","logs":["/tmp/service.log"],"dependencies":["closed"]}',
                        '"orders":{"entrypoint":"http://test-target:18080/health","process_name":"api-worker","logs":["/tmp/api.log"],"dependencies":["database","orders-health"]}')
    setup=setup.replace('"closed":{"host":"127.0.0.1","port":1}',
                        '"database":{"host":"127.0.0.1","port":15432},"orders-health":{"host":"127.0.0.1","port":18080,"health":{"scheme":"http","path":"/health"}}')
    (shared/'setup.py').write_text(setup);(shared/'app.py').write_text(APP);(shared/'db.py').write_text(DB);(shared/'helper.py').write_text(HELPER)
    docker('network','create',network)
    server=None;service=None;results=[];trace=[]
    try:
        docker('run','-d','--name',target,'--network',network,'--network-alias','test-target',
               '-v',f'{shared}:/verification','-v',f'{ROOT/"mcp_servers/diagnostic_collector.py"}:/opt/collector.py:ro',
               '--entrypoint','sh',image,'-c','python3 /verification/setup.py && exec /usr/sbin/sshd -D -e')
        docker('run','-d','--name',analyzer,'--network',network,'--user','1000:1000','--read-only','--cap-drop','ALL',
               '--security-opt','no-new-privileges','--security-opt',f'seccomp={ROOT/"docker/diagnostic/seccomp.json"}',
               '--pids-limit','64','--memory','256m','--tmpfs','/tmp:size=16m',
               '-v',f'{shared}:/verification','-v',f'{ROOT/"mcp_servers/diagnostic_server.py"}:/opt/diagnostic_server.py:ro',
               '--entrypoint','sleep',image,'3600')
        for _ in range(50):
            if (shared/'key.pub').exists():break
            await asyncio.sleep(.2)
        scan=docker('exec',analyzer,'ssh-keyscan','-t','ed25519','test-target')
        (shared/'known_hosts').write_text(scan)
        (shared/'target.json').write_text(json.dumps({'target_id':'test-target','host':'test-target','user':'collector',
                'identity_file':'/verification/key','known_hosts':'/verification/known_hosts'}))
        (shared/'evidence').mkdir();os.chmod(shared/'evidence',0o777)
        async def invoke(name,arguments):
            process=await asyncio.create_subprocess_exec('docker','exec','-i',analyzer,'python3','/verification/helper.py',
                          stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            stdout,stderr=await process.communicate(json.dumps({'tool':name,'arguments':arguments}).encode())
            if process.returncode: raise RuntimeError('diagnostic transport failed')
            result=json.loads(stdout);trace.append({'tool':name,'arguments':arguments,'result':result})
            return result
        mcp=FastMCP('EvaluationDiagnostic')
        @mcp.tool()
        async def diagnostic_query(operation:str,service:str='',lines:int=100)->dict:
            """Real target catalog/resources/processes/ports/logs/service; use configured service names."""
            return await invoke('diagnostic_query',{'operation':operation,'service':service,'lines':lines})
        @mcp.tool()
        async def diagnostic_probe_dependency(name:str,timeout:float=3,probe:str='tcp')->dict:
            """Target-side allowlisted dns/tcp/health probes. Discover allowed dependency names from catalog."""
            return await invoke('diagnostic_probe_dependency',{'name':name,'timeout':timeout,'probe':probe})
        @mcp.tool()
        async def diagnostic_exec(command:str,timeout:float=10,max_output:int=8192)->dict:
            """Free shell in no-network sandbox; analyze collector /evidence files only. Not target proc."""
            return await invoke('diagnostic_exec',{'command':command,'timeout':timeout,'max_output':max_output})
        app=mcp.http_app(path='/mcp')
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=32089,log_level='error'))
        server_task=asyncio.create_task(server.serve())
        while not server.started: await asyncio.sleep(.1)
        diagnostic_client=MultiServerMCPClient({'diagnostic':{'transport':'streamable_http','url':'http://127.0.0.1:32089/mcp'}})
        tools=await diagnostic_client.get_tools()
        if joint_mcp:
            # 业务 MCP 使用当前 settings 的真实地址；逐服务加载由客户端负责，
            # 任何不可达服务都会在工具加载阶段暴露，而不是静默伪造数据。
            business_client=MultiServerMCPClient(settings.MCP_SERVERS)
            business_tools=await business_client.get_tools()
            business_tools = [tool for tool in business_tools if tool.name not in {
                'check_website', 'check_ports', 'check_service_health', 'check_api_endpoint',
            }]
            tools = business_tools + tools
            print(json.dumps({'stage':'tools_loaded','joint_mcp':True,
                              'business_tools':[t.name for t in business_tools],
                              'diagnostic_tools':[t.name for t in tools if t not in business_tools]},ensure_ascii=False),flush=True)
        async def tool_loader(*_args): return tools,None
        planner.load_agent_tools=tool_loader;executor.load_agent_tools=tool_loader
        executor._tools_cache.clear();executor._tools_cache_at.clear()
        service=AIOpsService()
        symptoms=('请核实单个测试目标的订单服务是否可用；如果异常，请自主调查根因，并提供现场证据和替代解释核查。'
                  '本次必须先调用知识库工具搜索“订单服务依赖数据库不可用/连接被拒绝”的排查手册，'
                  '在最终报告引用返回的 source、page 或 chunk_id；然后再用受限现场诊断工具核实，'
                  '知识库只能作排查提示，根因必须由现场原始证据支持。不要修改或重启服务。') if joint_mcp else (
                  '请核实单个测试目标的订单服务是否可用；如果异常，请自主调查根因，并提供现场证据和替代解释核查。不要修改或重启服务。')
        # 联合知识库验收只跑一个可控故障，避免重复消耗模型额度；
        # 原有隔离评测仍保留四种场景。
        planned_cases=['dependency_stopped'] if joint_mcp else ['healthy','dependency_stopped','misconfigured_dependency','application_stopped']
        stop_reason='completed'
        stop_reason_code=None
        for kind in planned_cases:
            for pidfile in ['/tmp/api.pid','/tmp/db.pid']:
                command='import os,pathlib,signal;p=pathlib.Path('+repr(pidfile)+');\nif p.exists():\n try: os.kill(int(p.read_text()),signal.SIGTERM)\n except ProcessLookupError: pass\n p.unlink()'
                docker('exec',target,'python3','-c',command)
            docker('exec',target,'sh','-c',': > /tmp/api.log')
            if kind!='dependency_stopped':docker('exec','-d',target,'python3','/verification/db.py')
            if kind!='application_stopped':docker('exec','-d','-e','DB_PORT='+('15433' if kind=='misconfigured_dependency' else '15432'),target,'python3','/verification/app.py')
            await asyncio.sleep(.5)
            health=await invoke('diagnostic_probe_dependency',{'name':'orders-health','probe':'health'})
            if kind=='healthy': assert health.get('status_code')==200,health
            trace.clear();start=time.monotonic();events=[]
            case_id=uuid4().hex
            print(json.dumps({'case_id':case_id,'stage':'started','reserved_cny':budget.reserved}),flush=True)
            case_status='completed'
            try:
                async for event in service.execute(symptoms,session_id=case_id,terminal_enabled=True):
                    events.append(event)
                    if event.get('type')=='step_complete':print(json.dumps({'case_id':case_id,'stage':'check','step':event.get('current_step'),'reserved_cny':budget.reserved},ensure_ascii=False),flush=True)
            except EvaluationBudgetExceeded as error:
                case_status='budget_stopped'
                stop_reason=str(error)
                stop_reason_code=error.reason_code
            final=next((e.get('response') or e.get('report') for e in reversed(events)
                        if e.get('type') in {'complete','report','error'} and (e.get('response') or e.get('report'))),'')
            if case_status=='completed' and (not any(e.get('type')=='complete' for e in events)
                    or any(e.get('type')=='error' or e.get('investigation_failure') for e in events)):
                case_status='incomplete'
            row={'case_id':case_id,'fixture_truth':kind,'symptom':symptoms,'response':final,'events':events,
                 'tool_trace':list(trace),'elapsed_s':round(time.monotonic()-start,2),
                 'status':case_status}
            results.append(row);(output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'case_id':case_id,'stage':'finished','truth':kind,'response':final,'reserved_cny':budget.reserved},ensure_ascii=False),flush=True)
            if case_status=='budget_stopped':break
            if case_status=='incomplete':
                stop_reason='investigation incomplete; evidence and failure report preserved'
                break
            if not final:
                stop_reason='investigation returned no final response'
                break
            if budget.reserved>=4.9:
                stop_reason='conservative reservation reached 4.9 CNY'
                break
        (output/'evaluation_summary.json').write_text(json.dumps({
            'planned_cases': planned_cases,
            'completed_cases': [row['fixture_truth'] for row in results if row.get('status')=='completed'],
            'attempted_cases': [row['fixture_truth'] for row in results],
            'stop_reason': stop_reason,
            'stop_reason_code': stop_reason_code,
            'reserved_cny': budget.reserved,
            'actual_estimated_cny': budget.actual_cost_cny(),
        },ensure_ascii=False,indent=2),encoding='utf-8')
        print('REPORT_DIRECTORY='+str(output),flush=True)
    finally:
        budget.save()
        if service:await service.close()
        if server:
            server.should_exit=True
            await server_task
        await http.aclose()
        docker('rm','-f',analyzer,target);docker('network','rm',network)


if __name__=='__main__':
    asyncio.run(main())
