import asyncio
from types import SimpleNamespace

import pytest

from src.api.routers.aiops import AIOpsRequest, diagnose_stream


@pytest.mark.asyncio
async def test_leaving_sse_keeps_diagnosis_running_once(monkeypatch):
    release, completed = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)
        yield {'type': 'status', 'thread_id': 'owned-run'}
        await release.wait()
        completed.set()
        yield {'type': 'complete', 'thread_id': 'owned-run'}

    monkeypatch.setattr('src.api.routers.aiops.aiops_service.execute', execute)
    response = await diagnose_stream(AIOpsRequest(query='商城商品打不开'), SimpleNamespace(id=7))
    stream = response.body_iterator
    assert 'owned-run' in (await anext(stream))['data']
    try:
        await stream.aclose()
    except RuntimeError:
        pass  # The old generator also tried to yield usage during GeneratorExit.
    release.set()
    await asyncio.wait_for(completed.wait(), timeout=0.5)
    assert len(calls) == 1
