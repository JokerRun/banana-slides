"""
AI Service Prompts - 集中管理所有 AI 服务的 prompt 模板
"""

import json
import logging
from textwrap import dedent
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from services.ai_service import ProjectContext

logger = logging.getLogger(__name__)


# 语言配置映射
LANGUAGE_CONFIG = {
    "zh": {
        "name": "中文",
        "instruction": "请使用全中文输出。",
        "ppt_text": "PPT文字请使用全中文。",
    },
    "ja": {
        "name": "日本語",
        "instruction": "すべて日本語で出力してください。",
        "ppt_text": "PPTのテキストは全て日本語で出力してください。",
    },
    "en": {
        "name": "English",
        "instruction": "Please output all in English.",
        "ppt_text": "Use English for PPT text.",
    },
    "auto": {
        "name": "自动",
        "instruction": "",  # 自动模式不添加语言限制
        "ppt_text": "",
    },
}


def get_default_output_language() -> str:
    """
    获取环境变量中配置的默认输出语言

    Returns:
        语言代码: 'zh', 'ja', 'en', 'auto'
    """
    from config import Config

    return getattr(Config, "OUTPUT_LANGUAGE", "zh")


def get_language_instruction(language: str = None) -> str:
    """
    获取语言限制指令文本

    Args:
        language: 语言代码，如果为 None 则使用默认语言

    Returns:
        语言限制指令，如果是自动模式则返回空字符串
    """
    lang = language if language else get_default_output_language()
    config = LANGUAGE_CONFIG.get(lang, LANGUAGE_CONFIG["zh"])
    return config["instruction"]


def get_ppt_language_instruction(language: str = None) -> str:
    """
    获取PPT文字语言限制指令

    Args:
        language: 语言代码，如果为 None 则使用默认语言

    Returns:
        PPT语言限制指令，如果是自动模式则返回空字符串
    """
    lang = language if language else get_default_output_language()
    config = LANGUAGE_CONFIG.get(lang, LANGUAGE_CONFIG["zh"])
    return config["ppt_text"]


def _format_reference_files_xml(
    reference_files_content: Optional[List[Dict[str, str]]],
) -> str:
    """
    Format reference files content as XML structure

    Args:
        reference_files_content: List of dicts with 'filename' and 'content' keys

    Returns:
        Formatted XML string
    """
    if not reference_files_content:
        return ""

    xml_parts = ["<uploaded_files>"]
    for file_info in reference_files_content:
        filename = file_info.get("filename", "unknown")
        content = file_info.get("content", "")
        xml_parts.append(f'  <file name="{filename}">')
        xml_parts.append("    <content>")
        xml_parts.append(content)
        xml_parts.append("    </content>")
        xml_parts.append("  </file>")
    xml_parts.append("</uploaded_files>")
    xml_parts.append("")  # Empty line after XML

    return "\n".join(xml_parts)


def get_outline_generation_prompt(
    project_context: "ProjectContext", language: str = None
) -> str:
    """
    生成 PPT 大纲的 prompt

    Args:
        project_context: 项目上下文对象，包含所有原始信息
        language: 输出语言代码（'zh', 'ja', 'en', 'auto'），如果为 None 则使用默认语言

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)
    idea_prompt = project_context.idea_prompt or ""

    prompt = f"""\
You are a helpful assistant that generates an outline for a ppt.

You can organize the content in two ways:

1. Simple format (for short PPTs without major sections):
[{{"title": "title1", "points": ["point1", "point2"]}}, {{"title": "title2", "points": ["point1", "point2"]}}]

2. Part-based format (for longer PPTs with major sections):
[
    {{
    "part": "Part 1: Introduction",
    "pages": [
        {{"title": "Welcome", "points": ["point1", "point2"]}},
        {{"title": "Overview", "points": ["point1", "point2"]}}
    ]
    }},
    {{
    "part": "Part 2: Main Content",
    "pages": [
        {{"title": "Topic 1", "points": ["point1", "point2"]}},
        {{"title": "Topic 2", "points": ["point1", "point2"]}}
    ]
    }}
]

Choose the format that best fits the content. Use parts when the PPT has clear major sections.
Unless otherwise specified, the first page should be kept simplest, containing only the title, subtitle, and presenter information.

