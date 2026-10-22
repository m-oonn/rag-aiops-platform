FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    fastapi==0.128.0 uvicorn==0.49.0 fastmcp==2.14.5 \
    'sqlalchemy>=2.0.25' 'pydantic-settings>=2.0.0' loguru==0.7.3
COPY mcp_servers /app/mcp_servers
COPY src /app/src
CMD ["python", "-m", "uvicorn", "mcp_servers.probe_gateway:app", "--host", "0.0.0.0", "--port", "18767"]
