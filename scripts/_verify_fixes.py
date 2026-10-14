"""临时验证(2026-10-10): 用真实代码路径确认两处修复生效。

  1) embedding: get_embedding_service().embed_query 不再欠费,维度 = MILVUS_DIMENSION
  2) 结构化输出: ainvoke_structured(create_agent_llm(), ...) 走原生 function calling,
     不再出现 "[structured] function_calling 失败,降级" 告警
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.environ["NO_PROXY"] = os.environ.get("NO_PROXY", "") + ",aliyuncs.com,dashscope.aliyuncs.com,deepseek.com"

from langchain_core.prompts import ChatPromptTemplate  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from src.agent.aiops_llm import create_agent_llm  # noqa: E402
from src.agent.aiops.structured import ainvoke_structured  # noqa: E402
from src.embedding import get_embedding_service  # noqa: E402
from src.models.vector import SearchResult  # noqa: E402
from src.retrieval.reranker import DashScopeReranker  # noqa: E402
from src.settings import settings  # noqa: E402


class Plan(BaseModel):
    """诊断计划。"""
    steps: list[str] = Field(description="诊断步骤列表")


_fallback_hit = {"v": False}


class _FallbackWatcher(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if "function_calling 失败" in record.getMessage():
            _fallback_hit["v"] = True


def check_embedding() -> None:
    print("== embedding ==")
    print(f"  EMBEDDING_MODEL={settings.EMBEDDING_MODEL} MILVUS_DIMENSION={settings.MILVUS_DIMENSION}")
    try:
        vec = get_embedding_service().embed_query("订单服务内存偏高如何排查")
        print(f"  [{'OK' if len(vec) == settings.MILVUS_DIMENSION else 'FAIL'}] "
              f"embed_query dim={len(vec)} (期望 {settings.MILVUS_DIMENSION})")
    except Exception as e:
        print(f"  [FAIL] embed_query {type(e).__name__}: {str(e)[:160]}")


def check_rerank() -> None:
    print("== rerank (真实 DashScopeReranker) ==")
    print(f"  RERANK_MODEL={settings.RERANK_MODEL} ENABLE_RERANK={settings.ENABLE_RERANK}")
    docs = [
        SearchResult(id="1", text="内存溢出导致 OOM,进程被 kill", score=0.0, metadata={}),
        SearchResult(id="2", text="网络连接超时,端口不可达", score=0.0, metadata={}),
        SearchResult(id="3", text="磁盘写满,日志无法落盘", score=0.0, metadata={}),
    ]
    try:
        out = DashScopeReranker().rerank("内存溢出如何排查", docs)
        top = out[0].text if out else "(空)"
        print(f"  [{'OK' if out else 'FAIL'}] rerank 返回 {len(out)} 条, top1={top}")
    except Exception as e:
        print(f"  [FAIL] rerank {type(e).__name__}: {str(e)[:160]}")


async def check_structured() -> None:
    print("== 结构化输出 (真实 ainvoke_structured) ==")
    logging.getLogger().addHandler(_FallbackWatcher())
    llm = create_agent_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是运维诊断规划器,请给出诊断步骤。"),
        ("human", "目标: {query}"),
    ])
    try:
        plan = await ainvoke_structured(llm, Plan, prompt, {"query": "检查订单服务内存是否偏高"})
        print(f"  [OK] 得到 {len(plan.steps)} 步计划,首步: {plan.steps[0][:60]}")
    except Exception as e:
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:160]}")
    print(f"  [{'FAIL' if _fallback_hit['v'] else 'OK'}] "
          f"{'命中了降级(原生 FC 仍失败)' if _fallback_hit['v'] else '未触发降级 → 原生 function calling 生效'}")


async def main() -> None:
    check_embedding()
    check_rerank()
    await check_structured()


if __name__ == "__main__":
    asyncio.run(main())