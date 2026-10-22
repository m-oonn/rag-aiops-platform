"""Authorized real-model acceptance: <=4 isolated cases, <=5 CNY reserved."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_diagnostic_boundary import SETUP, docker


class EvaluationBudgetExceeded(RuntimeError):
    pass


class PaidRequestBudget:
    # Official 2026-10-14 Flash peak: USD0.30/M input, USD1.20/M output.
    # Use 8 CNY/USD and input UTF-8 bytes + 8192 for protocol/token overhead.
    def __init__(self, output, max_output_tokens=2048):
        self.output = output
        self.max_output_tokens = max_output_tokens
        self.reserved = 0.0
        self.ledger = []

    def reserve(self, body):
        model = body.get('model', '')
        if model not in {'deepseek-v4-flash', 'deepseek-flash'}:
            raise EvaluationBudgetExceeded('Pricing not verified for configured model')
        input_upper = len(json.dumps(body, ensure_ascii=False).encode()) + 8192
        output_upper = min(int(body.get('max_tokens') or body.get('max_completion_tokens') or self.max_output_tokens), self.max_output_tokens)
        body.pop('max_completion_tokens', None)
        body['max_tokens'] = output_upper
        body['stream'] = False
        reserve = (input_upper * .30 + output_upper * 1.20) * 8 / 1_000_000
        if self.reserved + reserve > 5.0:
            raise EvaluationBudgetExceeded('5 CNY request reservation limit reached')
        self.reserved += reserve
        row = {'number':len(self.ledger)+1,'model':model,'input_token_upper':input_upper,
               'output_token_upper':output_upper,'reserved_cny':reserve,'status':'reserved'}
        self.ledger.append(row)
        self.save()
        return row

    def save(self):
        (self.output / 'cost.json').write_text(json.dumps({
            'reserved_cny':self.reserved,'limit_cny':5,'requests':self.ledger,
            'rate_basis':'Flash peak USD0.30 input / USD1.20 output per million; 8 CNY/USD',
            'pricing_source':'https://api-docs.deepseek.com/quick_start/pricing',
        },ensure_ascii=False,indent=2),encoding='utf-8')

    def actual_cost_cny(self):
        prompt = sum(row.get('usage', {}).get('prompt_tokens', 0) for row in self.ledger)
        completion = sum(row.get('usage', {}).get('completion_tokens', 0) for row in self.ledger)
        return (prompt * .30 + completion * 1.20) * 8 / 1_000_000


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
    budget=PaidRequestBudget(output)
    class BudgetTransport(httpx.AsyncBaseTransport):
        def __init__(self): self.inner=httpx.AsyncHTTPTransport()
        async def handle_async_request(self,request):
            body=json.loads(await request.aread())
            row=budget.reserve(body)
            revised=httpx.Request(request.method,request.url,headers={k:v for k,v in request.headers.items() if k.lower()!='content-length'},
                                  content=json.dumps(body).encode(),extensions=request.extensions)
            try:
                response=await self.inner.handle_async_request(revised)
                await response.aread()
                row['http_status']=response.status_code
                row['status']='returned'
                if response.status_code==200:
                    data=response.json(); row['usage']=data.get('usage',{}); row['served_model']=data.get('model')
                budget.save()
                return response
            except Exception as error:
                row['status']=type(error).__name__;budget.save();raise
        async def aclose(self): await self.inner.aclose()
    http=httpx.AsyncClient(transport=BudgetTransport(),timeout=60)
    def bounded_factory(**kwargs):
        llm=factory(**kwargs)
        llm.max_tokens=2048;llm.max_retries=0
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
            final=next((e.get('response','') for e in reversed(events) if e.get('type')=='complete'),'')
            row={'case_id':case_id,'fixture_truth':kind,'symptom':symptoms,'response':final,'events':events,
                 'tool_trace':list(trace),'elapsed_s':round(time.monotonic()-start,2),
                 'status':case_status}
            results.append(row);(output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'case_id':case_id,'stage':'finished','truth':kind,'response':final,'reserved_cny':budget.reserved},ensure_ascii=False),flush=True)
            if case_status=='budget_stopped':break
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
