"""技能路由（skills，B2b）测试。

- 路由：征兆命中 / 零命中兜底全量 / 空输入 / top_k / 稳定性
- 内容保真：全量块包含全部卡 guidance（与原文逐字一致由独立验证脚本佐证）
- planner 接线：prompt 变量化 / 开关控制 _build_skills_block
"""

from src.agent.aiops.planner import _build_skills_block, planner_prompt
from src.agent.aiops.skills import SKILLS, render_skills_block, route_skills
from src.settings import settings


# ═══════════════ 路由 ═══════════════


class TestRouteSkills:
    def test_network_symptom_routes_net_card(self):
        got = route_skills("今天接口延迟很高,还有丢包")
        assert got[0].id == "skill.net"

    def test_url_routes_site_card(self):
        got = route_skills("帮我检查 https://example.com/ 能不能打开")
        assert got[0].id == "skill.site"

    def test_zero_hit_falls_back_to_all(self):
        assert len(route_skills("你好")) == len(SKILLS)

    def test_empty_input_falls_back_to_all(self):
        assert len(route_skills("")) == len(SKILLS)

    def test_top_k_limit(self):
        got = route_skills("网站打不开,接口 5xx 崩溃,配置也不对", top_k=2)
        assert len(got) <= 2

    def test_change_and_net_multi_hit(self):
        got = route_skills("刚发版就出现连接超时", top_k=10)
        ids = [s.id for s in got]
        assert "skill.change" in ids and "skill.net" in ids

    def test_no_duplicates(self):
        got = route_skills("延迟")
        assert len({s.id for s in got}) == len(got)


# ═══════════════ 渲染与内容 ═══════════════


class TestRenderBlock:
    def test_full_block_contains_all_guidances(self):
        block = render_skills_block(SKILLS)
        for sk in SKILLS:
            assert sk.guidance in block, sk.id

    def test_nine_skills_with_keywords(self):
        assert len(SKILLS) == 9
        for sk in SKILLS:
            assert sk.symptom_keywords, sk.id

    def test_render_two_cards(self):
        cards = route_skills("网站打开超时")
        assert render_skills_block(cards) == "\n".join(c.guidance for c in cards)


# ═══════════════ planner 接线 ═══════════════


class TestPlannerWiring:
    def test_prompt_has_skills_block_variable(self):
        assert "skills_block" in planner_prompt.input_variables

    def test_prompt_no_longer_inlines_paths(self):
        template_text = str(planner_prompt.messages[0].prompt.template)
        assert "- 网络/连通性:" not in template_text  # 原文已移出模板
        assert "{skills_block}" in template_text

    def test_prompt_renders_skills_block(self):
        msgs = planner_prompt.format_messages(
            tools_description="T",
            experience_context="E",
            skills_block="[[SKILLS_BLOCK]]",
            messages=[],
        )
        assert "[[SKILLS_BLOCK]]" in msgs[0].content

    def test_build_block_default_full(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_SKILL_ROUTING", False)
        block = _build_skills_block("随便说说")
        assert "- 网络/连通性" in block and "- 外部依赖" in block

    def test_build_block_routed_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_SKILL_ROUTING", True)
        block = _build_skills_block("接口延迟高、丢包")
        assert "- 网络/连通性" in block
        assert "- 外部依赖" not in block  # 未命中卡不注入
