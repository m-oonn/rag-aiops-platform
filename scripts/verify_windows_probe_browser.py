"""Real browser + production evidence/auth routes on a local DB copy; no model calls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(output, port):
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output / 'browser.sqlite').as_posix()
    os.environ['AIOPS_CHECKPOINT_DB_PATH'] = str(output / 'browser-checkpoints.sqlite')
    os.environ['SECRET_KEY'] = uuid4().hex + uuid4().hex
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from src.api.routers import aiops, auth
    from src.database.sql_session import SessionLocal
    from src.database.models import User
    from src.utils.security import get_password_hash
    from src.utils.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    import uvicorn
    config = json.loads((output / 'private.json').read_text(encoding='utf-8'))
    db = SessionLocal()
    try:
        for uid in (1, 2):
            assert db.get(User, uid) is None, 'not an isolated database'
            db.add(User(id=uid, username='browser-test-' + str(uid),
                email=f'browser-test-{uid}@example.invalid', is_active=True, role='user',
                password_hash=get_password_hash(config['password'])))
        db.commit()
    finally:
        db.close()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.middleware('http')
    async def read_only_routes(request: Request, call_next):
        path = request.url.path
        if path.startswith('/api/') and not (
            request.method == 'GET' and path.startswith('/api/v1/aiops/') or
            request.method == 'POST' and path == '/api/v1/auth/login/access-token'
        ):
            return JSONResponse({'detail': 'disabled in free browser verification'}, status_code=403)
        return await call_next(request)

    app.include_router(auth.router, prefix='/api/v1/auth')
    app.include_router(aiops.router, prefix='/api/v1/aiops')
    dist = ROOT / 'frontend/dist'
    assert (dist / 'index.html').is_file()
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/{path:path}')
    async def frontend(path: str):
        if path.startswith('api/'):
            return JSONResponse({'detail': 'not found'}, status_code=404)
        return FileResponse(dist / 'index.html')

    uvicorn.run(app, host='127.0.0.1', port=port, access_log=False)


def verify(source):
    from scripts.windows_probe import _set_acl
    from scripts.verify_windows_local_faults import free_port, wait_listener, stop, listening_rows
    source = source.resolve()
    summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
    runs = [x for x in summary['cases'] if x['case'].startswith('fixed_model_graph_')]
    assert len(runs) == 2 and all(x['status'] == 'passed' for x in runs)
    cli = shutil.which('playwright-cli.cmd')
    assert cli, 'existing playwright-cli required'
    output = source / ('browser-verification-' + uuid4().hex)
    output.mkdir()
    if os.name == 'nt':
        _set_acl(output)
    origin_db = sqlite3.connect((source / 'ledger.sqlite').as_uri() + '?mode=ro', uri=True)
    copied_db = sqlite3.connect(output / 'browser.sqlite')
    try:
        origin_db.backup(copied_db)
    finally:
        copied_db.close()
        origin_db.close()
    origin_checkpoint = sqlite3.connect((source / 'graph-checkpoints.sqlite').as_uri() + '?mode=ro', uri=True)
    copied_checkpoint = sqlite3.connect(output / 'browser-checkpoints.sqlite')
    try:
        origin_checkpoint.backup(copied_checkpoint)
    finally:
        copied_checkpoint.close()
        origin_checkpoint.close()
    port = free_port()
    private = {'password': uuid4().hex + 'a1', 'runs': runs, 'url': f'http://127.0.0.1:{port}'}
    (output / 'private.json').write_text(json.dumps(private), encoding='utf-8')
    session = 'probe-' + uuid4().hex[:12]
    result = {'ok': False, 'model_calls': 0, 'source_modified': False,
        'evidence_is_historical': True, 'browser_session': session, 'port': port}
    logs = []
    process = None

    def browser(*args):
        completed = subprocess.run([cli, '-s=' + session, *args], cwd=output,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=55)
        logs.append({'action': args[0], 'exit_code': completed.returncode})
        (output / ('cli-' + str(len(logs)) + '.txt')).write_text(
            completed.stdout + completed.stderr, encoding='utf-8')
        assert completed.returncode == 0 and '### Error' not in completed.stdout, 'browser action failed; inspect protected CLI log'
        return completed.stdout

    def code(name, body):
        path = output / (name + '.js')
        path.write_text('async page => {\n' + body + '\n}', encoding='utf-8')
        return browser('run-code', '--filename=' + str(path))

    try:
        with (output / 'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                '--serve', str(output), '--port', str(port)], cwd=ROOT, stdout=log, stderr=log)
            wait_listener(port, process)
            browser('open', private['url'] + '/login', '--browser=msedge')
            shared = f'const config = {json.dumps(private)};\n' + r'''
const check = (value, message) => { if (!value) throw new Error(message); };
const login = async uid => {
  const response = await page.request.post(config.url + '/api/v1/auth/login/access-token',
    {form: {username: 'browser-test-' + uid, password: config.password}});
  check(response.status() === 200, 'real login failed');
  return (await response.json()).access_token;
};
const ownerToken = await login(1);
await page.evaluate(token => localStorage.setItem('token', token), ownerToken);
'''
            normal = shared + r'''
await page.context().route('**/*', route => {
  return route.request().url().startsWith(config.url + '/') ? route.continue() : route.abort();
});
const otherToken = await login(2);
for (const run of config.runs) {
  const base = config.url + '/api/v1/aiops/runs/' + run.thread_id;
  check((await page.request.get(base + '/evidence')).status() === 401, 'anonymous access');
  check((await page.request.get(base + '/evidence',
    {headers: {Authorization: 'Bearer ' + otherToken}})).status() === 404, 'other owner access');
  await page.evaluate(tid => localStorage.setItem('aiops_last_thread', tid), run.thread_id);
  await page.goto(config.url + '/aiops');
  await page.locator('.el-timeline-item').nth(3).waitFor();
  check(await page.locator('.el-timeline-item').count() === 4, 'four evidence rows expected');
  check(await page.getByText('查看现场证据（脱敏）', {exact: true}).count() === 0, 'normal user raw button');
  check(await page.locator('.evidence-raw').count() === 0, 'normal user raw content');
  const text = await page.locator('body').innerText();
  check(text.includes('windows-local-01') && text.includes('windows_probe'), 'missing provenance');
  const ledger = await (await page.request.get(base + '/evidence', {headers:{Authorization:'Bearer ' + ownerToken}})).json();
  for (const item of ledger.evidence) {
    const row = page.locator('[id="evidence-' + item.evidence_id + '"]');
    check((await row.innerText()).includes(item.fresh ? '新鲜' : '过期/不可用'), 'freshness differs from ledger');
  }
  const stored = await (await page.request.get(base, {headers:{Authorization:'Bearer ' + ownerToken}})).json();
  check(text.includes(stored.report.split('\n')[0]), 'missing persisted report');
  check(text.includes('已检查范围'), 'structured diagnosis missing');
  if (stored.diagnosis.kind === 'localized_fault') {
    check(text.includes('故障层已定位，深层原因未明') && text.includes('已观察到：'), 'fault findings missing');
    check((stored.diagnosis.observed_findings || []).length > 0, 'missing persisted findings');
  } else check(text.includes('尚未定位'), 'unlocated label missing');
  check(text.includes('未决问题：'), 'unresolved questions missing');
  check(await page.locator('.diagnosis-result button').count() > 0, 'canonical evidence links missing');
  await page.locator('.diagnosis-result button').first().click();
  await page.reload();
  await page.locator('.el-timeline-item').nth(3).waitFor();
  check(await page.locator('.el-timeline-item').count() === 4, 'reload duplicated or lost evidence');
  await page.getByRole('button', {name: '刷新证据状态'}).click();
  check(await page.locator('.el-timeline-item').count() === 4, 'refresh duplicated evidence');
  await page.screenshot({path: run.case + '-normal-user.png', fullPage: true});
}
check((await page.request.post(config.url + '/api/v1/aiops', {data:{query:'forbidden'}})).status() === 403, 'paid route open');
return {ok:true, role:'user', runs:2, evidencePerRun:4, realLogin:true, reload:true, crossOwnerDenied:true};
'''
            normal_output = code('ordinary-user', normal)
            assert '"ok": true' in normal_output or '"ok":true' in normal_output
            db = sqlite3.connect(output / 'browser.sqlite')
            try:
                db.execute("UPDATE users SET role='auditor' WHERE id=1")
                db.commit()
            finally:
                db.close()
            audit = shared + r'''
for (const run of config.runs) {
  await page.evaluate(tid => localStorage.setItem('aiops_last_thread', tid), run.thread_id);
  await page.goto(config.url + '/aiops');
  await page.getByText('查看现场证据（脱敏）', {exact:true}).nth(3).waitFor();
  check(await page.getByText('查看现场证据（脱敏）', {exact:true}).count() === 4, 'audit buttons missing');
  await page.getByText('查看现场证据（脱敏）', {exact:true}).first().click();
  await page.locator('.evidence-raw').waitFor();
  const raw = JSON.parse(await page.locator('.evidence-raw').innerText());
  check(raw.target_id === 'windows-local-01' && raw.data_source === 'probe_target' && raw.raw_hash.startsWith('sha256:'), 'invalid raw provenance');
  await page.screenshot({path: run.case + '-auditor.png', fullPage:true});
  await page.reload();
  await page.getByText('查看现场证据（脱敏）', {exact:true}).nth(3).waitFor();
  check(await page.locator('.evidence-raw').count() === 0, 'raw should require explicit read after reload');
}
return {ok:true, role:'auditor', runs:2, rawOnDemand:true, reload:true};
'''
            audit_output = code('auditor', audit)
            assert '"ok": true' in audit_output or '"ok":true' in audit_output
            result.update(ok=True, real_browser=True, real_login=True, ordinary_user_runs=2,
                auditor_runs=2, evidence_per_run=4, cross_owner_denied=True, reload_verified=True,
                raw_requires_explicit_read=True, deployed_local_server=True, api_mocked=False,
                autonomous_model_investigation=False)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        try:
            browser('close')
        finally:
            if process:
                stop(process)
            result['remaining_listeners'] = listening_rows([port])
            result['port_released'] = not result['remaining_listeners']
            result['actions'] = logs
            (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'output': str(output), **result}, ensure_ascii=False))
    assert result['port_released'], 'owned listener remained'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, nargs='?')
    parser.add_argument('--serve', type=Path)
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        assert args.source, 'source run directory required'
        verify(args.source)