The user's request: {idea_prompt}. Now generate the outline, don't include any other text.
{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_outline_generation_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_outline_parsing_prompt(
    project_context: "ProjectContext", language: str = None
) -> str:
    """
    解析用户提供的大纲文本的 prompt

    Args:
        project_context: 项目上下文对象，包含所有原始信息

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)
    outline_text = project_context.outline_text or ""

    prompt = f"""\
You are a helpful assistant that parses a user-provided PPT outline text into a structured format.

The user has provided the following outline text:

{outline_text}

Your task is to analyze this text and convert it into a structured JSON format WITHOUT modifying any of the original text content.
You should only reorganize and structure the existing content, preserving all titles, points, and text exactly as provided.

You can organize the content in two ways:

1. Simple format (for short PPTs without major sections):
[{{"title": "title1", "points": ["point1", "point2"]}}, {{"title": "title2", "points": ["point1", "point2"]}}]

2. Part-based format (for longer PPTs with major sections):
[
    {{
    "part": "Part 1: Introduction",
    "pages": [
        {{"title": "Welcome", "points": ["point1", "point2"]}},
        {{"title": "Overview", "points": ["point1", "point2"]}}
    ]
    }},
    {{
    "part": "Part 2: Main Content",
    "pages": [
        {{"title": "Topic 1", "points": ["point1", "point2"]}},
        {{"title": "Topic 2", "points": ["point1", "point2"]}}
    ]
    }}
]

Important rules:
- DO NOT modify, rewrite, or change any text from the original outline
- DO NOT add new content that wasn't in the original text
- DO NOT remove any content from the original text
- Only reorganize the existing content into the structured format
- Preserve all titles, bullet points, and text exactly as they appear
- If the text has clear sections/parts, use the part-based format
- Extract titles and points from the original text, keeping them exactly as written

Now parse the outline text above into the structured format. Return only the JSON, don't include any other text.
{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_outline_parsing_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_page_description_prompt(
    project_context: "ProjectContext",
    outline: list,
    page_outline: dict,
    page_index: int,
    part_info: str = "",
    language: str = None,
) -> str:
    """
    生成单个页面描述的 prompt

    Args:
        project_context: 项目上下文对象，包含所有原始信息
        outline: 完整大纲
        page_outline: 当前页面的大纲
        page_index: 页面编号（从1开始）
        part_info: 可选的章节信息

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)
    # 根据项目类型选择最相关的原始输入
    if project_context.creation_type == "idea" and project_context.idea_prompt:
        original_input = project_context.idea_prompt
    elif project_context.creation_type == "outline" and project_context.outline_text:
        original_input = f"用户提供的大纲：\n{project_context.outline_text}"
    elif (
        project_context.creation_type == "descriptions"
        and project_context.description_text
    ):
        original_input = f"用户提供的描述：\n{project_context.description_text}"
    else:
        original_input = project_context.idea_prompt or ""

    prompt = f"""\
我们正在为PPT的每一页生成内容描述。
用户的原始需求是：\n{original_input}\n
我们已经有了完整的大纲：\n{outline}\n{part_info}
现在请为第 {page_index} 页生成描述：
{page_outline}
{"**除非特殊要求，第一页的内容需要保持极简，只放标题副标题以及演讲人等（输出到标题后）, 不添加任何素材。**" if page_index == 1 else ""}

【重要提示】生成的"页面文字"部分会直接渲染到PPT页面上，因此请务必注意：
1. 文字内容要简洁精炼，每条要点控制在15-25字以内
2. 条理清晰，使用列表形式组织内容
3. 避免冗长的句子和复杂的表述
4. 确保内容可读性强，适合在演示时展示
5. 不要包含任何额外的说明性文字或注释

输出格式示例：
页面标题：原始社会：与自然共生
{"副标题：人类祖先和自然的相处之道" if page_index == 1 else ""}

页面文字：
- 狩猎采集文明：人类活动规模小，对环境影响有限
- 依赖性强：生活完全依赖自然资源的直接供给
- 适应而非改造：通过观察学习自然，发展生存技能
- 影响特点：局部、短期、低强度，生态可自我恢复

其他页面素材（如果文件中存在请积极添加，包括markdown图片链接、公式、表格等）

【关于图片】如果参考文件中包含以 /files/ 开头的本地文件URL图片（例如 /files/mineru/xxx/image.png），请将这些图片以markdown格式输出，例如：![图片描述](/files/mineru/xxx/image.png)。这些图片会被包含在PPT页面中。

{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_page_description_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_image_generation_prompt(
    page_desc: str,
    outline_text: str,
    current_section: str,
    has_material_images: bool = False,
    extra_requirements: str = None,
    language: str = None,
    has_template: bool = True,
    page_index: int = 1,
) -> str:
    """
    生成图片生成 prompt

    Args:
        page_desc: 页面描述文本
        outline_text: 大纲文本
        current_section: 当前章节
        has_material_images: 是否有素材图片
        extra_requirements: 额外的要求（可能包含风格描述）
        language: 输出语言
        has_template: 是否有模板图片（False表示无模板图模式）

    Returns:
        格式化后的 prompt 字符串
    """
    # 如果有素材图片，在 prompt 中明确告知 AI
    material_images_note = ""
    if has_material_images:
        material_images_note = (
            "\n\n提示："
            + (
                "除了模板参考图片（用于风格参考）外，还提供了额外的素材图片。"
                if has_template
                else "用户提供了额外的素材图片。"
            )
            + "这些素材图片是可供挑选和使用的元素，你可以从这些素材图片中选择合适的图片、图标、图表或其他视觉元素"
            "直接整合到生成的PPT页面中。请根据页面内容的需要，智能地选择和组合这些素材图片中的元素。"
        )

    # 添加额外要求到提示词
    extra_req_text = ""
    if extra_requirements and extra_requirements.strip():
        extra_req_text = f"\n\n额外要求（请务必遵循）：\n{extra_requirements}\n"

    # 根据是否有模板/风格参考图生成不同的设计指南内容（保持原prompt要点顺序）
    template_style_guideline = (
        "- 深度解析参考图的版式框架、色彩系统、字体规范、图形语言，并将其完整应用于新页面。"
        if has_template
        else "- 严格按照风格描述进行设计。"
    )
    forbidden_template_text_guidline = (
        "- 只参考风格设计，禁止出现模板中的文字。\n" if has_template else ""
    )

    prompt = f"""\
# Role: 资深商业咨询级 PPT 内容架构师与视觉设计师

# Inputs:
- 参考图片 = 标准 PPT 模板 / 风格参考图（若提供）
- [文本] = 当前页需要转化为 PPT 的原始页面内容

# Core Objective:
基于 [文本] 的内容与业务逻辑，套用参考图片的 PPT 模板风格，
从零设计页面的信息架构、视觉层级、空间关系与排版方式，
输出具有麦肯锡 / BCG 咨询报告风格的专业商务 PPT 页面。

当前PPT页面的[文本]如下:
<page_description>
{page_desc}
</page_description>

<reference_information>
整个PPT的大纲为：
{outline_text}

当前位于章节：{current_section}
</reference_information>


<execution_rules>
- 要求文字清晰锐利，画面为高分辨率，16:9比例。
{template_style_guideline}
- 严格基于 [文本] 中的原始文字内容进行排版设计，禁止凭空新增、替换、总结或重写未出现的文字信息。
- 可以对内容进行视觉化拆分、归类、层级化呈现，以及必要的版式适配（如将长句拆分为要点列表）。
- 深度理解 [文本] 的业务主题、逻辑关系（并列 / 递进 / 包含 / 对比 / 因果），再决定版式。
- 强制执行文本条目与视觉区块的 1:1 映射，严格基于实际文本条目数生成对应数量的几何区块或层级。
- 若 [文本] 中包含明确主题或标题，将其作为页面标题；若无法识别明确标题，严禁自行捏造标题。
- 标题规范：微软雅黑 Bold，32pt，DDI 板岩蓝 #3D4F5F，左对齐，贴近内容区左侧。
- 色系限定：标题/页眉/结构线/主视觉使用 #3D4F5F；强调色/流程箭头/重点标签使用 #F9A825；辅助色仅使用 #2D72B2 / #E67E22 / #88A02C / #662D7C / #8B9A46；正文 #333333，次要文本 #666666，分割线 #E0E0E0，背景 #FFFFFF。
- 优先理解内容逻辑并匹配最优版式：流程用路线图，对比用左右/矩阵，层级用分层/冰山，核心主题用辐射/树状，概览用网格卡片，指标用 dashboard，循环用环形流转，问题到解决方案用桥接版式。
- 允许图形：圆形节点、圆角矩形、房屋图标、粗体折线/S形箭头、带序号流程节点、矩阵表格、金字塔、文档图示；必须为纯扁平化矢量风格。
- 主视觉区块控制在 3–5 个内并容纳所有原文内容；整体留白 8%–10%；文字约 40%，结构化图形约 60%；线条粗细一致，严格网格对齐。
- 若文本缺乏视觉支撑，可生成与内容高度匹配的扁平化图标或配图，但不得与文字重叠。
- 如非必要，禁止出现 markdown 格式符号（如 # 和 * 等）。
{forbidden_template_text_guidline}- 使用大小恰当的装饰性图形或插画对空缺位置进行填补。
</execution_rules>
{get_ppt_language_instruction(language)}
{material_images_note}{extra_req_text}

{"**注意：当前页面为ppt的封面页，请你采用专业的封面设计美学技巧，务必凸显出页面标题，分清主次，确保一下就能抓住观众的注意力。**" if page_index == 1 else ""}

# Output Format:
请输出基于 [文本] 内容生成的 16:9 高保真商业 PPT 页面，确保所有视觉块清晰规整，具有明确的边界逻辑。
"""

    logger.debug(f"[get_image_generation_prompt] Final prompt:\n{prompt}")
    return prompt


def get_image_edit_prompt(
    edit_instruction: str, original_description: str = None
) -> str:
    """
    生成图片编辑 prompt

    Args:
        edit_instruction: 编辑指令
        original_description: 原始页面描述（可选）

    Returns:
        格式化后的 prompt 字符串
    """
    if original_description:
        # 删除"其他页面素材："之后的内容，避免被前面的图影响
        if "其他页面素材" in original_description:
            original_description = original_description.split("其他页面素材")[0].strip()

        prompt = f"""\
该PPT页面的原始页面描述为：
{original_description}

现在，根据以下指令修改这张PPT页面：{edit_instruction}

要求维持原有的文字内容和设计风格，只按照指令进行修改。提供的参考图中既有新素材，也有用户手动框选出的区域，请你根据原图和参考图的关系智能判断用户意图。
"""
    else:
        prompt = f"根据以下指令修改这张PPT页面：{edit_instruction}\n保持原有的内容结构和设计风格，只按照指令进行修改。提供的参考图中既有新素材，也有用户手动框选出的区域，请你根据原图和参考图的关系智能判断用户意图。"

    logger.debug(f"[get_image_edit_prompt] Final prompt:\n{prompt}")
    return prompt


def get_description_to_outline_prompt(
    project_context: "ProjectContext", language: str = None
) -> str:
    """
    从描述文本解析出大纲的 prompt

    Args:
        project_context: 项目上下文对象，包含所有原始信息

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)
    description_text = project_context.description_text or ""

    prompt = f"""\
You are a helpful assistant that analyzes a user-provided PPT description text and extracts the outline structure from it.

The user has provided the following description text:

{description_text}

Your task is to analyze this text and extract the outline structure (titles and key points) for each page.
You should identify:
1. How many pages are described
2. The title for each page
3. The key points or content structure for each page

You can organize the content in two ways:

1. Simple format (for short PPTs without major sections):
[{{"title": "title1", "points": ["point1", "point2"]}}, {{"title": "title2", "points": ["point1", "point2"]}}]

2. Part-based format (for longer PPTs with major sections):
[
    {{
    "part": "Part 1: Introduction",
    "pages": [
        {{"title": "Welcome", "points": ["point1", "point2"]}},
        {{"title": "Overview", "points": ["point1", "point2"]}}
    ]
    }},
    {{
    "part": "Part 2: Main Content",
    "pages": [
        {{"title": "Topic 1", "points": ["point1", "point2"]}},
        {{"title": "Topic 2", "points": ["point1", "point2"]}}
    ]
    }}
]

Important rules:
- Extract the outline structure from the description text
- Identify page titles and key points
- If the text has clear sections/parts, use the part-based format
- Preserve the logical structure and organization from the original text
- The points should be concise summaries of the main content for each page

Now extract the outline structure from the description text above. Return only the JSON, don't include any other text.
{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_description_to_outline_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_description_split_prompt(
    project_context: "ProjectContext", outline: List[Dict], language: str = None
) -> str:
    """
    从描述文本切分出每页描述的 prompt

    Args:
        project_context: 项目上下文对象，包含所有原始信息
        outline: 已解析出的大纲结构

    Returns:
        格式化后的 prompt 字符串
    """
    outline_json = json.dumps(outline, ensure_ascii=False, indent=2)
    description_text = project_context.description_text or ""

    prompt = f"""\
You are a helpful assistant that splits a complete PPT description text into individual page descriptions.

The user has provided a complete description text:

{description_text}

We have already extracted the outline structure:

{outline_json}

Your task is to split the description text into individual page descriptions based on the outline structure.
For each page in the outline, extract the corresponding description from the original text.

Return a JSON array where each element corresponds to a page in the outline (in the same order).
Each element should be a string containing the page description in the following format:

页面标题：[页面标题]

页面文字：
- [要点1]
- [要点2]
...

其他页面素材（如果有排版、风格、素材等细节）

Example output format:
[
    "页面标题：人工智能的诞生\\n页面文字：\\n- 1950 年，图灵提出"图灵测试"\\n- 奠定了AI的理论基础\\n\\n其他页面素材：\\n排版：标题居中，大字号\\n风格：科技感蓝色背景",
    "页面标题：AI 的发展历程\\n页面文字：\\n- 1950年代：符号主义...",
    ...
]

Important rules:
- Split the description text according to the outline structure
- Each page description should match the corresponding page in the outline
- Preserve all important content from the original text, including layout details (排版细节), style requirements (风格要求), material specifications (素材说明), and any other design requirements
- If the user described layout, style, or materials for a page, include them in the "其他页面素材" section
- Keep the format consistent with the example above
- If a page in the outline doesn't have a clear description in the text, create a reasonable description based on the outline

Now split the description text into individual page descriptions. Return only the JSON array, don't include any other text.
{get_language_instruction(language)}
"""

    logger.debug(f"[get_description_split_prompt] Final prompt:\n{prompt}")
    return prompt


def get_outline_refinement_prompt(
    current_outline: List[Dict],
    user_requirement: str,
    project_context: "ProjectContext",
    previous_requirements: Optional[List[str]] = None,
    language: str = None,
) -> str:
    """
    根据用户要求修改已有大纲的 prompt

    Args:
        current_outline: 当前的大纲结构
        user_requirement: 用户的新要求
        project_context: 项目上下文对象，包含所有原始信息
        previous_requirements: 之前的修改要求列表（可选）

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)

    # 处理空大纲的情况
    if not current_outline or len(current_outline) == 0:
        outline_text = "(当前没有内容)"
    else:
        outline_text = json.dumps(current_outline, ensure_ascii=False, indent=2)

    # 构建之前的修改历史记录
    previous_req_text = ""
    if previous_requirements and len(previous_requirements) > 0:
        prev_list = "\n".join([f"- {req}" for req in previous_requirements])
        previous_req_text = f"\n\n之前用户提出的修改要求：\n{prev_list}\n"

    # 构建原始输入信息（根据项目类型显示不同的原始内容）
    original_input_text = "\n原始输入信息：\n"
    if project_context.creation_type == "idea" and project_context.idea_prompt:
        original_input_text += f"- PPT构想：{project_context.idea_prompt}\n"
    elif project_context.creation_type == "outline" and project_context.outline_text:
        original_input_text += (
            f"- 用户提供的大纲文本：\n{project_context.outline_text}\n"
        )
    elif (
        project_context.creation_type == "descriptions"
        and project_context.description_text
    ):
        original_input_text += (
            f"- 用户提供的页面描述文本：\n{project_context.description_text}\n"
        )
    elif project_context.idea_prompt:
        original_input_text += f"- 用户输入：{project_context.idea_prompt}\n"

    prompt = f"""\
You are a helpful assistant that modifies PPT outlines based on user requirements.
{original_input_text}
当前的 PPT 大纲结构如下：

{outline_text}
{previous_req_text}
**用户现在提出新的要求：{user_requirement}**

请根据用户的要求修改和调整大纲。你可以：
- 添加、删除或重新排列页面
- 修改页面标题和要点
- 调整页面的组织结构
- 添加或删除章节（part）
- 合并或拆分页面
- 根据用户要求进行任何合理的调整
- 如果当前没有内容，请根据用户要求和原始输入信息创建新的大纲

输出格式可以选择：

1. 简单格式（适用于没有主要章节的短 PPT）：
[{{"title": "title1", "points": ["point1", "point2"]}}, {{"title": "title2", "points": ["point1", "point2"]}}]

2. 基于章节的格式（适用于有明确主要章节的长 PPT）：
[
    {{
    "part": "第一部分：引言",
    "pages": [
        {{"title": "欢迎", "points": ["point1", "point2"]}},
        {{"title": "概述", "points": ["point1", "point2"]}}
    ]
    }},
    {{
    "part": "第二部分：主要内容",
    "pages": [
        {{"title": "主题1", "points": ["point1", "point2"]}},
        {{"title": "主题2", "points": ["point1", "point2"]}}
    ]
    }}
]

选择最适合内容的格式。当 PPT 有清晰的主要章节时使用章节格式。

现在请根据用户要求修改大纲，只输出 JSON 格式的大纲，不要包含其他文字。
{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_outline_refinement_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_descriptions_refinement_prompt(
    current_descriptions: List[Dict],
    user_requirement: str,
    project_context: "ProjectContext",
    outline: List[Dict] = None,
    previous_requirements: Optional[List[str]] = None,
    language: str = None,
) -> str:
    """
    根据用户要求修改已有页面描述的 prompt

    Args:
        current_descriptions: 当前的页面描述列表，每个元素包含 {index, title, description_content}
        user_requirement: 用户的新要求
        project_context: 项目上下文对象，包含所有原始信息
        outline: 完整的大纲结构（可选）
        previous_requirements: 之前的修改要求列表（可选）

    Returns:
        格式化后的 prompt 字符串
    """
    files_xml = _format_reference_files_xml(project_context.reference_files_content)

    # 构建之前的修改历史记录
    previous_req_text = ""
    if previous_requirements and len(previous_requirements) > 0:
        prev_list = "\n".join([f"- {req}" for req in previous_requirements])
        previous_req_text = f"\n\n之前用户提出的修改要求：\n{prev_list}\n"

    # 构建原始输入信息
    original_input_text = "\n原始输入信息：\n"
    if project_context.creation_type == "idea" and project_context.idea_prompt:
        original_input_text += f"- PPT构想：{project_context.idea_prompt}\n"
    elif project_context.creation_type == "outline" and project_context.outline_text:
        original_input_text += (
            f"- 用户提供的大纲文本：\n{project_context.outline_text}\n"
        )
    elif (
        project_context.creation_type == "descriptions"
        and project_context.description_text
    ):
        original_input_text += (
            f"- 用户提供的页面描述文本：\n{project_context.description_text}\n"
        )
    elif project_context.idea_prompt:
        original_input_text += f"- 用户输入：{project_context.idea_prompt}\n"

    # 构建大纲文本
    outline_text = ""
    if outline:
        outline_json = json.dumps(outline, ensure_ascii=False, indent=2)
        outline_text = f"\n\n完整的 PPT 大纲：\n{outline_json}\n"

    # 构建所有页面描述的汇总
    all_descriptions_text = "当前所有页面的描述：\n\n"
    has_any_description = False
    for desc in current_descriptions:
        page_num = desc.get("index", 0) + 1
        title = desc.get("title", "未命名")
        content = desc.get("description_content", "")
        if isinstance(content, dict):
            content = content.get("text", "")

        if content:
            has_any_description = True
            all_descriptions_text += f"--- 第 {page_num} 页：{title} ---\n{content}\n\n"
        else:
            all_descriptions_text += (
                f"--- 第 {page_num} 页：{title} ---\n(当前没有内容)\n\n"
            )

    if not has_any_description:
        all_descriptions_text = (
            "当前所有页面的描述：\n\n(当前没有内容，需要基于大纲生成新的描述)\n\n"
        )

    prompt = f"""\
You are a helpful assistant that modifies PPT page descriptions based on user requirements.
{original_input_text}{outline_text}
{all_descriptions_text}
{previous_req_text}
**用户现在提出新的要求：{user_requirement}**

请根据用户的要求修改和调整所有页面的描述。你可以：
- 修改页面标题和内容
- 调整页面文字的详细程度
- 添加或删除要点
- 调整描述的结构和表达
- 确保所有页面描述都符合用户的要求
- 如果当前没有内容，请根据大纲和用户要求创建新的描述

请为每个页面生成修改后的描述，格式如下：

页面标题：[页面标题]

页面文字：
- [要点1]
- [要点2]
...
其他页面素材（如果有请加上，包括markdown图片链接等）

提示：如果参考文件中包含以 /files/ 开头的本地文件URL图片（例如 /files/mineru/xxx/image.png），请将这些图片以markdown格式输出，例如：![图片描述](/files/mineru/xxx/image.png)，而不是作为普通文本。

请返回一个 JSON 数组，每个元素是一个字符串，对应每个页面的修改后描述（按页面顺序）。

示例输出格式：
[
    "页面标题：人工智能的诞生\\n页面文字：\\n- 1950 年，图灵提出\\"图灵测试\\"...",
    "页面标题：AI 的发展历程\\n页面文字：\\n- 1950年代：符号主义...",
    ...
]

现在请根据用户要求修改所有页面描述，只输出 JSON 数组，不要包含其他文字。
{get_language_instruction(language)}
"""

    final_prompt = files_xml + prompt
    logger.debug(f"[get_descriptions_refinement_prompt] Final prompt:\n{final_prompt}")
    return final_prompt


def get_restyle_prompt(
    page_index: int,
    total_pages: int,
    num_style_refs: int = 1,
    custom_prompt: str = "",
) -> str:
    """
    Generate prompt for single-page DDI restyle.

    Uses the compose_images pattern with explicit IMAGE N labels.
    The prompt is sent FIRST in the contents list, followed by images in order:
      IMAGE 1..N = [底版.png] base/template references
      IMAGE N+1  = original PPT slide (content source)

    Args:
        page_index: Current page number (1-indexed)
        total_pages: Total number of pages
        num_style_refs: Number of style reference images (default 1)
        custom_prompt: User-provided restyle prompt (optional)

    Returns:
        Formatted prompt string
    """
    # Build image role labels: base/template references first, then original slide.
    image_labels = []
    for i in range(1, num_style_refs + 1):
        img_num = i
        if num_style_refs == 1:
            image_labels.append(f"IMAGE {img_num}: [底版.png] base template reference")
        else:
            image_labels.append(f"IMAGE {img_num}: [底版.png] base template reference #{i}")
    original_image_num = num_style_refs + 1
    image_labels.append(f"IMAGE {original_image_num}: Original PPT slide (content source)")

    image_section = "\n".join(image_labels)
    template_ref_note = (
        "IMAGE 1 is the base/style reference. Treat it as [底版.png]."
        if num_style_refs == 1
        else f"IMAGE 1..{num_style_refs} are base/style references. Treat the best matching DDI base template as [底版.png]."
    )

    custom_prompt_text = (custom_prompt or "").strip()

    if custom_prompt_text:
        prompt = f"""\
{image_section}

Image role notes:
- {template_ref_note}
- IMAGE {original_image_num} is the original PPT slide. Extract content only.
- In the custom instructions, STYLE_REFERENCE means the base/style reference image(s).
- In the custom instructions, ORIGINAL_SLIDE means IMAGE {original_image_num}, the original PPT slide.

Use the following restyle instructions strictly:
{custom_prompt_text}

Non-negotiable: keep ALL text content exactly the same — every word, number, and punctuation mark must be preserved unchanged.

Page {page_index}/{total_pages}.

Output: 16:9 landscape PPT slide, high resolution, crisp readable text."""

        logger.debug(
            f"[get_restyle_prompt] page {page_index}/{total_pages}, "
            f"style_refs={num_style_refs}, custom_prompt=True"
        )
        return prompt

    prompt = f"""\
{image_section}

Image role notes:
- {template_ref_note}
- IMAGE {original_image_num} is the original PPT slide. Extract content only.

# Role: 资深商业咨询级 PPT 排版与视觉架构师

# Core Objective:
将 IMAGE {original_image_num} 套用参考图的 PPT 模板版式，在严格保留原始页面内容信息与业务逻辑的前提下，重新设计页面的信息架构、视觉层级、空间关系与排版方式，输出具有麦肯锡 / BCG 咨询报告风格的专业商务 PPT 页面。

Page {page_index}/{total_pages}.

# Execution Rules:
1. 模板迁移与背景净化：将参考图的版式框架严格应用到原始页面上；彻底移除原始页面中的背景、页眉、页脚、页码、装饰线条、低质量图形、无意义色块、旧版式视觉干扰元素；仅保留原始文本内容、数据信息、业务逻辑。
2. 零重写内容原则：严格保留 IMAGE {original_image_num} 的全部文字内容与逻辑层级；禁止修改、新增、删除、总结或重写任何文本；仅允许调整布局位置、对齐方式、字号层级和视觉排版。
3. 内容逻辑理解与结构重组：原图只是排版草稿，禁止复刻遮挡块、涂抹痕迹、多余占位符或错位元素；先清点实际文本条目数，基于文本条目生成对应数量的几何区块或层级；完全依据文本间的并列、递进、包含、对比、因果关系重构版式。
4. 标题规范：仅当原图存在标题时应用；若无标题，严禁新增。标题使用微软雅黑 Bold，32pt，DDI 板岩蓝 #3D4F5F，左对齐贴近内容区左侧。
5. 色系规范：禁止继承原图旧颜色。标题/页眉/结构线/主视觉使用 #3D4F5F；强调色/流程箭头/重点标签使用 #F9A825；辅助色仅可使用 #2D72B2 / #E67E22 / #88A02C / #662D7C / #8B9A46；正文 #333333，次要文本 #666666，分割线 #E0E0E0，背景 #FFFFFF。
6. 动态版式选择：时序/流程用线性流程或路线图；两方对比用左右对比；多维对比用矩阵；优先级/层级用分层架构或冰山图；核心主题+分支用辐射或树状；板块概览用网格卡片；漏斗/转化用漏斗图；指标/KPI 用 dashboard；交集关系用维恩图；循环用环形流转；问题到解决方案用桥接过渡；单一叙事用极简要点或图文注解；三项并列用三栏或图标网格。
7. 视觉元素与密度：允许圆形节点、圆角矩形、房屋图标、粗体折线/S形箭头、带序号流程节点、矩阵表格、金字塔、文档图示、等轴测路径图；必须纯扁平化矢量风格。主区块尽量控制在 3–5 个内并容纳全部原文；留白 8%–10%；文字约 40%，结构化图形约 60%；线条一致，严格网格对齐；禁止文字与图形重叠。

# Output Format:
输出优化后的 16:9 高保真商业 PPT 页面。所有视觉块必须清晰、规整，具有明确边界逻辑。"""

    logger.debug(
        f"[get_restyle_prompt] page {page_index}/{total_pages}, "
        f"style_refs={num_style_refs}, custom_prompt=False, ddi_requirements=True"
    )
    return prompt

    prompt = f"""\
{image_section}

Image role notes:
- {template_ref_note}
- IMAGE {original_image_num} is the original PPT slide. Analyze it as the KEY CONTENT source.
- Do not alter source wording, numbers, labels, or chart values while migrating content.

Page {page_index}/{total_pages}.

Generate a 16:9 professional presentation slide image using [底版.png] as the EXCLUSIVE background template.

═══════════════════════════════════════
ROLE: THE ARCHITECT
═══════════════════════════════════════
You are a master visual storyteller producing consulting-grade slides that translate leadership/management concepts into clear visual frameworks. Your aesthetic: Swiss typographic precision, authoritative color restraint, modular structured layouts, high information density with professional clarity.

═══════════════════════════════════════
ABSOLUTE CONSTRAINTS (NON-NEGOTIABLE)
═══════════════════════════════════════

BASE TEMPLATE LOCK: [底版.png] is the SOLE background. ELIMINATE 100% of original PPT visual elements — backgrounds (无论相似与否一律清除), page numbers, footers, headers, decorative lines, borders, watermarks, logos, ornamental graphics.

PURE CONTENT MIGRATION: Migrate ONLY text, data, and charts onto [底版.png]. Zero preservation of source visual styling.

TEXT-GRAPHIC SEPARATION: Body text must occupy dedicated negative space — never overlap, intersect, or be obscured by icons/arrows/shapes. Enforce padding around all text boxes.

NO ADDED CHROME: No slide numbers, footers, headers, or logos beyond elements already baked into [底版.png].

═══════════════════════════════════════
TITLE SPECIFICATION
═══════════════════════════════════════

Font size: EXACTLY 32pt (统一32号)

Color: #3D4F5F on light bg / #FFFFFF on dark bg

Position: Left-aligned at content area's left edge

Spacing: ~1 character width gap from the orange arrow icon's right edge

Alignment: Title's vertical center aligns with the orange arrow icon

Exception: If source has no title, DO NOT invent one

═══════════════════════════════════════
TYPOGRAPHY
═══════════════════════════════════════

Font family: 微软雅黑 (Microsoft YaHei) — both headlines and body

Headlines: Bold, clear hierarchy

Body: Editorial-quality, fully legible

Prohibited: Hand-drawn, organic, or generic computer-generated font styling

═══════════════════════════════════════
COLOR SYSTEM
═══════════════════════════════════════
PRIMARY:

DDI Slate Blue #3D4F5F → titles, headers, structural elements, main graphics

DDI Accent Orange #F9A825 → highlights, CTAs, flow arrows, key tags, title icons, secondary headers

SECONDARY (categorization / visual interest):

Tech Blue #2D72B2 | Energy Orange #E67E22 | Nature Green #88A02C | Quality Purple #662D7C | Olive Green #8B9A46

NEUTRAL:

Body Text #333333 | Secondary Text #666666 | Divider #E0E0E0 | Dark-BG Text #FFFFFF

Background fills: #FFFFFF (with dark text) OR #3D4F5F (with white text)

COLOR HIERARCHY RULE: Equal-status items (parallel viewpoints, peer categories, pyramid layers) MUST receive equal visual weight. Never create false importance via color contrast. Use uniform treatment for equivalent items. Multi-color schemes are permitted for categorization, not implicit ranking.

═══════════════════════════════════════
VISUAL ELEMENTS (FLAT VECTOR ONLY)
═══════════════════════════════════════
Permitted: circular nodes, rounded rectangles (8–10px radius), house/home symbols, bold angular or S-curved arrows, numbered flow nodes (1, 2, 3), matrix/grid tables, pyramids, document mockups, isometric pathway illustrations.
Prohibited: hand-drawn shapes, decorative flourishes, photographic elements, soft curves used decoratively.

═══════════════════════════════════════
DENSITY & COMPOSITION
═══════════════════════════════════════

3–5 key points per slide with supporting details

Margins: 8–10%; maximize usable area

Section dividers: colored header bars (slate blue or orange)

Text-to-visual ratio: ~40% text / ~60% structured graphics

Layering: main concept → sub-bullets → visual icons

Maintain consistent line weights and strict grid alignment

═══════════════════════════════════════
LAYOUT SELECTION
═══════════════════════════════════════
Analyze content and select the single best-fit layout:

Sequential/timeline → linear-progression OR winding-roadmap

A vs B → binary-comparison

Multi-factor compare → comparison-matrix

Priority/levels → hierarchical-layers OR iceberg

Central concept w/ branches → hub-spoke OR tree-branching

Overview tiles → bento-grid

Funnel/conversion → funnel

Metrics/KPIs → dashboard OR key-stat

Overlap/relationships → venn-diagram

Recurring cycle → circular-flow

Problem→solution → bridge

Single narrative → bullet-list OR image-caption

Three peer items → three-columns OR icon-grid

LAYOUT GUARDRAILS — DO NOT:

Use 3-column layouts for 2 items (creates dead columns)

Stack charts below text when side-by-side fits better

Pick image-based layouts without actual images

Use quote layouts for general emphasis (reserve for attributed quotes)

Vary title sizing or icon spacing between slides

Overlap text with shapes/icons/arrows

═══════════════════════════════════════
SLIDE CONTENT
═══════════════════════════════════════
KEY CONTENT: Analyze text, data, and charts from IMAGE {original_image_num}. Migrate ONLY the source content onto [底版.png]. Do not alter source wording, numbers, labels, or chart values.

═══════════════════════════════════════
EXECUTION
═══════════════════════════════════════

Parse KEY CONTENT → identify content type → select optimal layout from the table above.

Apply [底版.png] as background; strip all source chrome.

Lay out title (32pt, slate blue, left-aligned, 1-char gap from orange arrow icon, vertically centered with icon) — only if source has a title.

Place modular content blocks per chosen layout, enforcing equal visual weight for parallel items and clear text/graphic separation.

Render all typography in 微软雅黑, all graphics as flat vector with consistent line weights.

Output: single 16:9 presentation slide image."""

    logger.debug(
        f"[get_restyle_prompt] page {page_index}/{total_pages}, "
        f"style_refs={num_style_refs}, custom_prompt=False"
    )
    return prompt


def get_clean_background_prompt() -> str:
    """
    生成纯背景图的 prompt（去除文字和插画）
    用于从完整的PPT页面中提取纯背景
    """
    prompt = """\
你是一位专业的图片文字&图片擦除专家。你的任务是从原始图片中移除文字和配图，输出一张无任何文字和图表内容、干净纯净的底板图。
<requirements>
- 彻底移除页面中的所有文字、插画、图表。必须确保所有文字都被完全去除。
- 保持原背景设计的完整性（包括渐变、纹理、图案、线条、色块等）。保留原图的文本框和色块。
- 对于被前景元素遮挡的背景区域，要智能填补，使背景保持无缝和完整，就像被移除的元素从来没有出现过。
- 输出图片的尺寸、风格、配色必须和原图完全一致。
- 请勿新增任何元素。
</requirements>

注意，**任意位置的, 所有的**文字和图表都应该被彻底移除，**输出不应该包含任何文字和图表。**
"""
    logger.debug(f"[get_clean_background_prompt] Final prompt:\n{prompt}")
    return prompt


def get_text_attribute_extraction_prompt(content_hint: str = "") -> str:
    """
    生成文字属性提取的 prompt

    提取文字内容、颜色、公式等信息。模型输出的文字将替代 OCR 结果。

    Args:
        content_hint: 文字内容提示（OCR 结果参考），如果提供则会在 prompt 中包含

    Returns:
        格式化后的 prompt 字符串
    """
    prompt = """你的任务是精确识别这张图片中的文字内容和样式，返回JSON格式的结果。

{content_hint}

## 核心任务
请仔细观察图片，精确识别：
1. **文字内容** - 输出你实际看到的文字符号。
2. **颜色** - 每个字/词的实际颜色
3. **空格** - 精确识别文本中空格的位置和数量
4. **公式** - 如果是数学公式，输出 LaTeX 格式

## 注意事项
- **空格识别**：必须精确还原空格数量，多个连续空格要完整保留，不要合并或省略
- **颜色分割**：一行文字可能有多种颜色，按颜色分割成片段，一般来说只有两种颜色。
- **公式识别**：如果片段是数学公式，设置 is_latex=true 并用 LaTeX 格式输出
- **相邻合并**：相同颜色的相邻普通文字应合并为一个片段

## 输出格式
- colored_segments: 文字片段数组，每个片段包含：
  - text: 文字内容（公式时为 LaTeX 格式，如 "x^2"、"\\sum_{{i=1}}^n"）
  - color: 颜色，十六进制格式 "#RRGGBB"
  - is_latex: 布尔值，true 表示这是一个 LaTeX 公式片段（可选，默认 false）

只返回JSON对象，不要包含任何其他文字。
示例输出：
```json
{{
    "colored_segments": [
        {{"text": "·  创新合成", "color": "#000000"}},
        {{"text": "1827个任务环境", "color": "#26397A"}},
        {{"text": "与", "color": "#000000"}},
        {{"text": "8.5万提示词", "color": "#26397A"}},
        {{"text": "突破数据瓶颈", "color": "#000000"}},
        {{"text": "x^2 + y^2 = z^2", "color": "#FF0000", "is_latex": true}}
    ]
}}
```
""".format(content_hint=content_hint)

    # logger.debug(f"[get_text_attribute_extraction_prompt] Final prompt:\n{prompt}")
    return prompt


def get_batch_text_attribute_extraction_prompt(text_elements_json: str) -> str:
    """
    生成批量文字属性提取的 prompt

    新逻辑：给模型提供全图和所有文本元素的 bbox 及内容，
    让模型一次性分析所有文本的样式属性。

    Args:
        text_elements_json: 文本元素列表的 JSON 字符串，每个元素包含：
            - element_id: 元素唯一标识
            - bbox: 边界框 [x0, y0, x1, y1]
            - content: 文字内容

    Returns:
        格式化后的 prompt 字符串
    """
    prompt = f"""你是一位专业的 PPT/文档排版分析专家。请分析这张图片中所有标注的文字区域的样式属性。

我已经从图片中提取了以下文字元素及其位置信息：

```json
{text_elements_json}
```

请仔细观察图片，对比每个文字区域在图片中的实际视觉效果，为每个元素分析以下属性：

1. **font_color**: 字体颜色的十六进制值，格式为 "#RRGGBB"
   - 请仔细观察文字的实际颜色，不要只返回黑色
   - 常见颜色如：白色 "#FFFFFF"、蓝色 "#0066CC"、红色 "#FF0000" 等

2. **is_bold**: 是否为粗体 (true/false)
   - 观察笔画粗细，标题通常是粗体

3. **is_italic**: 是否为斜体 (true/false)

4. **is_underline**: 是否有下划线 (true/false)

5. **text_alignment**: 文字对齐方式
   - "left": 左对齐
   - "center": 居中对齐
   - "right": 右对齐
   - "justify": 两端对齐
   - 如果无法判断，根据文字在其区域内的位置推测

请返回一个 JSON 数组，数组中每个对象对应输入的一个元素（按相同顺序），包含以下字段：
- element_id: 与输入相同的元素ID
- text_content: 文字内容
- font_color: 颜色十六进制值
- is_bold: 布尔值
- is_italic: 布尔值
- is_underline: 布尔值
- text_alignment: 对齐方式字符串

只返回 JSON 数组，不要包含其他文字：
```json
[
    {{
        "element_id": "xxx",
        "text_content": "文字内容",
        "font_color": "#RRGGBB",
        "is_bold": true/false,
        "is_italic": true/false,
        "is_underline": true/false,
        "text_alignment": "对齐方式"
    }},
    ...
]
```
"""

    # logger.debug(f"[get_batch_text_attribute_extraction_prompt] Final prompt:\n{prompt}")
    return prompt


def get_quality_enhancement_prompt(inpainted_regions: list = None) -> str:
    """
    生成画质提升的 prompt
    用于在百度图像修复后，使用生成式模型提升整体画质

    Args:
        inpainted_regions: 被修复区域列表，每个区域包含百分比坐标：
            - left, top, right, bottom: 相对于图片宽高的百分比 (0-100)
            - width_percent, height_percent: 区域宽高占图片的百分比
    """
    import json

    # 构建区域信息
    regions_info = ""
    if inpainted_regions and len(inpainted_regions) > 0:
        regions_json = json.dumps(inpainted_regions, ensure_ascii=False, indent=2)
        regions_info = f"""
以下是被抹除工具处理过的具体区域（共 {len(inpainted_regions)} 个矩形区域），请重点修复这些位置：

```json
{regions_json}
```

坐标说明（所有数值都是相对于图片宽高的百分比，范围0-100%）：
- left: 区域左边缘距离图片左边缘的百分比
- top: 区域上边缘距离图片上边缘的百分比
- right: 区域右边缘距离图片左边缘的百分比
- bottom: 区域下边缘距离图片上边缘的百分比
- width_percent: 区域宽度占图片宽度的百分比
- height_percent: 区域高度占图片高度的百分比

例如：left=10 表示区域从图片左侧10%的位置开始。
"""

    prompt = f"""\
你是一位专业的图像修复专家。这张ppt页面图片刚刚经过了文字/对象抹除操作，抹除工具在指定区域留下了一些修复痕迹，包括：
- 色块不均匀、颜色不连贯
- 模糊的斑块或涂抹痕迹
- 与周围背景不协调的区域，比如不和谐的渐变色块
- 可能的纹理断裂或图案不连续
{regions_info}
你的任务是修复这些抹除痕迹，让图片看起来像从未有过对象抹除操作一样自然。

要求：
- **重点修复上述标注的区域**：这些区域刚刚经过抹除处理，需要让它们与周围背景完美融合
- 保持纹理、颜色、图案的连续性
- 提升整体画质，消除模糊、噪点、伪影
- 保持图片的原始构图、布局、色调风格
- 禁止添加任何文字、图表、插画、图案、边框等元素
- 除了上述区域，其他区域不要做任何修改，保持和原图像素级别地一致。
- 输出图片的尺寸必须与原图一致

请输出修复后的高清ppt页面背景图片，不要遗漏修复任何一个被涂抹的区域。
"""
    #     prompt = f"""
    # 你是一位专业的图像修复专家。请你修复上传的图像，去除其中的涂抹痕迹，消除所有的模糊、噪点、伪影，输出处理后的高清图像，其他区域保持和原图**完全相同**，颜色、布局、线条、装饰需要完全一致.
    # {regions_info}
    # """
    return prompt
