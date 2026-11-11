# spec · platform（平台启动、配置、安全与 CI）

- 模块：`platform`，规则前缀 `RULE-PLAT-`，断言前缀 `ASRT-PLAT-`
- 基线提交：`bf789d9e4fff51b7a2c0b661046f9e5c72b6e483`
- 需求依据：`requirements/modules/platform.md`（REQ-PLAT-001 ~ REQ-PLAT-008）
- 流程：`FLOW-PLAT`（启动与请求进入）。
- 断言被 `cases/platform.json` 的 `assertion_id` 引用。**断言只描述可判定的观察点**，不描述"应该更好"。
- 所有 `source` 均为 `完整相对路径:行号`。`basis=observed` 表示读源码/配置核实；本模块有 4 条 `confirmed`——它们的理由与适用条件写在代码注释或 `requirements/project-card.md` 的已确认决定里（D4 端口 8200、D5 NO_PROXY、D6 SECRET_KEY 校验、D10 CI 假密钥）。
- 功能单元：`FEAT-PLAT-001` ~ `FEAT-PLAT-008`，定义见 `### 1.4 功能单元`（ID → 用户视角的一句话 → 入口 → requirement_refs → source）。
- 待登记 ID（供汇总方补齐）：`FEAT-PLAT-001` ~ `FEAT-PLAT-008` 需写入 `specs/feature-index.json`；`REQ-PLAT-001` ~ `REQ-PLAT-008` 需写入 `requirements/index.json` 的 `requirements` 数组。两者当前尚不存在，**不是本文件能自证的**。

---

## 1. 交互与接口状态

### 1.1 启动入口清单（人 → 命令 → 监听点）

| 入口动作 | 命令/文件 | 监听与就绪判据 | source |
|---|---|---|---|
| 直接跑后端模块 | `python -m src.main` | `0.0.0.0:8200`，非生产 `reload=True` | `src/main.py:283-288` |
| uvicorn 直起 | `python -m uvicorn src.main:app --port 8200` | 同上，reload 由命令行决定 | `scripts/demo.sh:34-36` |
| 一键启动（Windows 主入口） | `python scripts\launch_demo.py up` | 依次拉 monitor 8104 / cls 8103 / rag 8105 / change 8106 / api 8200 / frontend 5273 | `scripts/launch_demo.py:44-64` |
| 一键启动菜单 | 双击 `start_demo.bat` | 菜单 6 项转调 `launch_demo.py` | `start_demo.bat:2` |
| 基础服务（兼容入口） | `启动基础服务.bat` | 转调 `launch_demo.py infra up\|stop\|status` | `启动基础服务.bat:16` |
| 前端开发服务器 | `npm run dev`（`frontend/`） | `127.0.0.1:5273`，`strictPort: true` | `frontend/vite.config.js:33-38` |
| 容器全栈 | `docker compose -f docker/docker-compose.yml up` | 宿主 `8200` → 容器 `8000` | `docker/docker-compose.yml:4-9`、`docker/Dockerfile:22-25` |
| 仅建表 | `python scripts/create_tables.py` | 打印 `Tables created.` | `scripts/create_tables.py:6-11` |

### 1.2 请求进入的中间件与处理器顺序

| 序 | 组件 | 作用点 | 可观察产物 | source |
|---|---|---|---|---|
| 1 | `SlowAPIMiddleware` | 全请求，实际配额仅登录端点 | 超限 429 | `src/main.py:200-202`、`src/api/routers/auth.py:62` |
| 2 | `security_headers_middleware` | 所有响应 | 4 个安全响应头 | `src/main.py:223-230` |
| 3 | `trace_id_middleware` | 所有响应 | `X-Trace-ID` | `src/main.py:233-243` |
| 4 | `CORSMiddleware` | 跨域预检与响应 | `Access-Control-Allow-Origin` | `src/main.py:214-220` |
| 5 | `TrustedHostMiddleware` | **仅 production** | 非法 Host → 400 | `src/main.py:205-211` |
| 6 | 11 组业务路由 | 业务 | 业务响应 | `src/main.py:255-265` |
| 7 | 全局 `Exception` 处理器 | 未捕获异常 | 500 固定中文 detail | `src/main.py:246-252` |

