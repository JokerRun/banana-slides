# Restyle Edit Conversation Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `restyle` 工作流的编辑阶段稳定注入“基线上下文 + 本轮增量上下文”，显著降低多轮编辑风格漂移，并保持非-restyle 流程零回归。

**Architecture:** 采用“先建模、再编排、后接入”三层方案：先补齐 `Page` 的基线 prompt 快照字段与配置上限，再实现 provider-agnostic 的 conversation context 选择与裁剪算法，最后接入 `page edit -> task -> ai_service -> provider` 链路并增加一次 fallback。Gemini 作为首个 conversation adapter，其他 provider 默认走 legacy flattened path。

**Tech Stack:** Flask, SQLAlchemy, Alembic, Pillow, Google GenAI SDK, Pytest, UV

---

## Scope Check

本 spec 仅覆盖一个子系统：`restyle` 编辑时的上下文组装与调用协议。无须拆分多份 implementation plan。

## Implementation Discipline

1. 全程按 `@superpowers:test-driven-development` 执行（先失败测试，再最小实现）。
2. 完成前按 `@superpowers:verification-before-completion` 执行验证命令并保留输出证据。
3. 每个 Task 单独 commit，避免大杂烩。

## File Structure

### Create

- `backend/migrations/versions/020_add_restyle_base_prompt_snapshot_to_pages.py`（新增 `pages.restyle_base_prompt_snapshot`）
- `backend/services/restyle_edit_context.py`（restyle 编辑上下文构建、裁剪、degrade/fail 判定）
- `backend/tests/unit/test_restyle_edit_context.py`（上下文选择算法、最低可执行集合、裁剪与重建测试）
- `backend/tests/unit/test_genai_image_provider_conversation.py`（Gemini conversation adapter 单测）
- `backend/tests/integration/test_restyle_edit_context_flow.py`（restyle 编辑链路集成测试）

### Modify

- `backend/models/page.py`（新增快照字段 + `to_dict` 输出）
- `backend/services/ai_providers/image/base.py`（provider capability 与 conversation 接口）
- `backend/services/ai_providers/image/genai_provider.py`（实现 `supports_conversation_contents` 与 conversation 调用）
- `backend/services/ai_providers/image/openai_provider.py`（显式 `supports_conversation_contents=False`）
- `backend/services/ai_service.py`（新增 restyle edit conversation 调用路径与一次 fallback）
- `backend/services/task_manager.py`（restyle 首轮快照落库；编辑任务接入 conversation context）
- `backend/controllers/page_controller.py`（restyle 编辑入口最小参数编排与错误码透传）
- `backend/config.py`（`RESTYLE_EDIT_MAX_PRUNABLE_IMAGES`、`RESTYLE_EDIT_MAX_TOTAL_IMAGES`）
- `backend/tests/integration/test_restyle_flow.py`（补首轮快照持久化断言）

### Test Matrix Mapping

- 单元：context builder、provider adapter、fallback classifier。
- 集成：restyle edit conversation 首选路径、legacy fallback 路径、结构图缺失失败路径、non-restyle 不受影响。
- 回归：已有 `restyle_generate`、`image version` 行为保持。

---

### Task 1: 数据模型与配置基线落地

**Files:**
- Create: `backend/migrations/versions/020_add_restyle_base_prompt_snapshot_to_pages.py`
- Modify: `backend/models/page.py`
- Modify: `backend/config.py`
- Test: `backend/tests/unit/test_restyle_edit_context.py`

- [ ] **Step 1: 写失败测试（Page 支持快照字段 + 配置默认值）**

```python
def test_page_has_restyle_base_prompt_snapshot_field(db_session):
    from models import Page
    page = Page(project_id='p1', order_index=0, restyle_base_prompt_snapshot='BASE PROMPT')
    assert page.restyle_base_prompt_snapshot == 'BASE PROMPT'


def test_restyle_edit_caps_default_from_config():
    from config import Config
    assert Config.RESTYLE_EDIT_MAX_PRUNABLE_IMAGES == 6
    assert Config.RESTYLE_EDIT_MAX_TOTAL_IMAGES == 8
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_restyle_edit_context.py -k "snapshot_field or caps_default" -v`
Expected: FAIL（字段/配置未定义）。

- [ ] **Step 3: 最小实现模型字段与序列化输出**

```python
# backend/models/page.py
restyle_base_prompt_snapshot = db.Column(db.Text, nullable=True)

data['restyle_base_prompt_snapshot'] = self.restyle_base_prompt_snapshot
```

- [ ] **Step 4: 添加 Alembic migration（仅新增 nullable 列）**

