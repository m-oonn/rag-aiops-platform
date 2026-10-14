"""诊断历史压缩器（compaction，B2a）测试。

三层覆盖：
  1. 旧口径路径——逐字节同迁移前（最近 5 步 × 150 字，"[步骤]/[结果]" 两行式）
  2. 压缩路径——阈值触发 + 摘要行 80 字 / 详情 400 字截断 + 结构标记
  3. 开关与边界——enabled=False 恒旧口径；≤ 阈值不压缩；参数适配
"""

from src.agent.aiops.compaction import compress_history


def _plain(n: int, length: int = 1000):
    return [(f"step{i:02d}", "X" * length) for i in range(1, n + 1)]


# ═══════════════ 旧口径路径（回归基线）═══════════════


class TestLegacyPath:
    def test_empty(self):
        assert compress_history([]) == ""
        assert compress_history(None) == ""

    def test_legacy_exact_format(self):
        out = compress_history([("do-a", "res-a")], enabled=False)
        assert out == "[步骤] do-a\n[结果] res-a"

    def test_legacy_truncates_result_at_150(self):
        out = compress_history([("s1", "R" * 500)], enabled=False)
        assert "R" * 150 in out and "R" * 151 not in out

    def test_disabled_uses_legacy_even_for_long_history(self):
        out = compress_history(_plain(10), enabled=False)
        assert "[较早步骤摘要]" not in out
        assert out.count("[步骤]") == 5  # 只留最近 5 步
        assert "step06" in out
        assert "step01" not in out  # 旧步骤丢弃（旧行为）

    def test_short_history_stays_legacy_when_enabled(self):
        out = compress_history(_plain(5), enabled=True)
        assert "[较早步骤摘要]" not in out  # 5 ≤ keep_recent+2，不触发压缩
        assert out.count("[步骤]") == 5


# ═══════════════ 压缩路径 ═══════════════


class TestCompactionPath:
    def test_long_history_compacted_structure(self):
        out = compress_history(_plain(10), enabled=True)
        assert "[较早步骤摘要]" in out and "[最近步骤详情]" in out
        assert out.count("[步骤]") == 3  # 最近 3 步详情（默认 keep_recent）

    def test_older_steps_summarized_as_one_line(self):
        out = compress_history(_plain(10), enabled=True)
        assert "- step01 — " in out  # 旧步骤一行式（步骤名 + 结果摘要）
        assert "step07" in out  # 边界：第 7 步是摘要区最后一条

    def test_digest_truncated_at_80(self):
        out = compress_history(_plain(6), enabled=True, keep_recent=1)
        head = out.split("[最近步骤详情]")[0]
        assert "X" * 80 in head
        assert "X" * 81 not in head

    def test_detail_truncated_at_400(self):
        out = compress_history(_plain(6), enabled=True, keep_recent=1)
        assert "X" * 400 in out
        assert "X" * 401 not in out

    def test_boundary_six_steps_compacts(self):
        out = compress_history(_plain(6), enabled=True)
        assert "[较早步骤摘要]" in out  # 6 > 3+2 触发压缩

    def test_keep_recent_param(self):
        out = compress_history(_plain(10), enabled=True, keep_recent=5)
        assert out.count("[步骤]") == 5
        assert "[较早步骤摘要]" in out  # 10 > 5+2

    def test_recent_steps_keep_full_step_names(self):
        steps = [(f"完整步骤名称{i}", "Y" * 600) for i in range(1, 9)]
        out = compress_history(steps, enabled=True)
        detail = out.split("[最近步骤详情]")[1]
        assert "完整步骤名称8" in detail  # 最近步骤保留原名（不截 60 字）
