"""请求级追踪工具。

使用 contextvars 在工作线程 / 协程间隔离 trace_id，
日志通过 loguru 的 bind() 注入，在日志文件/控制台中可过滤归组。

用法:
  from src.utils.tracing import get_trace_id, trace_span

  async def handler():
      with trace_span("handler"):
          await do_work()
          loguru.logger.info("something happened")  # 自动附带 trace_id
"""

import time
from contextvars import ContextVar
from typing import AsyncIterator, Optional
from uuid import uuid4

from loguru import logger as _logger

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_depth_var: ContextVar[int] = ContextVar("trace_depth", default=0)


def get_trace_id() -> str:
    return trace_id_var.get()


def set_trace_id(tid: Optional[str] = None) -> str:
    tid = tid or uuid4().hex[:12]
    trace_id_var.set(tid)
    return tid


def reset_trace_id() -> None:
    trace_id_var.set("")


class trace_span:
    """异步上下文管理器，记录 span 的开始、结束和耗时。

    日志通过 loguru 的 bind(trace_id=..., span=...) 结构化输出，
    自动嵌套缩进显示调用深度。
    """

    def __init__(self, name: str, **extra):
        self.name = name
        self.extra = extra

    async def __aenter__(self) -> "trace_span":
        depth = _depth_var.get()
        _depth_var.set(depth + 1)
        self._depth = depth
        self._start = time.monotonic()
        tid = get_trace_id()
        _logger.bind(trace_id=tid, span=self.name, depth=depth).debug(
            "[{}{}] 开始", "  " * depth, self.name
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        elapsed = time.monotonic() - self._start
        tid = get_trace_id()
        depth = _depth_var.get() - 1
        _depth_var.set(max(depth, 0))
        level = "error" if exc_info and exc_info[0] else "debug"
        getattr(_logger.bind(trace_id=tid, span=self.name, depth=depth), level)(
            "[{}{}] 结束 ({:.0f}ms)",
            "  " * depth,
            self.name,
            elapsed * 1000,
        )
