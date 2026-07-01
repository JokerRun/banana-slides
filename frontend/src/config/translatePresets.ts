export interface TranslatePreset {
  id: string;
  name: string;
  description: string;
  prompt: string;
  stylePresetId?: string;
}

export interface TargetLanguage {
  code: string;
  name: string;
  nativeName: string;
}

export const TARGET_LANGUAGES: TargetLanguage[] = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'zh', name: 'Chinese', nativeName: '中文' },
  { code: 'ja', name: 'Japanese', nativeName: '日本語' },
  { code: 'ko', name: 'Korean', nativeName: '한국어' },
  { code: 'es', name: 'Spanish', nativeName: 'Español' },
  { code: 'fr', name: 'French', nativeName: 'Français' },
  { code: 'de', name: 'German', nativeName: 'Deutsch' },
  { code: 'pt', name: 'Portuguese', nativeName: 'Português' },
  { code: 'ru', name: 'Russian', nativeName: 'Русский' },
  { code: 'it', name: 'Italian', nativeName: 'Italiano' },
  { code: 'ar', name: 'Arabic', nativeName: 'العربية' },
  { code: 'custom', name: 'Custom', nativeName: '其他语言' },
];

export const PURE_TRANSLATION_PROMPT = `# Role: 专业PPT翻译与排版保真专家

# Core Objective:
将原始PPT页面中的所有可见文本精准翻译为目标语言，同时严格保留原始页面的版式布局、视觉层次、图片、图表、Logo、背景及所有非文本元素。

# Execution Rules (Strict Compliance Required):

## 1. 精准翻译原则
- 识别并翻译所有可见文本内容（标题、正文、标签、按钮文字、图表标注等）
- 翻译必须准确、专业，保持原文的语气和语境
- 不得添加、删除、总结或改写原文内容

## 2. 版式锁定原则 (CRITICAL)
- 必须100%保留原始页面的版式布局、空间关系、视觉层次
- 保持文本框的原始位置和大小，确保翻译后的文本在原始区域内恰当显示
- 保持字体大小、颜色、粗细等文本样式的一致性
- 保持图表、图片、图标、Logo等视觉元素的原始位置和样式
- 保持背景、色块、装饰线条等所有非文本元素的完整性

## 3. 文本适配原则
- 翻译后的文本应当适配原始文本框区域，避免明显的溢出或截断
- 如果目标语言的文本长度显著不同，可适当调整字号或行距，但必须保持视觉平衡
- 保持文本的对齐方式与原始一致

## 4. 视觉元素保护
- 严禁修改、移动或删除任何图片、图表、Logo、图标、背景图案
- 严禁修改配色方案、渐变效果、阴影效果等视觉样式

# Output:
输出翻译后的16:9高保真商业PPT页面，所有文本已翻译，版式、视觉元素和原始页面保持一致。`;

export const TRANSLATION_WITH_RESTYLE_PROMPT = `# Role: 专业PPT翻译与视觉重构专家

# Core Objective:
将原始PPT页面中的所有可见文本精准翻译为目标语言，同时应用目标风格参考图的设计规范，在保持内容逻辑的前提下重新设计视觉呈现。

# Execution Rules (Strict Compliance Required):

## 1. 精准翻译原则
- 识别并翻译所有可见文本内容（标题、正文、标签、按钮文字、图表标注等）
- 翻译必须准确、专业，保持原文的语气和语境
- 不得添加、删除、总结或改写原文内容

## 2. 风格应用原则
- 深度解析风格参考图的版式框架、色彩系统、字体规范、图形语言
- 将翻译后的内容迁移到目标风格模板中，保持内容逻辑和视觉层级
- 应用风格参考图的配色方案和视觉元素规范

## 3. 版式重构原则
- 基于翻译后的文本内容，结合风格参考图的设计规范，重新设计页面信息架构
- 保持内容逻辑的完整性和清晰性
- 确保翻译后的内容在新的风格框架下显示得当、美观

## 4. 视觉元素规范
- 使用风格参考图中定义的配色、字体、图形风格
- 保持图表、数据可视化等元素的专业性和可读性
- 保持16:9比例的高清输出

# Output:
输出翻译并重构后的16:9高保真商业PPT页面，所有文本已翻译为目标语言，应用了目标风格的设计规范。`;

export const TRANSLATE_PRESETS: TranslatePreset[] = [
  {
    id: 'pure-translation',
    name: '纯翻译模式',
    description: '仅翻译文本内容，完全保留原始PPT的版式、风格和视觉元素。',
    prompt: PURE_TRANSLATION_PROMPT,
  },
  {
    id: 'translation-restyle',
    name: '翻译+风格转换',
    description: '翻译文本内容，同时应用风格参考图的设计规范，重新设计视觉呈现。',
    prompt: TRANSLATION_WITH_RESTYLE_PROMPT,
    stylePresetId: 'ddi-standard',
  },
];

export const getTranslatePresetById = (id: string): TranslatePreset | undefined => {
  return TRANSLATE_PRESETS.find((preset) => preset.id === id);
};

export const getTargetLanguageByCode = (code: string): TargetLanguage | undefined => {
  return TARGET_LANGUAGES.find((lang) => lang.code === code);
};
