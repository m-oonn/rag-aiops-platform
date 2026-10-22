FROM python:3.12-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir fastmcp==2.14.5 mcp==1.26.0
RUN useradd --uid 65532 --no-create-home --shell /usr/sbin/nologin diagnostic
COPY mcp_servers/diagnostic_server.py /app/diagnostic_server.py

# 容器默认不开放自动执行；启用前必须由部署方补齐隔离策略和目标数据挂载。
ENV DIAGNOSTIC_EXEC_ENABLED=false
ENV DIAGNOSTIC_HOST=0.0.0.0
USER 65532:65532
CMD ["python", "/app/diagnostic_server.py"]
