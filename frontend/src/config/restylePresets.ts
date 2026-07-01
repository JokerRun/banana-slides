export interface RestylePreset {
  id: string;
  legacyIds: string[];
  name: string;
  description: string;
  prompt: string;
  imageUrl: string;
  sha256: string;
  version: string;
}

export const DDI_RESTYLE_PROMPT = `# Role: 资深商业咨询级 PPT 排版与视觉架构师

# Inputs:
- STYLE_REFERENCE = 标准 PPT 模板 / 风格参考图
- ORIGINAL_SLIDE = 待优化的原始 PPT 页面


# Core Objective:
ORIGINAL_SLIDE 套用 STYLE_REFERENCE 的 PPT 模板版式，在严格保留 ORIGINAL_SLIDE 内容信息与业务逻辑的前提下，重新设计页面的信息架构、视觉层级、空间关系与排版方式，输出具有麦肯锡 / BCG 咨询报告风格的专业商务 PPT 页面。



# Execution Rules (Strict Compliance Required):

## 1. 模板迁移与背景净化 (Highest Priority)
- 将 STYLE_REFERENCE 的版式框架，严格应用到 ORIGINAL_SLIDE 上
- 彻底移除 ORIGINAL_SLIDE 中的原有背景、页眉、页脚、页码、装饰线条、低质量图形、无意义色块、旧版式的视觉干扰元素。
- 仅保留 ORIGINAL_SLIDE 的原始文本内容、数据信息、业务逻辑。



## 2. 零重写内容原则 (Zero Text Modification)
- 严格保留 ORIGINAL_SLIDE 的全部文字内容与逻辑层级。 
- 绝对禁止：修改、新增、删除、总结或重写任何文本。 
- 仅允许调整内容的布局位置、对齐方式、字号层级和视觉排版。


## 3. 内容逻辑理解与结构重组 (Structural Override - Critical)
- 强制视觉去噪：ORIGINAL_SLIDE 为排版草稿。绝对禁止复刻原图中的遮挡块、涂抹痕迹、多余占位符或错位元素。
- 文本驱动计数：强制执行【文本与区块的 1:1 映射】。彻底抛弃原图的物理图形个数，必须先清点实际的“文本条目数”，严格基于该数字生成对应数量的几何区块或层级。
- 版式彻底重构：打破原图的视觉外壳。完全依据文本间的内在关系（如并列、递进、包含），重新生成逻辑自洽、排列规整的全新版式。


## 4. 标题格式与定位规范
- 条件触发：仅当 ORIGINAL_SLIDE 原本存在标题时应用；若无标题，严禁新增。 
- 字体规范：微软雅黑 Bold，32pt，板岩蓝 (#3D4F5F)。 
- 布局关系：左对齐贴近内容区左侧。


## 5. 色系规范 (Strict Color Palette)
- 强制色系统一：禁止继承 ORIGINAL_SLIDE 原有颜色。所有图形、金字塔、流程图、图标、模块底色、描边与强调元素，必须重新着色并统一替换为以下规范色系。
- 禁止出现色池外颜色：仅允许使用以下颜色及其透明度/明度变化，严禁新增其他色系。
- 【主色调】：
     - 标题/页眉/结构线/主视觉：DDI 板岩蓝 (#3D4F5F)
     - 强调色/行动按钮/流程箭头/重点标签：DDI 点缀橙 (#F9A825) 
- 【辅助分类与点缀色】（用于图表或多模块区分，允许使用低透明度作为模块底色）： 
     - 科技蓝 (#2D72B2) | 活力橙 (#E67E22) | 自然绿 (#88A02C) | 品质紫 (#662D7C) | 橄榄绿 (#8B9A46) 
- 【基础文本与背景】： 
     - 正文：#333333 | 次要文本：#666666 | 分割线：#E0E0E0 | 背景色：纯白 #FFFFFF


## 6. 动态版式选择逻辑 (Layout Selection Guide)
必须先理解 ORIGINAL_SLIDE 的真实业务逻辑，再决定适配版式：
- 时序 / 流程类 → 线性流程 / 路线图布局
- 两方对比类 → 二元左右对比版式
- 多维度对比 → 对比矩阵
- 优先级 / 层级架构 → 分层架构 / 冰山图
- 核心主题 + 分支内容 → 辐射布局 / 树状分支
- 板块概览 → 网格卡片 (Grid Cards)
- 漏斗 / 转化流程 → 漏斗图
- 数据指标 / 关键绩效 → 数据面板 / 重点数据栏 (Dashboard)
- 交集 / 关联关系 → 维恩图
- 循环流程 → 环形流转图
- 问题 →  解决方案 → 衔接过渡版式
- 单一叙事内容 → 极简要点列表 / 图文注解
- 三项并列内容 → 三栏纵向布局 / 图标网格


## 7. 视觉元素与排版密度限制
- 【允许的图形】：圆形节点、圆角矩形（圆角 8–10px）、房屋图标、粗体折线 / S 形箭头、带序号流程节点（1/2/3）、矩阵表格、金字塔、文档图示、等轴测路径图。且必须为纯粹的扁平化矢量风格。
- 【视觉区块化】：通过岩蓝/橙色通栏色块作为区域标题栏进行分区分割。将原文内容归类，视觉主区块尽量控制在 3-5 个内（必须容纳所有原文）。
- 【空间与网格】：页面整体留白保持 8%–10%；文字占比约 40%，结构化图形约 60%。所有线条粗细必须保持一致，严格遵循不可见的网格对齐规则。
- 【层级递进】：遵循“核心概念 → 分项要点 → 配套图标”的视觉递进逻辑。
- 【智能补偿】：若 ORIGINAL_SLIDE 文本表达缺乏视觉支撑，需深度理解文字语义，自动生成并补充与内容高度匹配的“扁平化图标”或“配图”。补充的图形必须视觉语义准确，且边缘清晰、无复杂的融合式背景。图标间距必须保持统一，且严禁与文字重叠。



# Output Format: 
请输出优化后的 16:9 高保真商业 PPT 页面。确保所有视觉块清晰、规整，具有明确的边界逻辑。`;

export const RESTYLE_PRESETS: RestylePreset[] = [
  {
    id: 'ddi-standard',
    legacyIds: ['ddi', 'ddi-standard', 'ddi-restyle-v2'],
    name: 'DDI Restyle',
    description: '使用 DDI 底版和需求文档 restyle prompt 的标准化风格转换模板。',
    imageUrl: '/api/presets/ddi-standard/image',
    sha256: 'f7f14464afd72793df3b68e5c06a91a32b4329c24d0886a7a557dd01bdcc112c',
    version: '2026-07-01',
    prompt: DDI_RESTYLE_PROMPT,
  },
];

export const getRestylePresetById = (id: string): RestylePreset | undefined => {
  return RESTYLE_PRESETS.find((preset) => preset.id === id || preset.legacyIds.includes(id));
};
