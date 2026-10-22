from src.settings import Settings


def test_probe_tls_verify_is_forwarded_to_streamable_http_client():
    cfg = Settings(
        SECRET_KEY="test-secret",
        PROBE_ENABLED=True,
        PROBE_TOKEN="probe-token",
        MCP_PROBE_URL="https://probe-gateway.example/mcp",
        PROBE_TLS_VERIFY=False,
    ).MCP_SERVERS["probe"]

    assert cfg["headers"]["Authorization"] == "Bearer probe-token"
    assert 'session_kwargs' not in cfg
    from src.agent import mcp_client
    from unittest.mock import patch
    connection = mcp_client._client_connections({'probe': cfg})['probe']
    assert 'tls_verify' not in connection
    with patch.object(mcp_client.httpx, 'AsyncClient') as constructor:
        connection['httpx_client_factory'](headers={'X-Test': 'yes'})
    assert constructor.call_args.kwargs['verify'] is False
    assert constructor.call_args.kwargs['headers'] == {'X-Test': 'yes'}


def test_mcp_cache_key_does_not_expose_tokens():
    from src.agent.mcp_client import _tools_config_key
    first = _tools_config_key({'probe': {'headers': {'Authorization': 'Bearer never-log-me'}}})
    assert len(first) == 64 and 'never-log-me' not in first
    assert first != _tools_config_key({'probe': {'headers': {'Authorization': 'Bearer changed'}}})
