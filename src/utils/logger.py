import re
import sys

from loguru import logger as _loguru_logger

# ---------------------------------------------------------------------------
# loguru <-> stdlib logging 兼容层
# ---------------------------------------------------------------------------
# 项目内大量调用沿用 stdlib logging 的惰性占位风格：logger.info("...%s...", arg)。
# loguru 只认 "{}" 风格，且（与 stdlib 不同）不会对多余位置参数报错，而是**静默
# 丢弃** —— 于是日志输出字面 "%s"、参数丢失，损害可观测性与排查效率。
# 此适配层在保留 loguru "{}" 原生风格的前提下，对 "%" 风格调用做惰性格式化，
# 消除该静默缺陷。未知方法（remove/add/bind/opt/patch/...）原样透传给 loguru。
_PCT_PLACEHOLDER = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa%]")

_FMT_LEVELS = (
    "trace", "debug", "info", "success", "warning", "error", "critical", "exception",
)


class _CompatLogger:
    """包装 loguru logger，兼容 stdlib logging 的惰性 %-格式化调用。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        # 包一层后调用栈多了一帧，需把 depth 调回真实调用点；否则日志的
        # {function}/{line}/{name} 会指向本适配层，丢失来源定位能力。
        self._inner_d1 = inner.opt(depth=1)

    @staticmethod
    def _format(message, args):
        """若 message 使用 %-占位且 args 匹配，则惰性格式化；否则原样返回。"""
        if args and isinstance(message, str) and _PCT_PLACEHOLDER.search(message):
            try:
                return message % args, ()
            except (TypeError, ValueError):
                return message, args
        return message, args

    def __getattr__(self, name):
        if name in _FMT_LEVELS:
            attr = getattr(self._inner_d1, name)

            def _emit(message, *args, **kwargs):
                msg, rest = self._format(message, args)
                return attr(msg, *rest, **kwargs)
            return _emit
        if name == "log":
            attr = getattr(self._inner_d1, "log")

            def _log(level, message, *args, **kwargs):
                msg, rest = self._format(message, args)
                return attr(level, msg, *rest, **kwargs)
            return _log
        return getattr(self._inner, name)


logger = _CompatLogger(_loguru_logger)

# Configure Loguru
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
logger.add(
    "logs/processing.log",
    rotation="10 MB",
    retention="1 week",
    level="INFO"
)
