"""Verify pending AIOps approval recovery across two independent API processes.

This is a free, isolated plumbing check.  The planner, executor, Termcp
approval authority, and shell output are deterministic test doubles; no model,
real command, Docker service, or existing database is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _configure_runtime(output: Path, phase: str):
    """Build the production routers around an isolated patched AIOpsService."""
    os.environ["DATABASE_URL"] = "sqlite:///" + (output / "api.sqlite").as_posix()
    os.environ["AIOPS_CHECKPOINT_DB_PATH"] = str(output / "checkpoints.sqlite")
    os.environ["SECRET_KEY"] = "cross-process-test-secret-" + output.name
    os.environ["TERMCP_ENABLED"] = "true"
    os.environ["ENABLE_HITL"] = "false"
    os.environ["PROBE_ENABLED"] = "false"
    os.environ["TERMCP_APPROVAL_API_URL"] = "http://127.0.0.1:1"
    os.environ["TERMCP_SSH_PROFILE"] = "isolated-test-target"

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers import aiops as aiops_router
    from src.api.routers import auth
    import src.agent.aiops.graph as graph_module
    import src.agent.aiops.executor as executor_module
    from src.agent.aiops.graph import AIOpsService
    from src.database.models import User
    from src.database.sql_session import SessionLocal, Base, engine
    from src.utils.rate_limit import limiter
    from src.utils.security import get_password_hash

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        password = "CrossProcess9a"
        for user_id in (1, 2):
            if db.get(User, user_id) is None:
                db.add(User(
                    id=user_id,
                    username=f"cross-process-{user_id}",
                    email=f"cross-process-{user_id}@example.invalid",
                    password_hash=get_password_hash(password),
                    role="user",
                    is_active=True,
                ))
        db.commit()
    finally:
        db.close()

    metrics_path = output / f"{phase}-metrics.json"
    counts = {"planner": 0, "executor": 0, "shell_output": 0}

    def save_counts():
        metrics_path.write_text(json.dumps(counts), encoding="utf-8")

    async def planner_stub(state):
        counts["planner"] += 1
        save_counts()
        return {"plan": ["读取受控测试现场"]}

    async def executor_stub(state):
        counts["executor"] += 1
        save_counts()
        if phase == "browser":
            from src.agent.aiops.executor import _record_probe_evidence
            from src.probe.protocol import evidence
            raw = evidence(
                target_id="windows-local-01",
                operation="resources",
                payload={"cpu_percent": 12.5, "memory": {"percent": 41.0}},
            )
            raw_text = json.dumps(raw, ensure_ascii=False)
            return {
                "plan": [],
                "past_steps": [("读取受控测试现场", "现场资源已采集")],
                "raw_evidence": [("读取受控测试现场", raw_text)],
                "evidence_events": _record_probe_evidence(
                    {"thread_id": state.get("thread_id"), "user_id": state.get("user_id")},
                    raw_text,
                    "resources",
                ),
            }
        return {"terminal_approval": {
            "session_id": "session-cross-process",
            "shell_id": "shell-cross-process",
            "request_id": "request-cross-process",
            "command": "diagnostic-read-only",
            "expires_at": 4102444800000,
            "step": "读取受控测试现场",
        }}

    class Strategy:
        async def decide(self, state):
            return {"response": "跨进程恢复后的受控证据已读取"}

    strategy = Strategy()
    graph_module.planner = planner_stub
    graph_module.executor = executor_stub
    AIOpsService._create_strategy = lambda self: strategy
    AIOpsService._create_run_strategy = lambda self, terminal_enabled=False: strategy

    async def approved(_approval):
        return {"state": "approved", "id": "request-cross-process"}

    # The router and graph each imported this authority separately.
    aiops_router.verify_terminal_approval = approved
    graph_module.verify_terminal_approval = approved

    async def fake_tools(_include_termcp=False):
        class OutputTool:
            name = "shell_output"

            async def ainvoke(self, _args):
                counts["shell_output"] += 1
                save_counts()
                return "approved read-only evidence"

        return [OutputTool()], None

    executor_module._get_tools_cached = fake_tools
    service = AIOpsService(strategy)
    aiops_router.aiops_service = service

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.url.hostname != "127.0.0.1":
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        return await call_next(request)

    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(aiops_router.router, prefix="/api/v1/aiops")
    if phase == "browser":
        dist = ROOT / "frontend" / "dist"
        assert (dist / "index.html").is_file(), "frontend/dist is required; run npm run build"
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        async def frontend(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            return FileResponse(dist / "index.html")

    async def shutdown():
        await service.close()
        save_counts()

    return app, shutdown, password, metrics_path


def serve(output: Path, phase: str, port: int):
    import uvicorn

    app, shutdown, _, _ = _configure_runtime(output, phase)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)
    finally:
        asyncio.run(shutdown())


def _wait_listener(port: int, process: subprocess.Popen):
    import socket

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("API process exited before listening")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("API process did not listen")


def _stop(process: subprocess.Popen):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


def _sse_json(response):
    values = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            try:
                values.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                continue
    return values


def verify_browser(output: Path):
    """Exercise the built AIOps page against the production routers."""
    import shutil
    from scripts.verify_windows_local_faults import free_port, listening_rows

    output.mkdir(parents=True, exist_ok=False)
    (output / "private.json").write_text(
        json.dumps({"username": "cross-process-1", "password": "CrossProcess9a"}),
        encoding="utf-8",
    )
    cli = shutil.which("playwright-cli.cmd")
    assert cli, "existing playwright-cli required"
    port = free_port()
    log = (output / "browser.log").open("w", encoding="utf-8")
    process = subprocess.Popen([
        sys.executable, str(Path(__file__).resolve()), "--serve", str(output),
        "--phase", "browser", "--port", str(port),
    ], cwd=ROOT, stdout=log, stderr=log)
    session = "aiops-live-" + uuid4().hex[:12]
    result = {"ok": False, "model_calls": 0, "production_http_routes": True,
              "api_mocked": False, "real_browser": True, "port": port}

    def browser(*args):
        completed = subprocess.run(
            [cli, "-s=" + session, *args], cwd=output,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=55,
        )
        (output / f"browser-{len(list(output.glob('browser-*.txt'))) + 1}.txt").write_text(
            completed.stdout + completed.stderr, encoding="utf-8")
        assert completed.returncode == 0 and "### Error" not in completed.stdout, completed.stdout
        return completed.stdout

    try:
        _wait_listener(port, process)
        browser("open", f"http://127.0.0.1:{port}/login", "--browser=msedge")
        script = output / "live.js"
        script.write_text(
            """async page => {
  const base = %s;
  const password = 'CrossProcess9a';
  const login = await page.request.post(base + '/api/v1/auth/login/access-token',
    {form: {username: 'cross-process-1', password}});
  if (login.status() !== 200) throw new Error('login failed');
  const token = (await login.json()).access_token;
  await page.evaluate(t => { localStorage.setItem('token', t); localStorage.setItem('username', 'cross-process-1'); }, token);
  await page.goto(base + '/aiops');
  await page.locator('textarea').fill('本机运行概况异常，请只读核查现场');
  await page.getByRole('button', {name: '开始诊断'}).click();
  await page.getByText('诊断报告').waitFor();
  await page.getByText('windows-local-01', {exact: false}).first().waitFor();
  const body = await page.locator('body').innerText();
  if (!body.includes('诊断完成')) throw new Error('missing completion');
  if (!body.includes('windows-local-01')) throw new Error('missing target');
  if (!body.includes('resources')) throw new Error('missing evidence kind');
  if ((await page.locator('.evidence-raw').count()) !== 0) throw new Error('raw evidence exposed');
  await page.screenshot({path: 'aiops-live.png', fullPage: true});
  return {ok: true, realLogin: true, submittedFromPage: true, sseComplete: true, evidenceTimeline: true};
}""" % json.dumps(f"http://127.0.0.1:{port}"),
            encoding="utf-8",
        )
        output_json = browser("run-code", "--filename=" + str(script))
        result.update(ok=True, real_login=True, submitted_from_page=True,
                      sse_complete=True, evidence_timeline=True, raw_hidden=True)
        (output / "browser-result.txt").write_text(output_json, encoding="utf-8")
    finally:
        try:
            browser("close")
        finally:
            _stop(process)
            log.close()
            deadline = time.monotonic() + 5
            remaining = listening_rows([port])
            while remaining and time.monotonic() < deadline:
                time.sleep(0.1)
                remaining = listening_rows([port])
            result["remaining_listeners"] = remaining
            result["port_released"] = not result["remaining_listeners"]
            (output / "summary.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"output": str(output), **result}, ensure_ascii=False))
    assert result["port_released"]


def verify(output: Path):
    import httpx
    from scripts.verify_windows_local_faults import free_port

    output.mkdir(parents=True, exist_ok=False)
    secret = {"username": "cross-process-1", "password": "CrossProcess9a"}
    (output / "private.json").write_text(json.dumps(secret), encoding="utf-8")
    first_port, second_port = free_port(), free_port()
    processes = []
    result = {"ok": False, "model_calls": 0, "production_http_routes": True,
              "termcp_authority_stub": True, "shell_output_stub": True,
              "cross_process": True, "wrong_owner_denied": False,
              "command_replayed": None}
    thread_id = None
    try:
        first_log = (output / "first.log").open("w", encoding="utf-8")
        first = subprocess.Popen([
            sys.executable, str(Path(__file__).resolve()), "--serve",
            str(output), "--phase", "first", "--port", str(first_port),
        ], cwd=ROOT, stdout=first_log, stderr=first_log)
        processes.append((first, first_log))
        _wait_listener(first_port, first)
        with httpx.Client(base_url=f"http://127.0.0.1:{first_port}", timeout=20) as client:
            token = client.post("/api/v1/auth/login/access-token",
                data={"username": secret["username"], "password": secret["password"]}).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            with client.stream("POST", "/api/v1/aiops",
                               headers=headers,
                               json={"query": "入口访问异常", "terminal_enabled": True}) as response:
                assert response.status_code == 200, response.text
                events = _sse_json(response)
            (output / "first-events.json").write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
            pending = [item for item in events if item.get("type") == "pending_terminal_approval"]
            assert len(pending) == 1, events
            thread_id = pending[0]["thread_id"]
            status = client.get(f"/api/v1/aiops/runs/{thread_id}", headers=headers)
            assert status.status_code == 200 and status.json()["status"] == "pending_terminal"
        _stop(first)
        first_log.close()

        second_log = (output / "second.log").open("w", encoding="utf-8")
        second = subprocess.Popen([
            sys.executable, str(Path(__file__).resolve()), "--serve",
            str(output), "--phase", "second", "--port", str(second_port),
        ], cwd=ROOT, stdout=second_log, stderr=second_log)
        processes.append((second, second_log))
        _wait_listener(second_port, second)
        with httpx.Client(base_url=f"http://127.0.0.1:{second_port}", timeout=20) as client:
            owner_token = client.post("/api/v1/auth/login/access-token",
                data={"username": secret["username"], "password": secret["password"]}).json()["access_token"]
            other_token = client.post("/api/v1/auth/login/access-token",
                data={"username": "cross-process-2", "password": secret["password"]}).json()["access_token"]
            owner = {"Authorization": f"Bearer {owner_token}"}
            other = {"Authorization": f"Bearer {other_token}"}
            denied = client.post(f"/api/v1/aiops/runs/{thread_id}/continue", headers=other)
            assert denied.status_code == 404, denied.text
            result["wrong_owner_denied"] = True
            with client.stream("POST", f"/api/v1/aiops/runs/{thread_id}/continue", headers=owner) as response:
                assert response.status_code == 200, response.text
                resumed = _sse_json(response)
            assert any(item.get("type") == "complete" for item in resumed), resumed
            final = client.get(f"/api/v1/aiops/runs/{thread_id}", headers=owner)
            assert final.status_code == 200 and final.json()["status"] == "completed"
            again = client.post(f"/api/v1/aiops/runs/{thread_id}/continue", headers=owner)
            assert again.status_code == 409, again.text
        _stop(second)
        second_log.close()

        first_metrics = json.loads((output / "first-metrics.json").read_text(encoding="utf-8"))
        second_metrics = json.loads((output / "second-metrics.json").read_text(encoding="utf-8"))
        assert first_metrics == {"planner": 1, "executor": 1, "shell_output": 0}, first_metrics
        assert second_metrics == {"planner": 0, "executor": 0, "shell_output": 1}, second_metrics
        result.update(ok=True, thread_id=thread_id, first_process=first_metrics,
                      second_process=second_metrics, command_replayed=False)
    finally:
        for process, log in processes:
            _stop(process)
            if not log.closed:
                log.close()
        (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), **result}, ensure_ascii=False))
    assert result["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--phase", choices=["first", "second", "browser"])
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.serve:
        assert args.output and args.phase and args.port
        serve(args.output, args.phase, args.port)
    else:
        base = args.output or (ROOT / "runtime")
        if args.phase == "browser":
            verify_browser(base / ("aiops-browser-" + uuid4().hex))
        else:
            verify(base / ("cross-process-" + uuid4().hex))