```python
op.add_column('pages', sa.Column('restyle_base_prompt_snapshot', sa.Text(), nullable=True))
```

- [ ] **Step 5: 增加配置默认值**

```python
RESTYLE_EDIT_MAX_PRUNABLE_IMAGES = int(os.getenv('RESTYLE_EDIT_MAX_PRUNABLE_IMAGES', '6'))
RESTYLE_EDIT_MAX_TOTAL_IMAGES = int(os.getenv('RESTYLE_EDIT_MAX_TOTAL_IMAGES', '8'))
```

- [ ] **Step 6: 再跑测试确认通过**

Run: `uv run pytest backend/tests/unit/test_restyle_edit_context.py -k "snapshot_field or caps_default" -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/migrations/versions/020_add_restyle_base_prompt_snapshot_to_pages.py backend/models/page.py backend/config.py backend/tests/unit/test_restyle_edit_context.py
git commit -m "feat(restyle): add base prompt snapshot field and restyle edit caps"
```

### Task 2: 图片 Provider 能力声明与 Gemini Conversation Adapter

**Files:**
- Modify: `backend/services/ai_providers/image/base.py`
- Modify: `backend/services/ai_providers/image/genai_provider.py`
- Modify: `backend/services/ai_providers/image/openai_provider.py`
- Test: `backend/tests/unit/test_genai_image_provider_conversation.py`

- [ ] **Step 1: 写失败测试（capability flag + conversation 调用）**

```python
def test_genai_provider_supports_conversation_contents():
    provider = GenAIImageProvider(api_key='k')
    assert provider.supports_conversation_contents is True


def test_genai_generate_image_from_conversation_calls_generate_content(mocker):
    provider = GenAIImageProvider(api_key='k')
    mocker.patch.object(provider.client.models, 'generate_content', return_value=fake_response_with_image())
    result = provider.generate_image_from_conversation(contents=[{'role': 'user', 'parts': [{'text': 'x'}]}])
    assert result is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_genai_image_provider_conversation.py -v`
Expected: FAIL（接口尚未存在）。

- [ ] **Step 3: 在基类加入 capability 与 conversation 接口（默认不支持）**

```python
class ImageProvider(ABC):
    supports_conversation_contents = False

    def generate_image_from_conversation(...):
        raise NotImplementedError("Conversation contents not supported by this provider")
```

- [ ] **Step 4: 在 GenAI provider 实现 conversation 调用**

```python
class GenAIImageProvider(ImageProvider):
    supports_conversation_contents = True

    def generate_image_from_conversation(self, contents, aspect_ratio='16:9', resolution='2K', thinking_level='none'):
        response = self.client.models.generate_content(model=self.model, contents=contents, config=...)
        return self._extract_last_image(response)
```

- [ ] **Step 5: 在 OpenAI provider 显式声明不支持 conversation**

```python
class OpenAIImageProvider(ImageProvider):
    supports_conversation_contents = False
```

- [ ] **Step 6: 再跑测试确认通过**

Run: `uv run pytest backend/tests/unit/test_genai_image_provider_conversation.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/services/ai_providers/image/base.py backend/services/ai_providers/image/genai_provider.py backend/services/ai_providers/image/openai_provider.py backend/tests/unit/test_genai_image_provider_conversation.py
git commit -m "feat(restyle): add image provider conversation capability for gemini"
```

### Task 3: Restyle 编辑上下文构建器（选择、裁剪、degrade）

**Files:**
- Create: `backend/services/restyle_edit_context.py`
- Modify: `backend/services/prompts.py`（如需提取共用 baseline 文本模板）
- Test: `backend/tests/unit/test_restyle_edit_context.py`

- [ ] **Step 1: 写失败测试（最低可执行集合 + 裁剪算法 + snapshot 重建）**

```python
def test_minimum_executable_set_original_only():
    result = build_restyle_edit_context(..., original_slide='a.png', current_selected=None)
    assert result.executable is True
    assert result.degraded_context is True


def test_context_image_limit_exceeded_raises_when_total_cap_too_small():
    with pytest.raises(ContextImageLimitExceeded):
        build_restyle_edit_context(..., total_cap=1)


def test_reconstruct_snapshot_uses_best_effort_metadata_when_missing():
    prompt = reconstruct_base_prompt_snapshot(page, project)
    assert 'Page' in prompt


def test_missing_both_structural_images_raises_recoverable_error():
    with pytest.raises(MissingStructuralImagesError):
        build_restyle_edit_context(..., original_slide=None, current_selected=None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_restyle_edit_context.py -k "minimum_executable or limit_exceeded or reconstruct_snapshot" -v`
Expected: FAIL。

