import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 测试使用内存数据库，避免污染开发数据库
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker, Session

from src.database.sql_session import Base, get_db
from src.database.models import User
from src.utils.security import get_password_hash
from src.main import app

# 安全最佳实践: 测试环境禁用速率限制
# patch _check_request_limit 设置 view_rate_limit 但不执行限制检查
from src.utils.rate_limit import limiter as _limiter
from slowapi import Limiter

def _noop_check_request_limit(self, request, func, *args, **kwargs):
    # 设置 view_rate_limit 供 SlowAPIMiddleware 响应阶段使用
    if not hasattr(request.state, 'view_rate_limit'):
        request.state.view_rate_limit = {}

Limiter._check_request_limit = _noop_check_request_limit


async def _fake_aiops_execute(user_input: str, session_id: str = "default"):
    """AIOps 诊断服务的快速假实现，避免测试中调用真实 LLM。"""
    yield {"type": "plan", "stage": "plan_created", "message": "test plan", "plan": []}
    yield {"type": "step_complete", "stage": "step_executed", "message": "step done"}
    yield {"type": "report", "stage": "final_report", "message": "report", "report": "ok"}
    yield {"type": "complete", "stage": "complete", "message": "done", "response": "ok"}


@pytest.fixture(scope="session", autouse=True)
def mock_aiops_service():
    """全局 mock AIOps 诊断服务，防止测试时消耗真实 LLM token。"""
    with patch("src.agent.aiops.aiops_service.execute", _fake_aiops_execute):
        yield


@pytest.fixture(scope="session", autouse=True)
def mock_process_document_task():
    """全局 mock 文档处理 Celery 任务，避免测试中连接 broker 或执行长耗时解析。"""
    fake_task = MagicMock()
    fake_task.delay.return_value = MagicMock(id="fake-task-id")
    with patch("src.api.routers.knowledge_base.process_document_task", fake_task):
        yield


@pytest.fixture(scope="session", autouse=True)
def run_background_tasks_synchronously():
    """让 FastAPI BackgroundTasks 在测试环境中同步执行，避免 response 返回后还在操作已被清空的内存数据库。"""
    original_add_task = None

    def sync_add_task(self, func, *args, **kwargs):
        func(*args, **kwargs)

    with patch("starlette.background.BackgroundTasks.add_task", sync_add_task):
        yield


@pytest.fixture(scope="session", autouse=True)
def mock_qa_generator():
    """全局 mock 评估数据集生成器，避免测试中调用真实 LLM。"""
    def fake_generate(text, count, qa_type):
        return [{"question": f"Q-{qa_type}-{i}", "answer": f"A-{qa_type}-{i}"} for i in range(count)]

    with patch("src.api.routers.evaluation.qa_generator.generate_qa_pairs", fake_generate):
        yield


@pytest.fixture(scope="session")
def engine():
    """创建内存数据库引擎，并在会话结束时清理。"""
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(engine):
    """每个测试函数使用独立的数据库会话。"""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function", autouse=True)
def clean_tables(engine):
    """每个测试结束后清空所有业务表，避免测试数据互相污染。"""
    yield
    from sqlalchemy import text
    with engine.connect() as conn:
        # 临时关闭 SQLite 外键约束以便按任意顺序清空
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))
        conn.execute(text("PRAGMA foreign_keys = ON"))
        conn.commit()


@pytest.fixture(scope="function")
def client(db):
    """返回已挂载测试数据库的 TestClient。"""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_user(db: Session):
    """创建一个测试用户。"""
    user = User(
        username="testuser",
        email="test@example.com",
        password_hash=get_password_hash("testpass"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="function")
def auth_token(client, test_user):
    """获取测试用户的 access token。"""
    response = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": "testuser", "password": "testpass"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="function")
def auth_headers(auth_token):
    """返回带认证头的请求头。"""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="function")
def other_user(db: Session):
    """创建一个属于其他用户的测试用户，用于权限校验。"""
    user = User(
        username="otheruser",
        email="other@example.com",
        password_hash=get_password_hash("otherpass"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