> 注：`add_middleware` 的**执行**顺序与注册顺序相反（Starlette 语义，最后注册的最先进入）。上表按"对请求的生效先后"排列，注册代码顺序见 source。这一语义本身不在本模块断言范围内。

### 1.3 启动期状态迁移

| 起点 | 触发 | 终点 | source |
|---|---|---|---|
| 进程启动 | `import src.main` 执行到模块级 `create_all` | 缺失的表被建出（已存在的表不动） | `src/main.py:31` |
| 表已存在 | `create_app()` 首行 `_validate_secrets()` | 通过则继续；不通过抛 `RuntimeError`（进程死） | `src/main.py:178` |
| 密钥通过 | `_migrate_schema()` | 缺列被 `ALTER TABLE` 补上；单列失败只 warning | `src/main.py:179,89-144` |
| 迁移结束 | 挂中间件 + 11 组路由 + `/metrics` | app 就绪 | `src/main.py:200-279` |
| app 就绪 | `uvicorn.run` | 监听 `0.0.0.0:8200` | `src/main.py:288` |
| 生产态 | `docs_url/redoc_url/openapi_url` 置 None | `/docs`、`/redoc`、`/openapi.json` 均 404 | `src/main.py:189-197` |

### 1.4 功能单元（FEAT-PLAT-*，供 `specs/feature-index.json` 与 cases 的 feature_id 解析）

本表把"用户视角的一件事"映射到已写好的需求条目，只做索引，不引入新事实。

| ID | 功能单元（用户视角） | 入口 | requirement_refs | source |
|---|---|---|---|---|
| FEAT-PLAT-001 | 配好 `.env` 后服务能起来；密钥不合格时进程立刻退出并打印中文原因 | `python -m src.main` / `uvicorn src.main:app` / `launch_demo.py up` | REQ-PLAT-001 | `src/main.py:47-61,177-179`、`scripts/launch_demo.py:258-277` |
| FEAT-PLAT-002 | 不用手跑迁移：首次启动就有可用的表结构，老库缺列会被自动补上 | 任意启动方式 | REQ-PLAT-002 | `src/main.py:31,89-144`、`src/database/sql_session.py:5-25` |
| FEAT-PLAT-003 | 改一处配置就能控制全系统行为，且能从 `.env.example` 对照出有哪些开关 | 编辑 `.env` / 只读审计 | REQ-PLAT-003 | `src/settings.py:8-367`、`scripts/audit_configuration.py:17-40` |
| FEAT-PLAT-004 | 该有的接口都能调到；调不到的就是真的没开 | 各业务页面的接口调用 | REQ-PLAT-004 | `src/main.py:255-265` |
| FEAT-PLAT-005 | 浏览器从 5273 能正常跨域调用，响应带安全头，一条请求能靠 trace 串起来 | 前端页面发请求 | REQ-PLAT-005 | `src/main.py:200-243` |
| FEAT-PLAT-006 | 接口出错时只看到一句中文提示，看不到堆栈；生产环境也没有调试文档入口 | 任意接口异常 | REQ-PLAT-006 | `src/main.py:189-197,246-252` |
| FEAT-PLAT-007 | 本机直接跑或一条 compose 起全栈都能用，宿主端口对齐 | `.venv` 直跑 / `docker compose up` | REQ-PLAT-007 | `src/main.py:283-288`、`docker/docker-compose.yml:4-9` |
| FEAT-PLAT-008 | 提交后自动跑离线测试，改坏了立刻能看到红 | git push / pull request | REQ-PLAT-008 | `.github/workflows/tests.yml:46-50`、`pytest.ini:12-13` |

---

## 2. 规则