- [ ] **Step 3: 实现上下文数据结构与错误类型**

```python
@dataclass
class RestyleEditContext:
    conversation_contents: list
    legacy_prompt: str
    legacy_ref_images: list
    degraded_context: bool
    baseline_images_count: int
    current_images_count: int


class MissingStructuralImagesError(ValueError):
    """Recoverable: both original slide and current selected version are unavailable."""
```

- [ ] **Step 4: 实现 deterministic 选择/裁剪算法（2A + 1C 规则）**

```python
# anchors first, reserve >=1 style ref when available, then fill extras newest-first
selected_prunables = select_prunable_images(style_refs, current_extras, prunable_cap)
final_images = anchors + selected_prunables
if len(final_images) > effective_total_cap:
    raise ContextImageLimitExceeded(...)

if not anchors:
    raise MissingStructuralImagesError("Missing both original slide and current selected version")
```

- [ ] **Step 5: 实现 snapshot 缺失时 best-effort 重建**

```python
snapshot = page.restyle_base_prompt_snapshot or get_restyle_prompt(
    page_index=page.order_index + 1,
    total_pages=total_pages,
    num_style_refs=max(1, len(style_ref_paths)),
    custom_prompt=project.restyle_prompt or '',
    preset_base_body=get_style_preset_prompt_text(project.style_preset_id, "restyle")
    if project.style_preset_id
    else None,
)
```

- [ ] **Step 6: 再跑测试确认通过**

Run: `uv run pytest backend/tests/unit/test_restyle_edit_context.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/services/restyle_edit_context.py backend/tests/unit/test_restyle_edit_context.py backend/services/prompts.py
git commit -m "feat(restyle): add edit context builder with deterministic pruning and degrade rules"
```

### Task 4: 接入编辑链路（Controller -> Task -> AIService）

**Files:**
- Modify: `backend/controllers/page_controller.py`
- Modify: `backend/services/task_manager.py`
- Modify: `backend/services/ai_service.py`
- Test: `backend/tests/integration/test_restyle_edit_context_flow.py`

- [ ] **Step 1: 写失败集成测试（restyle 优先走 conversation，non-restyle 保持 legacy）**

```python
def test_restyle_edit_uses_conversation_mode(client, mocker):
    mocker.patch('services.ai_providers.image.genai_provider.GenAIImageProvider.supports_conversation_contents', True)
    # trigger /edit/image on restyle project
    # assert logs or spy call includes conversation_attempted=True


def test_non_restyle_edit_keeps_legacy_path(client, mocker):
    # trigger /edit/image on idea project
    # assert legacy generate_image called


def test_restyle_edit_fails_fast_when_both_structural_images_missing(client):
    # setup restyle page with missing original + missing current
    # assert task failed with recoverable error details
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_restyle_edit_context_flow.py -v`
Expected: FAIL。

- [ ] **Step 3: 在 AIService 新增 restyle edit 执行入口（含一次 fallback）**

```python
def edit_restyle_image_with_context(self, context, aspect_ratio, resolution):
    if self.image_provider.supports_conversation_contents:
        try:
            return self.image_provider.generate_image_from_conversation(...)
        except Exception as e:
            if is_retryable_conversation_error(e):
                return self.image_provider.generate_image(prompt=context.legacy_prompt, ref_images=context.legacy_ref_images, ...)
            raise
    return self.image_provider.generate_image(prompt=context.legacy_prompt, ref_images=context.legacy_ref_images, ...)


def _is_retryable_conversation_error(self, err: Exception) -> bool:
    # retry only format/schema errors:
    # - http 400/422
    # - sdk validation mentioning contents/parts/inline_data/schema/invalid_argument
    # do NOT retry timeout/5xx/internal errors
    ...
```

- [ ] **Step 4: 在 `edit_page_image_task` 接入 context builder（仅 restyle 项目）**

```python
if project.creation_type == 'restyle':
    ctx = build_restyle_edit_context(...)
    image = ai_service.edit_restyle_image_with_context(ctx, aspect_ratio, resolution)
else:
    image = ai_service.edit_image(...)
```

- [ ] **Step 4.1: 增加 retryable classifier 单测（避免 fallback 语义漂移）**

Run: `uv run pytest backend/tests/unit/test_restyle_edit_context.py -k "retryable_conversation_error" -v`
Expected: PASS（`400/422/schema` 为 True，`timeout/5xx` 为 False）。

- [ ] **Step 5: 增加结构化日志字段**

