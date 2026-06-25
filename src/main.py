import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.settings import settings
from src.api.routers import loadfile, query, health, auth, knowledge_base, chat, evaluation, assistant, agent, monitor, storage
from src.database.sql_session import engine, Base

# Create Tables
Base.metadata.create_all(bind=engine)

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="RAG System for PDF Documents"
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
    app.include_router(evaluation.router, prefix=settings.API_PREFIX + "/evaluations", tags=["Evaluation"])
    app.include_router(loadfile.router, prefix=settings.API_PREFIX + "/upload", tags=["File Management"]) # Legacy

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