### RULE-PLAT-001 SECRET_KEY 三项检查任一不过即启动失败
- **要求**：`_validate_secrets()` 必须按"空 → `.strip().lower()` 命中 6 个示例值 → 长度 < 32"的顺序检查，任一命中先 `logger.critical` 再 `raise RuntimeError`；六项黑名单为 `unsafe-secret-key`、`your-super-secret-key-change-it`、`your-secret-key`、`change-me`、`secret`、`changeit`。
- **适用条件**：每次 `create_app()`。因 `app = create_app()` 是模块级执行（`src/main.py:281`），`import src.main` 也会触发。
- **可观察**：进程以非零码退出，stderr/stdout 含 `SECRET_KEY 必须设置,不能为空` 或 `为已知不安全的示例值` 或 `长度必须 >= 32 字符`；`GET /health` 无响应（端口未监听）。
- **source**：`src/main.py:36-61,178,281`
- **requirement_refs**：REQ-PLAT-001　**basis**：confirmed（`requirements/project-card.md` D6 已记录该决定；`src/main.py:36-44` 常量与注释写明意图）

### RULE-PLAT-002 建表发生在密钥校验之前
- **要求**：`Base.metadata.create_all(bind=engine)` 必须位于模块导入期（`src/main.py:31`），早于 `create_app()` 内的 `_validate_secrets()`。
- **适用条件**：所有导入 `src.main` 的进程。
- **可观察**：用不合格的 `SECRET_KEY` 启动时，进程退出，但 `rag_system.db` 已被创建/表已被补齐——即"启动失败仍然留下数据库副作用"。
- **source**：`src/main.py:31,177-179`
- **requirement_refs**：REQ-PLAT-002　**basis**：observed

### RULE-PLAT-003 列迁移只做 ADD COLUMN，失败不阻断启动
- **要求**：`_migrate_schema()` 逐表逐列 diff，缺列拼 `ALTER TABLE "{table}" ADD COLUMN "{col}" {sql_type} DEFAULT {default}` 并即时 commit；**单列失败只 `logger.warning`，不得抛出**，也不得删列/改类型/改约束。
- **适用条件**：`inspect(engine)` 能取到该表；表不存在则跳过。
- **可观察**：新增模型字段后首次启动，日志出现 `[schema-migrate] {表}.{列} ({类型}) 已补齐`；人为让某列 ALTER 失败时启动仍成功，但该列仍缺失，后续对该表的 INSERT 报 500。
- **风险**：启动"成功"不等于结构完整（`src/main.py:143-144`）。
- **source**：`src/main.py:89-144`
- **requirement_refs**：REQ-PLAT-002　**basis**：observed

### RULE-PLAT-004 SQLite 连接强制 WAL 与 busy_timeout=10000
- **要求**：当 `DATABASE_URL` 含 `sqlite` 时，`create_engine` 必须带 `connect_args={"check_same_thread": False}`，且连接事件里执行 `PRAGMA journal_mode=WAL` 与 `PRAGMA busy_timeout=10000`；非 SQLite 时不得设置这些 PRAGMA。
- **适用条件**：每次新建连接。
- **可观察**：`PRAGMA journal_mode` 返回 `wal`；`PRAGMA busy_timeout` 返回 `10000`。
- **source**：`src/database/sql_session.py:5-21`
- **requirement_refs**：REQ-PLAT-002　**basis**：observed