```python
logger.info("restyle_edit_context", extra={
    'context_mode': context_mode,
    'conversation_attempted': conversation_attempted,
    'baseline_images_count': ctx.baseline_images_count,
    'current_images_count': ctx.current_images_count,
    'degraded_context': ctx.degraded_context,
    'provider_fallback': provider_fallback,
    'snapshot_present': bool(page.restyle_base_prompt_snapshot),
})
```

- [ ] **Step 6: 再跑集成测试确认通过**

Run: `uv run pytest backend/tests/integration/test_restyle_edit_context_flow.py -v`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/controllers/page_controller.py backend/services/task_manager.py backend/services/ai_service.py backend/tests/integration/test_restyle_edit_context_flow.py
git commit -m "feat(restyle): wire conversation context into page edit pipeline with single fallback"
```

### Task 5: 首轮 Restyle 快照持久化与旧项目兼容

**Files:**
- Modify: `backend/services/task_manager.py`
- Modify: `backend/tests/integration/test_restyle_flow.py`
- Modify: `backend/tests/integration/test_restyle_edit_context_flow.py`

- [ ] **Step 1: 写失败测试（首轮成功后快照写入，后续不覆盖）**

```python
def test_restyle_generate_persists_base_prompt_snapshot_once(...):
    # first generate
    assert page.restyle_base_prompt_snapshot
    first_value = page.restyle_base_prompt_snapshot
    # second generate/edit
    assert page.restyle_base_prompt_snapshot == first_value
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_restyle_flow.py -k snapshot -v`
Expected: FAIL。

- [ ] **Step 3: 在 `restyle_images_task` 成功保存图片后写入快照（仅为空时）**

```python
if not page_obj.restyle_base_prompt_snapshot:
    page_obj.restyle_base_prompt_snapshot = prompt
    db.session.commit()
```

- [ ] **Step 4: 补旧项目兼容测试（无 snapshot 也可编辑）**

Run: `uv run pytest backend/tests/integration/test_restyle_edit_context_flow.py -k "no_snapshot" -v`
Expected: PASS（走重建 + degrade）。

- [ ] **Step 5: Commit**

```bash
git add backend/services/task_manager.py backend/tests/integration/test_restyle_flow.py backend/tests/integration/test_restyle_edit_context_flow.py
git commit -m "feat(restyle): persist first-pass prompt snapshot and keep backward compatibility"
```

### Task 6: 验证、回归、收尾

**Files:**
- Modify: `backend/tests/unit/test_genai_image_provider_conversation.py`（若需补边界）
- Modify: `backend/tests/unit/test_restyle_edit_context.py`（若需补边界）
- Modify: `backend/tests/integration/test_restyle_edit_context_flow.py`（若需补边界）

- [ ] **Step 1: 跑定向单测套件**

Run: `uv run pytest backend/tests/unit/test_genai_image_provider_conversation.py backend/tests/unit/test_restyle_edit_context.py -k "retryable or missing_both_structural or reconstruct_snapshot or pruning" -v`
Expected: PASS。

- [ ] **Step 2: 跑定向集成套件**

Run: `uv run pytest backend/tests/integration/test_restyle_edit_context_flow.py backend/tests/integration/test_restyle_flow.py -v`
Expected: PASS。

- [ ] **Step 3: 跑编辑主链路回归**

Run: `uv run pytest backend/tests/integration/test_full_workflow.py -k "image or edit or restyle" -v`
Expected: PASS（或明确 skip 原因）。

- [ ] **Step 4: 做一次日志验收检查（非自动化）**

Run: `uv run pytest backend/tests/integration/test_restyle_edit_context_flow.py -k "conversation_mode" -s -v`
Expected: 输出中可见 `conversation_attempted`、`context_mode`、`provider_fallback` 相关日志。

- [ ] **Step 5: 最终 Commit（若 Task 1-5 已独立提交则此步可跳过）**

```bash
git add backend
git commit -m "test(restyle): finalize conversation-context coverage and regression evidence"
```

---

## Rollout Notes

1. 先上线 migration + model 字段，再上线编辑链路改造，避免旧代码读取新字段失败。
2. 若生产 provider 非 Gemini，功能将自动走 legacy，不会中断请求。
3. `CONTEXT_IMAGE_LIMIT_EXCEEDED` 出现率若偏高，优先调大 `RESTYLE_EDIT_MAX_PRUNABLE_IMAGES` 而非放松结构锚点约束。

## Verification Checklist

1. `restyle` 编辑请求日志中 `conversation_attempted=true`（Gemini 场景）。
2. fallback 时 `provider_fallback=true` 且仅一次重试。
3. 非-restyle 编辑路径不出现 `restyle_edit_context` 相关日志字段。
4. 版本历史 `page_image_versions` 递增且 `set-current` 行为不变。
