"""
generate_from_description 链路 prompt 单元测试

锁定 fidelity rules，防止回归到"concise summaries"或"create a reasonable
description"等诱导改写/幻觉的措辞。对应产品反馈：
- 设计注释混入正文
- P1/P2 等页码格式不识别
- 标题/要点被改写、图片信息被臆造
"""

import pytest

from services.ai_service import ProjectContext
from services.prompts import (
    get_description_to_outline_prompt,
    get_image_edit_prompt,
    get_description_split_prompt,
    get_image_generation_prompt,
    get_page_description_prompt,
)


def _ctx(description_text: str) -> ProjectContext:
    return ProjectContext({"description_text": description_text}, [])


class TestDescriptionToOutlinePrompt:
    def test_contains_verbatim_fidelity_rule(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A\n内容：x"))
        assert "VERBATIM" in prompt
        assert "钩子句" in prompt  # 反例来自真实日志

    def test_recognizes_multiple_page_markers(self):
        prompt = get_description_to_outline_prompt(_ctx("P1：A"))
        # 多种页码标记必须被列举
        for marker in ["第一页", "第1页", "P1", "Page 1", "Slide 1", "①"]:
            assert marker in prompt

    def test_design_notes_excluded_from_points(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A"))
        assert "排版" in prompt
        assert "NOT body content" in prompt

    def test_image_reference_preserved_as_point(self):
        prompt = get_description_to_outline_prompt(
            _ctx("第一页：A\n内容可见上传的图片")
        )
        assert "需上传图片" in prompt
        assert "内容可见上传的图片" in prompt  # 原句作为反例保留

    def test_no_paraphrase_encouraged(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A"))
        # 旧的诱导改写措辞必须移除
        assert "concise summaries" not in prompt

    def test_empty_points_allowed(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A"))
        assert "empty array" in prompt or "[]" in prompt

    def test_title_strips_delimiter_prefix(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：封面"))
        # 必须明确要求剥离前缀，并给出 WRONG/RIGHT 对照
        assert "第一页：封面" in prompt
        assert 'title "封面"' in prompt
        assert 'NOT "第一页：封面"' in prompt
        # 覆盖多种 delimiter 形式的剥离示例
        for src in ["P1：项目背景", "Page 1: Welcome", "1. 封面", "①项目背景"]:
            assert src in prompt


class TestDescriptionSplitPrompt:
    def test_contains_verbatim_fidelity_rule(self):
        prompt = get_description_split_prompt(
            _ctx("第一页：A\n内容：x"), [{"title": "A", "points": ["x"]}]
        )
        assert "VERBATIM" in prompt

    def test_design_notes_only_in_other_section(self):
        prompt = get_description_split_prompt(
            _ctx("第一页：A"), [{"title": "A", "points": []}]
        )
        assert "其他页面素材" in prompt
        assert "NEVER appear in" in prompt

    def test_image_reference_preserved_verbatim(self):
        prompt = get_description_split_prompt(
            _ctx("第一页：A\n内容可见上传的图片"), [{"title": "A", "points": []}]
        )
        assert "需上传图片" in prompt
        assert "内容可见上传的图片" in prompt

    def test_no_hallucination_for_missing_page(self):
        prompt = get_description_split_prompt(
            _ctx("第一页：A"),
            [{"title": "A", "points": []}, {"title": "B", "points": []}],
        )
        # 旧的 "create a reasonable description based on the outline" 必须移除
        assert "create a reasonable description" not in prompt
        assert "（原文未提供）" in prompt
        assert "hallucinate" in prompt

    def test_requires_ascii_layout_recommendation_without_changing_user_constraints(
        self,
    ):
        prompt = get_description_split_prompt(
            _ctx("第一页：A\n配色：black and gold\n模板：investor report"),
            [{"title": "A", "points": []}],
            language="en",
        )

        assert "ASCII Diagram" in prompt
        assert "Layout Recommendation" in prompt
        for region in [
            "title area",
            "visual area",
            "key message area",
            "bullet list",
            "chart/image area",
        ]:
            assert region in prompt
        assert "must not modify user-provided content" in prompt
        assert "must not modify user-provided color scheme" in prompt
        assert "must not modify user-provided base template constraints" in prompt


class TestPageDescriptionPrompt:
    def test_requires_ascii_layout_recommendation_without_changing_user_constraints(
        self,
    ):
        ctx = ProjectContext(
            {
                "creation_type": "outline",
                "outline_text": "Color scheme: black and gold\nBase template: investor report",
            },
            [],
        )
        prompt = get_page_description_prompt(
            project_context=ctx,
            outline=[{"title": "Market Growth", "points": ["Revenue up 30%"]}],
            page_outline={"title": "Market Growth", "points": ["Revenue up 30%"]},
            page_index=2,
            language="en",
        )

        assert "ASCII Diagram" in prompt
        assert "Layout Recommendation" in prompt
        for region in [
            "title area",
            "visual area",
            "key message area",
            "bullet list",
            "chart/image area",
        ]:
            assert region in prompt
        assert "must not modify user-provided content" in prompt
        assert "must not modify user-provided color scheme" in prompt
        assert "must not modify user-provided base template constraints" in prompt


class TestImageGenerationPrompt:
    def test_treats_ascii_layout_recommendation_as_non_rendered_instruction(self):
        prompt = get_image_generation_prompt(
            page_desc=(
                "页面标题：Market Growth\n"
                "页面文字：\n"
                "- Revenue up 30%\n\n"
                "布局建议（Layout Recommendation - ASCII Diagram）：\n"
                "+----------------------+----------------------+\n"
                "| title area           | key message area     |\n"
                "+----------------------+----------------------+\n"
                "| visual area          | bullet list          |\n"
                "+----------------------+----------------------+\n"
            ),
            outline_text="1. Market Growth",
            current_section="Market Growth",
            language="en",
        )

        assert "Layout Recommendation" in prompt
        assert "layout-only instruction" in prompt
        assert "must not be rendered as slide text" in prompt
        assert "Do not draw ASCII borders" in prompt

    def test_user_color_scheme_takes_priority_over_default_ddi_palette(self):
        prompt = get_image_generation_prompt(
            page_desc=(
                "页面标题：Market Growth\n"
                "页面文字：\n"
                "- Revenue up 30%\n"
                "其他页面素材：\n"
                "配色：black and gold\n"
            ),
            outline_text="1. Market Growth",
            current_section="Market Growth",
            language="en",
        )

        assert "user-provided color scheme" in prompt
        assert "default DDI palette" in prompt
        assert "only when" in prompt


class TestImageEditPrompt:
    def test_strips_ascii_layout_recommendation_from_original_description(self):
        prompt = get_image_edit_prompt(
            edit_instruction="make title larger",
            original_description=(
                "页面标题：Market Growth\n"
                "页面文字：\n"
                "- Revenue up 30%\n\n"
                "布局建议（Layout Recommendation - ASCII Diagram）：\n"
                "+----------------------+----------------------+\n"
                "| title area           | key message area     |\n"
                "+----------------------+----------------------+\n\n"
                "其他页面素材：\n"
                "配色：black and gold\n"
            ),
        )

        assert "页面标题：Market Growth" in prompt
        assert "- Revenue up 30%" in prompt
        assert "布局建议" not in prompt
        assert "ASCII Diagram" not in prompt
        assert "title area" not in prompt