### RULE-PLAT-005 开发态 CORS 白名单恒为 6 个源，且不含 5173
- **要求**：`APP_ENV != "production"` 时必须返回固定的 6 个 origin：`http://localhost:5273`、`http://127.0.0.1:5273`、`http://localhost:3000`、`http://127.0.0.1:3000`、`http://localhost:8080`、`http://127.0.0.1:8080`。不得读取 `ALLOWED_ORIGINS`。
- **适用条件**：开发/测试环境。
- **可观察**：以 `http://localhost:5273` 为 Origin 的跨域请求带 `Access-Control-Allow-Origin: http://localhost:5273`；以 `http://localhost:5173` 为 Origin 的**不带**该响应头。
- **已知不一致**：`README.md:147` 声称前端为 5173，与该白名单冲突。
- **source**：`src/main.py:64-87,214-220`、`README.md:147`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-006 生产态 ALLOWED_ORIGINS 为空即拒绝所有跨域
- **要求**：`APP_ENV == "production"` 时读 `ALLOWED_ORIGINS` 逗号切分；切分结果为空必须返回 `[]` 并打 warning，**不得**回退为 `["*"]` 或开发态列表。
- **适用条件**：仅 production。
- **可观察**：`_build_cors_origins()` 返回 `[]`；任意跨域请求无 `Access-Control-Allow-Origin`；服务端日志含 `生产环境未配置 ALLOWED_ORIGINS，CORS 将拒绝所有跨域请求`。
- **source**：`src/main.py:64-78`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-007 TrustedHostMiddleware 只在生产挂载
- **要求**：`TrustedHostMiddleware` 必须在 `is_prod` 为真时才 `add_middleware`；`ALLOWED_HOSTS` 逗号切分后为空则回退 `['*']`。
- **适用条件**：`create_app()`。
- **可观察**：开发态用任意 `Host` 头请求均不被拒；生产态且 `ALLOWED_HOSTS` 为具体域名时，非法 Host 返回 400。
- **source**：`src/main.py:205-211`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-008 每个响应都带 4 个安全头
- **要求**：所有响应（含 4xx/5xx）必须带 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`、`X-XSS-Protection: 1; mode=block`。
- **适用条件**：全部 HTTP 响应。
- **可观察**：`GET /api/v1/health/health` 与一个故意 404 的路径，响应头均含上述 4 项且值逐字相同。
- **source**：`src/main.py:223-230`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-009 每个响应都带 X-Trace-ID，且请求结束后 ContextVar 复位
- **要求**：`trace_id_middleware` 必须先 `set_trace_id()`（默认 `uuid4().hex[:12]`）写入 `request.state.trace_id`，响应头写 `X-Trace-ID`，并在 `finally` 里 `reset_trace_id()`。
- **适用条件**：全部 HTTP 响应。
- **可观察**：连续两次请求的 `X-Trace-ID` 不同，且长度 12；`X-Trace-ID` 与响应体/日志中的 trace 一致；请求结束后同进程再取 trace 为空串。
- **source**：`src/main.py:233-243`、`src/utils/tracing.py:27-34`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-010 生产关闭 /docs、/redoc、/openapi.json
- **要求**：`docs_url`、`redoc_url`、`openapi_url` 三个参数必须由同一个 `is_prod` 决定，生产态全部为 `None`。
- **适用条件**：`APP_ENV == "production"` 时创建 app。
- **可观察**：生产态 `GET /docs`、`GET /redoc`、`GET /openapi.json` 均 404；开发态三者均 200。
- **source**：`src/main.py:181,189-197`
- **requirement_refs**：REQ-PLAT-006　**basis**：observed

### RULE-PLAT-011 未捕获异常统一成 500 固定中文文案
- **要求**：`@app.exception_handler(Exception)` 必须先 `logger.error(..., exc_info=True)`，再返回 `status_code=500`、`content={"detail": "服务处理异常，请稍后重试"}`。响应体**不得**含异常类型、消息、堆栈或内网路径。
- **适用条件**：任何未被更具体处理器接管的异常。`HTTPException` 不在此列。
- **可观察**：制造一个未捕获异常（如让依赖抛 `ValueError` 而非 `HTTPException`）→ 500，body 恰为 `{"detail":"服务处理异常，请稍后重试"}`，且不含 `Traceback`；服务端日志有完整堆栈。
- **source**：`src/main.py:246-252`
- **requirement_refs**：REQ-PLAT-006　**basis**：observed

### RULE-PLAT-012 全仓唯一限流配额落在登录端点
- **要求**：`limiter = Limiter(key_func=get_remote_address)` 只允许一个实例；**全仓仅登录端点**可加 `@limiter.limit("5/minute")`，其它端点不得加限流装饰器。
- **适用条件**：所有端点注册。
- **可观察**：`grep` 结果只有 `src/api/routers/auth.py:62` 一处 `@limiter.limit`；对登录端点同一 IP 连续 6 次失败请求，第 6 次返回 **429**；对任意其它端点连续 10 次请求全部非 429。
- **source**：`src/utils/rate_limit.py:8-9`、`src/api/routers/auth.py:61-62`、`src/main.py:200-202`
- **requirement_refs**：REQ-PLAT-005　**basis**：observed

### RULE-PLAT-013 挂载 11 组路由，query 与 tasks 两支不可达
- **要求**：`create_app()` 必须恰好 `include_router` 11 次，前缀依次为 `/api/v1` 下的 `health`、`auth`、`knowledge-bases`、`assistants`、`agents`、`monitor`、`storage`、`chat`、`aiops`、`evaluations`、`upload`；`query.py` 与 `tasks.py` 不得挂载。
- **适用条件**：`create_app()`。
- **可观察**：`GET /api/v1/health/health` 200；`GET /api/v1/tasks/anything` 与 `GET /api/v1/query/anything` 均 **404**。
- **source**：`src/main.py:16,255-265`
- **requirement_refs**：REQ-PLAT-004　**basis**：observed

### RULE-PLAT-014 配置是单例，字段集与 .env.example 一一对应
- **要求**：`settings = Settings()` 必须在模块级唯一实例化；`Settings` 字段名集合与 `.env.example` 顶层键集合必须完全相等（无缺失、无多余、无重复）。
- **适用条件**：任何导入 `src.settings` 的进程。
- **可观察**：字段计数两边相同（本轮实测 **136 = 136**）；`tests/test_configuration_audit.py:92-99` 对该等式有显式断言；运行期修改环境变量对已导入的 `settings` 无效。
- **source**：`src/settings.py:360-367`、`tests/test_configuration_audit.py:92-99`
- **requirement_refs**：REQ-PLAT-003　**basis**：observed

### RULE-PLAT-015 五项配置在 src/ 内无任何消费方
- **要求**：`CHUNK_SIZE`、`CHUNK_OVERLAP`、`TOP_K`、`RAG_MIN_SCORE`、`LONG_TERM_MEMORY_COLLECTION` 在 `src/` 内除 `src/settings.py` 的定义处外必须无引用（死配置）。
- **适用条件**：静态检索。
- **可观察**：在这五项上分别 grep `src/`，命中行只出现在 `src/settings.py` 的定义行；改动它们的值不改变任何接口输出。
- **注意**：这与"默认关闭的能力开关"（`ENABLE_SUPERVISOR` 等）不是同一类——后者有消费方、只是默认 False。
- **source**：`src/settings.py:106-110,195`
- **requirement_refs**：REQ-PLAT-003　**basis**：observed

### RULE-PLAT-016 NO_PROXY 增量追加本机地址，不覆盖已有值
- **要求**：`src/settings.py` 导入时必须对 `NO_PROXY` 与 `no_proxy` 两个变量做**增量**追加 `127.0.0.1,localhost,::1`；已有值必须保留，已含该串时不得重复追加。
- **适用条件**：导入 `src.settings`。
- **可观察**：预设 `NO_PROXY=<既有值>` 后导入，`os.environ["NO_PROXY"]` 以既有值开头并含 `127.0.0.1,localhost,::1`；`no_proxy` 同步被设置；连续导入不产生重复片段。
- **source**：`src/settings.py:369-379`
- **requirement_refs**：REQ-PLAT-003　**basis**：confirmed（`src/settings.py:370-374` 注释写明理由：本机调试代理曾劫持本机 MCP 请求致 502；`requirements/project-card.md` D5 已确认）

### RULE-PLAT-017 导入配置即创建三个工作目录
- **要求**：`src/settings.py` 末尾必须用 `os.makedirs(..., exist_ok=True)` 创建 `UPLOAD_DIR`、`PROCESSED_DIR`、`VECTOR_DIR`。
- **适用条件**：导入 `src.settings`（即几乎任何入口）。
- **可观察**：删除三目录后执行任意 `import src.main`，三目录被重建；重复导入不报错。
- **source**：`src/settings.py:381-383`
- **requirement_refs**：REQ-PLAT-001　**basis**：observed

### RULE-PLAT-018 本机监听 8200，reload 只随非生产打开
- **要求**：`__main__` 分支必须 `uvicorn.run("src.main:app", host="0.0.0.0", port=8200, reload=is_dev)`，其中 `is_dev = settings.APP_ENV != "production"`。
- **适用条件**：仅 `python -m src.main` 这一走法。
- **可观察**：`APP_ENV=production python -m src.main` 时监听 8200 且进程不出现 reloader 子进程；开发态出现 reloader。
- **注意**：走 `python -m uvicorn src.main:app` 时本规则不生效，端口与 reload 由命令行决定（`scripts/demo.sh:35` 显式给 `--reload`）。
- **source**：`src/main.py:283-288`
- **requirement_refs**：REQ-PLAT-007　**basis**：confirmed（`src/main.py:285` 注释写明端口 8200 避开 Windows 保留段 7911-8010 否则 winerror 10013；`requirements/project-card.md` D4 已确认）

### RULE-PLAT-019 容器内 8000、宿主 8200，两处数字不同源
- **要求**：`docker/Dockerfile` 必须 `EXPOSE 8000` 且 CMD 监听 `--port 8000`；compose 必须映射 `8200:8000`。
- **适用条件**：容器部署路径。
- **可观察**：容器内 `curl 127.0.0.1:8000/docs` 200；宿主 `curl 127.0.0.1:8200/docs` 200；宿主 `curl 127.0.0.1:8000` 无监听。
- **风险**：改端口需三处同改（本机 8200、Dockerfile 8000、compose 映射），否则容器起得来但映射失效。
- **source**：`docker/Dockerfile:22-25`、`docker/docker-compose.yml:4-9`
- **requirement_refs**：REQ-PLAT-007　**basis**：observed

### RULE-PLAT-020 CI 先跑回放门禁再跑离线单测，且只注入假密钥
- **要求**：`offline-tests` workflow 必须按"checkout → setup-python 3.12 → 过滤重型依赖安装 → `pytest -q tests/test_recorded_round_replay.py` → `pytest -q -m "not integration"`"的顺序执行；环境里只允许出现占位假密钥，不得注入真实密钥。
- **适用条件**：push 到 main、pull_request、手动触发。
- **可观察**：workflow 步骤名恰为 `Decision-rule gate (recorded paid rounds must not regress)` 与 `Run offline unit tests`；第一步失败时第二步不执行；仓库内无真实密钥字面量。
- **source**：`.github/workflows/tests.yml:1-50`
- **requirement_refs**：REQ-PLAT-008　**basis**：confirmed（`requirements/project-card.md` D10 已确认；`.github/workflows/tests.yml:19` 注释写明"真实密钥永远不进 CI"）

### RULE-PLAT-021 本地裸跑 pytest 与 CI 同口径：默认跳过 integration
- **要求**：`pytest.ini` 必须 `testpaths = tests`、注册 `integration` marker、`addopts = -ra -m "not integration"`。
- **适用条件**：任何 `pytest` 调用。
- **可观察**：裸跑 `pytest` 不收集 `tests/test_health.py`（该文件有 `pytestmark = pytest.mark.integration`，`tests/test_health.py:29`）；`pytest -m integration` 才收集到它；无 `PytestUnknownMarkWarning`。
- **source**：`pytest.ini:1-13`、`tests/test_health.py:29`
- **requirement_refs**：REQ-PLAT-008　**basis**：observed

### RULE-PLAT-022 后端不托管前端产物
- **要求**：`src/main.py` 只允许 `app.mount("/metrics", ...)` 一个 mount，**不得**出现 `StaticFiles` 或对 `frontend/dist` 的挂载。
- **适用条件**：`create_app()`。
- **可观察**：`GET /` 与 `GET /assets/anything.js` 均 404；全仓 `StaticFiles` 命中为 0；前端只能经 5273（vite）或 nginx 容器访问。
- **source**：`src/main.py:147-174`、`frontend/vite.config.js:33-38`、`docker/docker-compose.yml:94-102`
- **requirement_refs**：REQ-PLAT-007　**basis**：observed

---

## 3. 断言

| ID | 断言（可判定） | 关联规则 | requirement_refs | basis |
|---|---|---|---|---|
| ASRT-PLAT-001 | 以**空** `SECRET_KEY` 启动 `python -m uvicorn src.main:app` 时进程退出码非 0，输出含 `SECRET_KEY 必须设置`，且 8200 无监听 | RULE-PLAT-001 | REQ-PLAT-001 | confirmed |
| ASRT-PLAT-002 | 用黑名单值（六个之一）作为 `SECRET_KEY` 启动 → 退出码非 0，输出含 `为已知不安全的示例值` | RULE-PLAT-001 | REQ-PLAT-001 | confirmed |
| ASRT-PLAT-003 | 用长度 31 的 `SECRET_KEY` 启动 → 退出码非 0，输出含 `长度必须 >= 32 字符`；换成 32 字符后进程正常监听 8200 | RULE-PLAT-001 | REQ-PLAT-001 | confirmed |
| ASRT-PLAT-004 | 删除 `rag_system.db` 后用**空** `SECRET_KEY` 启动，进程虽失败但 `rag_system.db` 文件已被重新创建（证明建表先于密钥校验） | RULE-PLAT-002 | REQ-PLAT-002 | observed |
| ASRT-PLAT-005 | 在一个已有旧结构的 SQLite 库上启动，缺失的列被补齐并在 stdout 出现至少一条 `[schema-migrate]` 记录；`PRAGMA table_info` 能看到该列 | RULE-PLAT-003 | REQ-PLAT-002 | observed |
| ASRT-PLAT-006 | 启动后对 `rag_system.db` 执行 `PRAGMA journal_mode` 返回 `wal`，`PRAGMA busy_timeout` 返回 `10000` | RULE-PLAT-004 | REQ-PLAT-002 | observed |
| ASRT-PLAT-007 | 开发态带 `Origin: http://localhost:5273` 的跨域请求响应含 `Access-Control-Allow-Origin: http://localhost:5273`；带 `Origin: http://localhost:5173` 的响应**不含**该头 | RULE-PLAT-005 | REQ-PLAT-005 | observed |
| ASRT-PLAT-008 | `APP_ENV=production` 且 `ALLOWED_ORIGINS` 为空时启动，`_build_cors_origins()` 返回 `[]`，日志含 `生产环境未配置 ALLOWED_ORIGINS`，任意跨域响应无 `Access-Control-Allow-Origin` | RULE-PLAT-006 | REQ-PLAT-005 | observed |
| ASRT-PLAT-009 | 开发态用 `Host: evil.example.com` 请求返回非 400；`APP_ENV=production` + `ALLOWED_HOSTS=127.0.0.1` 时同请求返回 **400** | RULE-PLAT-007 | REQ-PLAT-005 | observed |
| ASRT-PLAT-010 | 对 `GET /api/v1/health/health` 与一个不存在的路径，两者响应头逐字含 `X-Content-Type-Options: nosniff`、`X-Frame-Options: SAMEORIGIN`、`Referrer-Policy: strict-origin-when-cross-origin`、`X-XSS-Protection: 1; mode=block` | RULE-PLAT-008 | REQ-PLAT-005 | observed |
| ASRT-PLAT-011 | 连续两次 `GET /api/v1/health/health` 的 `X-Trace-ID` 不相等，且各为 12 位十六进制字符串 | RULE-PLAT-009 | REQ-PLAT-005 | observed |
| ASRT-PLAT-012 | `APP_ENV=production` 启动后 `GET /docs`、`GET /redoc`、`GET /openapi.json` 均 **404**；开发态三者均 200 | RULE-PLAT-010 | REQ-PLAT-006 | observed |
| ASRT-PLAT-013 | 制造未捕获异常后响应为 **500** 且 body 恰为 `{"detail":"服务处理异常，请稍后重试"}`，body 中不含 `Traceback`；同时 stdout/`logs/processing.log` 出现该异常的堆栈 | RULE-PLAT-011 | REQ-PLAT-006 | observed |
| ASRT-PLAT-014 | 对登录端点连续发起 6 次失败登录，第 6 次返回 **429**；对 `GET /api/v1/health/health` 连续 10 次全部 200（无 429） | RULE-PLAT-012 | REQ-PLAT-005 | observed |
| ASRT-PLAT-015 | `GET /api/v1/health/health` 返回 200；`GET /api/v1/tasks/1` 与 `GET /api/v1/query/1` 均 **404** | RULE-PLAT-013 | REQ-PLAT-004 | observed |
| ASRT-PLAT-016 | `scripts/audit_configuration.py` 输出的 `settings_field_count` 与 `.env.example` 顶层键计数相等（本轮实测 136）；`omitted_field_names`、`unknown_field_names`、`duplicate_field_names` 三者均为空 | RULE-PLAT-014 | REQ-PLAT-003 | observed |
| ASRT-PLAT-017 | 在 `src/` 内分别 grep 五个死配置名，命中行只出现在 `src/settings.py` 的定义行，无第三处 | RULE-PLAT-015 | REQ-PLAT-003 | observed |
| ASRT-PLAT-018 | 预设 `NO_PROXY` 为既有值后导入 `src.settings`，`os.environ["NO_PROXY"]` 以既有值开头并含 `127.0.0.1,localhost,::1`；`os.environ["no_proxy"]` 同样被设置 | RULE-PLAT-016 | REQ-PLAT-003 | confirmed |
| ASRT-PLAT-019 | 删除 `UPLOAD_DIR`/`PROCESSED_DIR`/`VECTOR_DIR` 后执行任意 `import src.main`，三目录被重新创建 | RULE-PLAT-017 | REQ-PLAT-001 | observed |
| ASRT-PLAT-020 | `APP_ENV=production python -m src.main` 监听 8200 且无 reloader 子进程；开发态出现 reloader | RULE-PLAT-018 | REQ-PLAT-007 | confirmed |
| ASRT-PLAT-021 | 容器内 `GET 127.0.0.1:8000/docs` 200，宿主 `GET 127.0.0.1:8200/docs` 200，宿主 8000 无监听 | RULE-PLAT-019 | REQ-PLAT-007 | observed |
| ASRT-PLAT-022 | `.github/workflows/tests.yml` 中先出现的 pytest 步骤名恰为 `Decision-rule gate (recorded paid rounds must not regress)` 且命令为 `tests/test_recorded_round_replay.py`，其后才是 `-m "not integration"` 的离线单测步骤 | RULE-PLAT-020 | REQ-PLAT-008 | confirmed |
| ASRT-PLAT-023 | 裸跑 `pytest --collect-only -q` 不收集 `tests/test_health.py` 的用例；`pytest -m integration --collect-only -q` 能收集到它；运行无 `PytestUnknownMarkWarning` | RULE-PLAT-021 | REQ-PLAT-008 | observed |
| ASRT-PLAT-024 | `GET /` 与 `GET /assets/app.js` 均 **404**；全仓 grep `StaticFiles` 命中 0 次 | RULE-PLAT-022 | REQ-PLAT-007 | observed |

