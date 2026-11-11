"""`/health/dependencies` 对现场取证能力的声明。

诊断页要能在**花钱之前**判断"这次能不能拿到主机侧现场证据"。判据只有一条：
`PROBE_ENABLED` 打开且 Probe 可达时，依赖清单里才有 `probe` 项。本文件锁住这条
约定，避免以后有人把 `probe` 无条件塞进清单（会让没启用 Probe 的部署显示"正常"），
或把它漏掉（前端就又会退回到"点了才知道没有证据"）。
"""
import pytest

from src.api.routers import health


async def _ok(*args, **kwargs):
    return {"status": "ok", "error": None}


async def _down(*args, **kwargs):
    return {"status": "unavailable", "error": "connection refused"}


@pytest.fixture
def patched_checks(monkeypatch):
    """把七项原始检查全部换成可控桩，避免测试真的去连 Milvus/MinIO。"""
    monkeypatch.setattr(health, "_check_http", _ok)
    monkeypatch.setattr(health, "_check_rabbitmq", _ok)
    monkeypatch.setattr(health, "_check_redis", _ok)
    monkeypatch.setattr(health, "_check_milvus", _ok)
    monkeypatch.setattr(health, "_check_minio", _ok)
    monkeypatch.setattr(health, "_check_llm", _ok)
    monkeypatch.setattr(health, "_check_probe", _ok)
    # 每个用例都从"没有缓存"开始，否则上一个用例的结果会被 TTL 缓存带过来
    monkeypatch.setattr(health, "_DEPS_CACHE", {"at": 0.0, "payload": None})
    return monkeypatch


@pytest.mark.asyncio
async def test_probe_absent_when_feature_disabled(patched_checks):
    """PROBE_ENABLED 关闭时不应声明 probe：此时诊断链路根本没有注册该工具。"""
    patched_checks.setattr(health.settings, "PROBE_ENABLED", False)

    data = await health.check_dependencies(current_user=object())

    assert "probe" not in data["services"]
    assert data["overall"] == "ok"


@pytest.mark.asyncio
async def test_probe_listed_when_feature_enabled(patched_checks):
    patched_checks.setattr(health.settings, "PROBE_ENABLED", True)

    data = await health.check_dependencies(current_user=object())

    assert data["services"]["probe"] == {"status": "ok", "error": None}
    assert data["overall"] == "ok"


@pytest.mark.asyncio
async def test_unreachable_probe_makes_overall_degraded(patched_checks):
    """启用但不可达必须体现为 degraded，否则前端会误判"现场证据可用"。"""
    patched_checks.setattr(health.settings, "PROBE_ENABLED", True)
    patched_checks.setattr(health, "_check_probe", _down)

    data = await health.check_dependencies(current_user=object())

    assert data["services"]["probe"]["status"] == "unavailable"
    assert data["overall"] == "degraded"


@pytest.mark.asyncio
async def test_repeated_check_within_ttl_reuses_the_last_result(patched_checks):
    """状态面板整表刷新时不重复建连接：TTL 内直接复用上一次结果。"""
    patched_checks.setattr(health.settings, "PROBE_ENABLED", False)
    first = await health.check_dependencies(current_user=object())

    # 第二次调用前把底层探活改成"全挂"，若仍在 TTL 内，结果不应改变
    patched_checks.setattr(health, "_check_redis", _down)
    second = await health.check_dependencies(current_user=object())

    assert second == first
    assert second["services"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_expired_cache_reruns_the_checks(patched_checks):
    """过了 TTL 必须重探，否则恢复/新增的故障最多要等一个 TTL 才被看见。"""
    patched_checks.setattr(health.settings, "PROBE_ENABLED", False)
    await health.check_dependencies(current_user=object())

    health._DEPS_CACHE["at"] = health.time.monotonic() - (health._DEPS_TTL_SECONDS + 1)
    patched_checks.setattr(health, "_check_redis", _down)

    data = await health.check_dependencies(current_user=object())

    assert data["services"]["redis"]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_probe_check_probes_health_not_mcp_endpoint(monkeypatch):
    """/health 探针不能去初始化 MCP 会话：可用性判断不该产生会话副作用。"""
    seen = {}

    class _Resp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, **kwargs):
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(health.aiohttp, "ClientSession", _Session)
    monkeypatch.setattr(health.settings, "MCP_PROBE_URL", "http://127.0.0.1:18767/mcp")

    result = await health._check_probe()

    assert result["status"] == "ok"
    assert seen["url"] == "http://127.0.0.1:18767/health"