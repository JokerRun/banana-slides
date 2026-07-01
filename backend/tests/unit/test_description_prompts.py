"""
generate_from_description 链路 prompt 单元测试

锁定 fidelity rules，防止回归到"concise summaries"或"create a reasonable
description"等诱导改写/幻觉的措辞。对应产品反馈：
- 设计注释混入正文
- P1/P2 等页码格式不识别
- 标题/要点被改写、图片信息被臆造
"""

from services.ai_service import ProjectContext
from services.prompts import (
    get_description_to_outline_prompt,
    get_image_edit_prompt,
    get_description_split_prompt,
    get_image_generation_prompt,
    get_page_description_prompt,
    resolve_image_generation_style_contract,
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
    def test_no_style_prompt_has_no_hidden_ddi_or_consulting_defaults(self):
        prompt = get_image_generation_prompt(
            page_desc="页面标题：Market Growth\n页面文字：\n- Revenue up 30%",
            outline_text="1. Market Growth",
            current_section="Market Growth",
            language="en",
            has_template=False,
        )

        forbidden_terms = [
            "DDI",
            "麦肯锡",
            "咨询",
            "BCG",
            "consulting report",
            "consulting-grade",
            "default DDI palette",
            "#3D4F5F",
            "#F9A825",
        ]
        for term in forbidden_terms:
            assert term not in prompt

    def test_custom_style_prompt_uses_only_user_style_contract(self):
        style_contract = resolve_image_generation_style_contract(
            extra_requirements="Use a playful neon editorial style.",
            has_template=False,
        )
        prompt = get_image_generation_prompt(
            page_desc="页面标题：Launch\n页面文字：\n- Ship beta",
            outline_text="1. Launch",
            current_section="Launch",
            language="en",
            has_template=False,
            style_contract=style_contract,
        )

        assert style_contract.kind == "custom"
        assert "Use a playful neon editorial style." in prompt
        assert "DDI" not in prompt
        assert "麦肯锡" not in prompt
        assert "BCG" not in prompt

    def test_ddi_prompt_appears_only_when_ddi_preset_selected(self):
        style_contract = resolve_image_generation_style_contract(
            extra_requirements="DDI canonical body",
            style_preset_id="ddi-standard",
            has_template=True,
        )
        prompt = get_image_generation_prompt(
            page_desc="页面标题：Market Growth\n页面文字：\n- Revenue up 30%",
            outline_text="1. Market Growth",
            current_section="Market Growth",
            language="en",
            has_template=True,
            style_contract=style_contract,
        )

        assert style_contract.kind == "preset"
        assert "ddi-standard" in prompt
        assert "DDI canonical body" in prompt

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


class TestImageRefNormalization:
    """Tests for markdown image reference normalization (Hybrid fix for image context loss)"""

    def test_normalize_single_markdown_image(self):
        from services.ai_service import AIService

        text = "我们的Logo：![公司Logo](/files/logo.png)"
        normalized, refs = AIService.normalize_markdown_image_references(text)

        assert '[IMAGE_REF:image_1 alt="公司Logo"]' in normalized
        assert "![公司Logo](/files/logo.png)" not in normalized
        assert len(refs) == 1
        assert refs[0].id == "image_1"
        assert refs[0].alt == "公司Logo"
        assert refs[0].url == "/files/logo.png"
        assert refs[0].source_index == 1

    def test_normalize_multiple_markdown_images(self):
        from services.ai_service import AIService

        text = (
            "第一页：![封面图](/files/cover.png)\n"
            "第二页：![示意图](https://example.com/diagram.jpg)"
        )
        normalized, refs = AIService.normalize_markdown_image_references(text)

        assert '[IMAGE_REF:image_1 alt="封面图"]' in normalized
        assert '[IMAGE_REF:image_2 alt="示意图"]' in normalized
        assert len(refs) == 2
        assert refs[0].id == "image_1"
        assert refs[1].id == "image_2"
        assert refs[0].url == "/files/cover.png"
        assert refs[1].url == "https://example.com/diagram.jpg"

    def test_handles_empty_alt_text(self):
        from services.ai_service import AIService

        text = "内容：![](/files/image.png)"
        normalized, refs = AIService.normalize_markdown_image_references(text)

        assert '[IMAGE_REF:image_1 alt="user provided image"]' in normalized
        assert len(refs) == 1
        assert refs[0].alt == "user provided image"

    def test_preserves_non_image_markdown(self):
        from services.ai_service import AIService

        text = "链接：[点击这里](http://example.com) 和 ![图片](/files/img.png)"
        normalized, refs = AIService.normalize_markdown_image_references(text)

        # 普通链接应该保持不变
        assert "[点击这里](http://example.com)" in normalized
        # 图片应该被转换
        assert '[IMAGE_REF:image_1 alt="图片"]' in normalized
        assert len(refs) == 1

    def test_skips_unsupported_urls(self):
        from services.ai_service import AIService

        text = "![内部链接](ftp://server.com/image.png) 和 ![图片](/files/img.png)"
        normalized, refs = AIService.normalize_markdown_image_references(text)

        # 不支持的 URL 应该保持不变
        assert "![内部链接](ftp://server.com/image.png)" in normalized
        # 支持的 URL 应该被转换
        assert '[IMAGE_REF:image_1 alt="图片"]' in normalized
        assert len(refs) == 1

    def test_handles_empty_text(self):
        from services.ai_service import AIService

        text = ""
        normalized, refs = AIService.normalize_markdown_image_references(text)

        assert normalized == ""
        assert refs == []


class TestImageGenerationPromptWithImageRefs:
    """Tests for image generation prompt with image reference manifest"""

    def test_includes_image_ref_manifest_when_refs_provided(self):
        image_refs = [
            {
                "id": "image_1",
                "alt": "公司Logo",
                "url": "/files/logo.png",
                "source_index": 1,
            }
        ]
        prompt = get_image_generation_prompt(
            page_desc='页面文字：\n- 我们的Logo：[IMAGE_REF:image_1 alt="公司Logo"]',
            outline_text="1. 封面",
            current_section="封面",
            image_refs=image_refs,
        )

        assert "Image Reference Manifest:" in prompt
        assert "image_1" in prompt
        assert "caption: 公司Logo" in prompt
        assert "source: /files/logo.png" in prompt
        assert "attached_as_reference_image: true" in prompt
        assert '[IMAGE_REF:image_1 alt="公司Logo"]' in prompt

    def test_omits_manifest_when_no_refs(self):
        prompt = get_image_generation_prompt(
            page_desc="页面文字：\n- 普通文本",
            outline_text="1. 封面",
            current_section="封面",
            image_refs=[],
        )

        assert "Image Reference Manifest:" not in prompt

    def test_multiple_image_refs_in_manifest(self):
        image_refs = [
            {
                "id": "image_1",
                "alt": "封面",
                "url": "/files/cover.png",
                "source_index": 1,
            },
            {
                "id": "image_2",
                "alt": "图表",
                "url": "https://example.com/chart.jpg",
                "source_index": 2,
            },
        ]
        prompt = get_image_generation_prompt(
            page_desc=(
                "页面文字：\n"
                '- [IMAGE_REF:image_1 alt="封面"]\n'
                '- [IMAGE_REF:image_2 alt="图表"]'
            ),
            outline_text="1. 封面\n2. 数据",
            current_section="数据",
            image_refs=image_refs,
        )

        assert "image_1" in prompt
        assert "image_2" in prompt
        assert "caption: 封面" in prompt
        assert "caption: 图表" in prompt
        assert "/files/cover.png" in prompt
        assert "https://example.com/chart.jpg" in prompt