---

## 4. 未决（供 `specs/questions.md` 汇总）

- **「8200 与 8000 要不要收敛」**：本机 8200（`src/main.py:288`）、容器内 8000（`docker/Dockerfile:25`）、compose 映射 `8200:8000`（`docker/docker-compose.yml:4-9`）三处数字。若定为"宿主恒 8200、容器内恒 8000"，需在资料里写死，避免下一个人只改一处。
- **「`/metrics` 生产是否关闭」**：文档三件套有 `is_prod` 开关，`/metrics` 没有，也没有注释解释。ASRT 目前只断言"装了就挂"，未断言生产可见性。
- **「启动失败是否应清理已建的库」**：RULE-PLAT-002 的副作用（失败仍建表）是现状；要不要改成先校验后建表，属设计决定，本轮不判优劣。
- **「端口占用检测该不该阻断」**：`scripts/launch_demo.py:299-309` 只打印不退出，会产生"部分服务在跑"的状态。是否算缺陷需产品口径。
- **「前端测试要不要进 CI」**：前端 18 个 `*.test.js` 只在本地 `npm test` 跑（`frontend/package.json:6-11`），CI 只跑 Python。是否需要独立前端 job `unresolved`。
- **「`_migrate_schema` 失败可观测性」**：单列失败仅 warning，启动成功但结构不全。是否需要在启动末尾加结构自检 `unresolved`。
- **「根级多份 .env 变体」**：`.env.agent-test`、`.env.aliyun-agent-test`、`.env.deepseek-agent-test`、`.env.deepseek-test` 与 `.env` 的加载关系本轮未核实；资料不引用其内容。
