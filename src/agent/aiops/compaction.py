"""诊断历史压缩器（B2a——借鉴 pi 结构化 Compaction 的预算触发设计）。

现状（executor._run_step 历史注入，2026-09-23 少 tokens 优化）:
  最近 5 步 × 每步结果截 150 字——超过 5 步的旧步骤**整体丢弃**。

问题: 旧步骤里可能含"已排除方向 / 关键标识符 / 遗留问题"等全局信息,
一步丢干净会让长诊断（步数上限 12）在尾部阶段丢失前情。

本模块提供**预算触发式压缩**（对齐 pi 的 keepRecentTokens + 摘要化思路）:
  - 步数 ≤ 阈值(keep_recent+2): 维持旧口径，零行为变化;
  - 步数 > 阈值: 旧步骤压成一行式摘要（步骤名 + 结果首 N 字），
    最近 keep_recent 步保留更长的详情——保"全局骨架"而非只留尾部。

开关: settings.ENABLE_CONTEXT_COMPACTION（默认 False=旧行为）；
由调用方通过 enabled 参数传入（纯函数，便于测试与消融）。
"""

from typing import List, Sequence, Tuple

# 旧口径常量（与迁移前 executor 内部常量一致）
_LEGACY_RECENT = 5
_LEGACY_CHARS = 150

# 压缩口径默认参数
_DEFAULT_KEEP_RECENT = 3
_DEFAULT_DETAIL_CHARS = 400
_DEFAULT_DIGEST_CHARS = 80


def _one_line(text: str, limit: int) -> str:
    """单行化 + 截断（摘要行用）。"""
    flat = " ".join(str(text).split())
    return flat[:limit]


def _render_legacy(steps: List[Tuple[str, str]]) -> str:
    """旧口径渲染：最近 5 步 × 150 字，"[步骤]/[结果]" 两行式（逐字节同迁移前）。"""
    history_lines = [
        f"[步骤] {s}\n[结果] {str(r)[:_LEGACY_CHARS]}"
        for s, r in steps[-_LEGACY_RECENT:]
    ]
    return "\n\n".join(history_lines)


def compress_history(
    past_steps: Sequence[Tuple[str, str]],
    *,
    enabled: bool = False,
    keep_recent: int = _DEFAULT_KEEP_RECENT,
    detail_chars: int = _DEFAULT_DETAIL_CHARS,
    digest_chars: int = _DEFAULT_DIGEST_CHARS,
) -> str:
    """把 past_steps 渲染为可注入 LLM 的历史文本。

    - 空历史 → 空串；
    - enabled=False 或步数 ≤ keep_recent+2 → 旧口径（最近 5 步 × 150 字）；
    - enabled=True 且步数更多 → 旧步骤一行式摘要 + 最近 keep_recent 步 detail_chars 字详情。
    """
    steps = list(past_steps or [])
    if not steps:
        return ""
    if not enabled or len(steps) <= keep_recent + 2:
        return _render_legacy(steps)

    older = steps[:-keep_recent]
    recent = steps[-keep_recent:]
    older_block = "\n".join(
        f"- {_one_line(s, 60)} — {_one_line(r, digest_chars)}" for s, r in older
    )
    recent_block = "\n\n".join(
        f"[步骤] {s}\n[结果] {str(r)[:detail_chars]}" for s, r in recent
    )
    return f"[较早步骤摘要]\n{older_block}\n\n[最近步骤详情]\n{recent_block}"
