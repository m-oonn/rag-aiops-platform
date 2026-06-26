#!/bin/bash
# Start Docker daemon + Milvus stack in WSL
set -e
sudo dockerd > /tmp/dockerd.log 2>&1 &
echo "Waiting for dockerd..."
for i in $(seq 1 15); do
    sleep 2
    docker info >/dev/null 2>&1 && break
done
echo "dockerd ready"

cd /mnt/d/ragPdfSystem++agent
docker rm -f milvus-standalone milvus-etcd milvus-minio 2>/dev/null || true
docker compose -f docker/docker-compose.yml up -d etcd minio milvus-standalone

echo "Waiting for Milvus..."
for i in $(seq 1 40); do
    sleep 3
    docker ps --format "{{.Names}}" | grep -q milvus-standalone && break
done
docker ps --format "table {{.Names}}\t{{.Status}}"
echo "Done. Keeping session alive..."
tail -f /dev/null
