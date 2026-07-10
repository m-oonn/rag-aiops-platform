import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from src.settings import settings
from src.api.routers import loadfile, query, health, auth, knowledge_base, chat, evaluation, assistant, agent, monitor, storage, aiops
from src.database.sql_session import engine, Base
from src.utils.logger import logger
from src.utils.tracing import set_trace_id, reset_trace_id
from src.utils.rate_limit import limiter  # 安全最佳实践: 速率限制器

# Create Tables
Base.metadata.create_all(bind=engine)


# 安全最佳实践: 已知不安全的占位符/示例密钥黑名单,禁止用于生产
# 覆盖 .env.example 里的示例值,防止照搬示例即可伪造任意用户 token
_INSECURE_SECRET_KEYS = frozenset({
    "unsafe-secret-key",
    "your-super-secret-key-change-it",  # .env.example 的占位符
    "your-secret-key",
    "change-me",
    "secret",
    "changeit",
})
_MIN_SECRET_KEY_LENGTH = 32


def _validate_secrets() -> None:
    if not settings.SECRET_KEY:
        logger.critical("SECRET_KEY 未设置!请在 .env 中填入 SECRET_KEY=<强随机字符串>")
        raise RuntimeError("SECRET_KEY 必须设置,不能为空")
    if settings.SECRET_KEY.strip().lower() in _INSECURE_SECRET_KEYS:
        logger.critical("SECRET_KEY 仍为不安全的占位符/示例值!请填入强随机字符串")
        raise RuntimeError(
            "SECRET_KEY 为已知不安全的示例值,请改为强随机字符串"
            "(可用 `python -c \"import secrets; print(secrets.token_urlsafe(48))\"` 生成)"
        )
    if len(settings.SECRET_KEY) < _MIN_SECRET_KEY_LENGTH:
        logger.critical("SECRET_KEY 长度不足,存在被暴力破解风险")
        raise RuntimeError(
            f"SECRET_KEY 长度必须 >= {_MIN_SECRET_KEY_LENGTH} 字符,当前仅 {len(settings.SECRET_KEY)} 字符"
        )


