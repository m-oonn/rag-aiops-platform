FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.128.0 uvicorn==0.49.0 httpx==0.28.1
COPY mcp_servers/termcp_gateway.py /app/termcp_gateway.py
USER 1000:1000
CMD ["python", "-m", "uvicorn", "termcp_gateway:app", "--host", "0.0.0.0", "--port", "18766"]
