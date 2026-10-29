"""隔离浏览器验收：正式路由/调查图/SQLite/SSE，固定模型和工具输入，无在线调用。"""
import argparse
import asyncio
from contextlib import asynccontextmanager
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(output, port, knowledge_kb=None):
    output.mkdir(parents=True, exist_ok=False)
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output / 'browser.sqlite').as_posix()
    os.environ['AIOPS_CHECKPOINT_DB_PATH'] = str(output / 'checkpoints.sqlite')
    os.environ['PROBE_EVIDENCE_DIR'] = str(output / 'evidence')
    os.environ['SECRET_KEY'] = uuid4().hex + uuid4().hex
    os.environ['ENABLE_HITL'] = 'false'
    os.environ['ENABLE_DYNAMIC_CLASSIFICATION'] = 'false'
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from src.database.sql_session import Base, engine, SessionLocal
    from src.database.models import User
    from src.utils.security import get_password_hash
    from src.api.routers import aiops, auth
    from src.agent.aiops import run_store
    from src.agent.aiops.events import make_complete_event, investigation_summary
    from src.agent.aiops.strategies import investigation as inv
    from src.agent.aiops.strategies.default import DefaultReplanStrategy
    from src.utils.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.settings import settings
    from src.probe.protocol import evidence
    import uvicorn
    Base.metadata.create_all(engine)
    db = SessionLocal()
    for uid in (1, 2):
        db.add(User(id=uid, username='offline-browser-' + str(uid),
            email=f'offline-browser-{uid}@example.invalid', is_active=True, role='user',
            password_hash=get_password_hash('OfflineDemo2026')))
    db.commit()
    db.close()
    if knowledge_kb is not None:
        # 仅复制本次指定知识库；不复制原数据库的账号、凭据和其他业务数据。
        import sqlite3
        from src.database.models import KnowledgeBase, KnowledgeDocument, DocumentChunk
        origin = sqlite3.connect((ROOT / 'rag_system.db').as_uri() + '?mode=ro', uri=True)
        origin.row_factory = sqlite3.Row
        db = SessionLocal()
        try:
            row = dict(origin.execute('SELECT * FROM knowledge_bases WHERE id=?', (knowledge_kb,)).fetchone())
            assert json.loads(row['chunking_config'])['retrieval_mode'] == 'bm25'
            row.update(owner_id=1)
            for table, records in [('knowledge_bases', [row]),
                    ('knowledge_documents', [dict(r) for r in origin.execute('SELECT * FROM knowledge_documents WHERE kb_id=?', (knowledge_kb,))]),
                    ('document_chunks', [dict(r) for r in origin.execute('SELECT dc.* FROM document_chunks dc JOIN knowledge_documents kd ON dc.doc_id=kd.id WHERE kd.kb_id=?', (knowledge_kb,))])]:
                for item in records:
                    names = ','.join(item)
                    placeholders = ','.join(':' + key for key in item)
                    from sqlalchemy import text
                    db.execute(text(f'INSERT INTO {table} ({names}) VALUES ({placeholders})'), item)
            db.commit()
        finally:
            db.close()
            origin.close()
    helpers = runpy.run_path(str(ROOT / 'tests/test_investigation_mechanisms.py'))
    graph_module = importlib.import_module('src.agent.aiops.graph')

    class OfflineService(graph_module.AIOpsService):
        def __init__(self):
            super().__init__()
            self.offline_lock = asyncio.Lock()

        async def execute(self, user_input, session_id='offline', user_id=None, **kwargs):
            async with self.offline_lock:
                case = 'contradiction' if '矛盾' in user_input else 'protection'
                tid = 'offline-' + case + '-' + uuid4().hex[:20]
                executed = []
                async def planner(state):
                    return {'plan': ['离线固定输入：初始检查']}
                async def executor(state):
                    task = state['plan'][0]
                    executed.append(task)
                    raw = []
                    evidence_events = []
                    if len(executed) == 2 and case == 'contradiction':
                        sample = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                            payload={'dependency': 'db', 'tcp': 'ok'})
                        raw = [('离线工具夹具：下游探测', json.dumps(sample))]
                        from src.agent.aiops.executor import _record_probe_evidence
                        evidence_events = _record_probe_evidence(state, json.dumps(sample), 'dependency_probe')
                        assert len(evidence_events) == 1, 'offline evidence ledger write failed'
                    return {'plan': state['plan'][1:], 'past_steps': [(task, '离线固定工具输入')],
                            'raw_evidence': raw, 'evidence_events': evidence_events}
                second = helpers['proposal'](include_alternative=(case != 'protection'))
                second.next_check = '再次核查下游'
                model = AsyncMock(side_effect=[helpers['proposal'](), second,
                    inv.InvestigationDecision(hypothesis='离线验收：未查清', blocked_reason='固定输入结束，未调用真实模型')])
                state = helpers['initial'](True, True)
                state.update(input='离线固定输入验收：' + user_input, autonomous_investigation=True,
                             past_steps=[], response='', thread_id=tid, user_id=user_id)
                run_store.create_run(tid, user_id, state['input'])
                with (patch.object(graph_module, 'planner', planner),
                      patch.object(graph_module, 'executor', executor),
                      patch.object(inv, 'create_agent_llm', lambda **kwargs: object()),
                      patch.object(inv, 'ainvoke_structured', model)):
                    graph = await self._persistent_graph(DefaultReplanStrategy())
                    config = {'configurable': {'thread_id': tid}}
                    events = []
                    async for event in self._stream_events(graph, config, state):
                        events.append(event)
                        yield event
                    final = (await graph.aget_state(config)).values
                    tracking = final['diagnosis']['mechanisms']
                    kind = 'contradiction_triggered' if case == 'contradiction' else 'protection_check_selected'
                    assert any(e['kind'] == kind for e in tracking['events'])
                    assert executed[-1] == helpers['check']().next_check
                    response = '离线固定输入流程验收（非真实模型诊断）\n\n' + final['response']
                    run_store.mark_completed(tid, response)
                    complete = make_complete_event(response, thread_id=tid, diagnosis=final['diagnosis'],
                                                    investigation=investigation_summary(final))
                    events.append(complete)
                    (output / (tid + '.json')).write_text(json.dumps({
                        'model_calls': 0, 'fixed_decision_calls': model.await_count, 'executed': executed,
                        'events': events, 'case': case, 'autonomous_model_verified': False
                    }, ensure_ascii=False, indent=2), encoding='utf-8')
                    yield complete

    service = OfflineService()
    aiops.aiops_service = service
    @asynccontextmanager
    async def lifespan(app):
        yield
        await service.close()
    app = FastAPI(lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    @app.middleware('http')
    async def guard(request: Request, call_next):
        path = request.url.path
        allowed = (request.method == 'GET' and path.startswith('/api/v1/aiops/')) or (
            request.method == 'POST' and path in ('/api/v1/auth/login/access-token', '/api/v1/aiops'))
        if knowledge_kb is not None:
            allowed = allowed or (request.method == 'GET' and path.startswith('/api/v1/knowledge-bases/')) or (
                request.method == 'POST' and path == f'/api/v1/knowledge-bases/{knowledge_kb}/search')
        if path.startswith('/api/') and not allowed:
            return JSONResponse({'detail': 'Disabled in offline verification'}, status_code=403)
        return await call_next(request)
    app.include_router(auth.router, prefix='/api/v1/auth')
    app.include_router(aiops.router, prefix='/api/v1/aiops')
    if knowledge_kb is not None:
        from src.api.routers import knowledge_base
        app.include_router(knowledge_base.router, prefix='/api/v1/knowledge-bases')
    app.mount('/assets', StaticFiles(directory=ROOT / 'frontend/dist/assets'), name='assets')
    @app.get('/{path:path}')
    async def frontend(path: str):
        return FileResponse(ROOT / 'frontend/dist/index.html')
    print('OFFLINE_BROWSER_READY', port, str(output), flush=True)
    uvicorn.run(app, host='127.0.0.1', port=port, access_log=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--knowledge-kb', type=int)
    args = parser.parse_args()
    serve(args.output.resolve(), args.port, args.knowledge_kb)