def _build_cors_origins() -> list[str]:
    """安全最佳实践: CORS origins 配置。

    生产环境: 从 ALLOWED_ORIGINS 读取显式域名列表，不允许通配。
    开发环境: 允许 localhost 常见端口，不使用 "*" + credentials。
    """
    if settings.APP_ENV == "production":
        # 生产环境从配置读取显式 origins
        allowed = getattr(settings, 'ALLOWED_ORIGINS', '')
        if allowed:
            origins = [o.strip() for o in allowed.split(',') if o.strip()]
            if origins:
                return origins
        logger.warning("生产环境未配置 ALLOWED_ORIGINS，CORS 将拒绝所有跨域请求")
        return []  # 空列表，拒绝所有跨域
    # 开发环境: 显式允许 localhost 常见端口，不用 "*"
    return [
        "http://localhost:5273",
        "http://127.0.0.1:5273",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

def _migrate_schema() -> None:
    """检测已有表是否缺少 Model 定义的列，缺则 ALTER TABLE 补齐。

    Base.metadata.create_all() 只建新表、不改旧表；
    模型新增列后 SQLite 不会自动迁移，导致 INSERT 500。
    此函数在启动时做列级 diff + ALTER，保证 schema 与模型一致。
    """
    from sqlalchemy import inspect, text

    _TYPE_MAP = {
        "INTEGER": "INTEGER",
        "SMALLINT": "INTEGER",
        "BIGINT": "INTEGER",
        "VARCHAR": "VARCHAR",
        "TEXT": "TEXT",
        "BOOLEAN": "BOOLEAN",
        "FLOAT": "FLOAT",
        "JSON": "JSON",
        "DATETIME": "DATETIME",
    }

    def _sql_type(col):
        compiled = col.type.compile(dialect=engine.dialect)
        upper = compiled.upper() if compiled else "TEXT"
        for key, val in _TYPE_MAP.items():
            if key in upper:
                return val
        return "TEXT"

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    sql_type = _sql_type(col)
                    default = "NULL"
                    if col.default is not None and hasattr(col.default, "arg"):
                        arg = col.default.arg
                        if isinstance(arg, bool):
                            default = "1" if arg else "0"
                        elif isinstance(arg, (int, float)):
                            default = str(arg)
                        elif isinstance(arg, str):
                            default = f"'{arg}'"
                    stmt = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {sql_type} DEFAULT {default}'
                    try:
                        conn.execute(text(stmt))
                        conn.commit()
                        logger.info(f"[schema-migrate] {table.name}.{col.name} ({sql_type}) 已补齐")
                    except Exception as e:
                        logger.warning(f"[schema-migrate] ALTER {table.name}.{col.name} 失败: {e}")


def create_app() -> FastAPI:
    _validate_secrets()
    _migrate_schema()
    # 安全最佳实践: 生产环境禁用 /docs、/redoc、/openapi.json
    is_prod = settings.APP_ENV == "production"
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="RAG System for PDF Documents",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # 安全最佳实践: 注册速率限制器，防止暴力破解
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # 安全最佳实践: TrustedHostMiddleware 防止 Host 头注入
    if is_prod:
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', '*')
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[h.strip() for h in allowed_hosts.split(',') if h.strip()] or ['*'],
        )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 安全最佳实践: 添加安全响应头 (F-04)
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response

    # Trace ID 注入:每个请求分配唯一 trace_id,记录到结构化日志
    @app.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        tid = set_trace_id()
        request.state.trace_id = tid
        logger.bind(trace_id=tid).debug("[{}] {} {}", tid, request.method, request.url.path)
        try:
            response = await call_next(request)
            response.headers["X-Trace-ID"] = tid
            return response
        finally:
            reset_trace_id()

    # 全局异常处理:防止未捕获的异常返回英文堆栈给前端
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("未捕获异常: %s %s", request.url, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "服务处理异常，请稍后重试"},
        )

    # Routers
    app.include_router(health.router, prefix=settings.API_PREFIX + "/health", tags=["Health"])
    app.include_router(auth.router, prefix=settings.API_PREFIX + "/auth", tags=["Auth"])
    app.include_router(knowledge_base.router, prefix=settings.API_PREFIX + "/knowledge-bases", tags=["Knowledge Base"])
    app.include_router(assistant.router, prefix=settings.API_PREFIX + "/assistants", tags=["Assistant"])
    app.include_router(agent.router, prefix=settings.API_PREFIX + "/agents", tags=["Agent"])
    app.include_router(monitor.router, prefix=settings.API_PREFIX + "/monitor", tags=["Monitor"])
    app.include_router(storage.router, prefix=settings.API_PREFIX + "/storage", tags=["MinIO Storage"])
    app.include_router(chat.router, prefix=settings.API_PREFIX + "/chat", tags=["RAG Chat"])
    app.include_router(aiops.router, prefix=settings.API_PREFIX + "/aiops", tags=["AIOps Agent"])
    app.include_router(evaluation.router, prefix=settings.API_PREFIX + "/evaluations", tags=["Evaluation"])
    app.include_router(loadfile.router, prefix=settings.API_PREFIX + "/upload", tags=["File Management"]) # Legacy

    # RAG MCP Server: 使用独立进程模式（同 monitor/cls server），不在此挂载
    # 独立进程: python mcp_servers/rag_server.py (端口 8105)
    # 如需同进程模式，取消下面的注释:
    # try:
    #     from mcp_servers.rag_server import create_rag_mcp_app
    #     rag_mcp_app = create_rag_mcp_app()
    #     app.mount("/mcp/rag", rag_mcp_app)
    #     logger.info("RAG MCP Server 已挂载到 /mcp/rag")
    # except Exception as e:
    #     logger.warning("RAG MCP Server 挂载失败: %s", e)

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    # 端口 8200 避开 Windows 保留段 7911-8010(Hyper-V/WSL 占用,否则 winerror 10013)
    # 安全最佳实践: 生产环境不应开启热重载(与项目统一用 APP_ENV 判定环境)
    is_dev = settings.APP_ENV != "production"
    uvicorn.run("src.main:app", host="0.0.0.0", port=8200, reload=is_dev)
