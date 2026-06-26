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
    get_description_split_prompt,
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
        prompt = get_description_to_outline_prompt(_ctx("第一页：A\n内容可见上传的图片"))
        assert "需上传图片" in prompt
        assert "内容可见上传的图片" in prompt  # 原句作为反例保留

    def test_no_paraphrase_encouraged(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A"))
        # 旧的诱导改写措辞必须移除
        assert "concise summaries" not in prompt

    def test_empty_points_allowed(self):
        prompt = get_description_to_outline_prompt(_ctx("第一页：A"))
        assert "empty array" in prompt or "[]" in prompt


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
            _ctx("第一页：A"), [{"title": "A", "points": []}, {"title": "B", "points": []}]
        )
        # 旧的 "create a reasonable description based on the outline" 必须移除
        assert "create a reasonable description" not in prompt
        assert "（原文未提供）" in prompt
        assert "hallucinate" in prompt
