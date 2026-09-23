from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from src.settings import settings

_is_sqlite = "sqlite" in settings.DATABASE_URL

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if _is_sqlite else {}
)


if _is_sqlite:
    # 多进程(Celery worker + API)并发写同一 SQLite 时,WAL + busy_timeout 降低
    # "database is locked" 概率;worker 侧保持单进程单任务,顺序消费。
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
