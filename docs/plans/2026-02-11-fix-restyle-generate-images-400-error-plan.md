---
title: "fix: Restyle 项目在 SlidePreview 生成/重生成图片 400 错误"
type: fix
date: 2026-02-11
---

# 🐛 fix: Restyle 项目在 SlidePreview 点击"生成此页/批量生成"返回 400

## Overview

Restyle 项目从首页提交后，后台 `restyle_images_task()` 异步完成了 7/7 页的风格转换。但当用户在 SlidePreview 中：
1. 初次进入看到"尚未生成图片"然后点击"生成此页"
2. 或想重新生成某页

都会触发 `POST /api/projects/{id}/generate/images` → **400 错误**: "请先上传模板图片或添加风格描述。"

## Root Cause Analysis

**两个问题叠加**:

### Bug 1: 后端验证不区分项目类型

```python
# backend/controllers/project_controller.py L702-711
ref_image_path = file_service.get_template_path(project_id)   # restyle 没有 template → None
if not ref_image_path and not project.template_style:          # restyle 也没有 template_style → None
    return bad_request("请先上传模板图片或添加风格描述。")       # ← 400!
```

Restyle 项目的风格信息存在 `style_ref_image_paths` + `brand_guidelines`，而非 `template_image_path` + `template_style`。验证逻辑没有考虑这一点。

### Bug 2: 后端对 restyle 项目仍调用 generate_images_task

即使通过了验证，L749-751 无条件调用 `generate_images_task`（从描述生成图片），而非 `restyle_images_task`（从原始slide重绘）：

```python
# L749-751 — 不区分项目类型
task_manager.submit_task(
    task.id,
    generate_images_task,    # ❌ 应该根据 creation_type 选择
    ...
)
```

### Bug 3: 前端 SlidePreview 不轮询 restyle 初始任务

Home.tsx 调用 `restyleGenerate()` 后立即导航到 `/preview`，但 `restyleGenerate` 返回的 `task_id` **未被传递**到 SlidePreview。SlidePreview 的 `syncProject()` 只拉取项目数据，不知道有正在进行的 restyle 任务要轮询。导致：
- 生成实际已完成，但前端不知道需要刷新
- 用户看到"尚未生成"状态 → 手动点"生成此页"→ 触发 Bug 1

### 流程时间线

```
T1: Home.tsx
    createRestyleProject() → 201 ✅
    restyleGenerate()      → 202 ✅ (返回 task_id，但未使用)
    navigate(/preview)     → 立即跳转

T2: SlidePreview 加载
    syncProject()          → 获取 7 页数据
    页面显示"尚未生成图片" (generated_image_url 可能还没生成完)
    ❌ 没有轮询 restyle task

T3-T4: 后台完成 restyle (7/7 pages)
    前端无感知 → 用户仍看到"尚未生成"

T5: 用户手动点"生成此页"
    generateImages([pageId]) → POST /generate/images → 400 ❌
```

## Proposed Fix — 3 个修复点

### Fix 1: 后端验证增加 restyle 分支 (核心修复)

`backend/controllers/project_controller.py` L702-711:

```python
# 检查是否有足够的风格/模板信息
if project.creation_type == 'restyle':
    # Restyle 项目：需要风格参考图
    style_ref_paths = project.get_style_ref_image_paths()
    if not style_ref_paths:
        return bad_request("Restyle 项目必须有风格参考图。")
else:
    # 非 restyle 项目：需要模板图片或风格描述
    if not ref_image_path and not project.template_style:
        return bad_request("请先上传模板图片或添加风格描述。")
```

### Fix 2: 后端按 creation_type 分派任务

`backend/controllers/project_controller.py` L748-770:

```python
if project.creation_type == 'restyle':
    # Restyle 项目 → restyle_images_task
    task_manager.submit_task(
        task.id,
        restyle_images_task,
        project_id,
        ai_service,
        file_service,
        page_ids=selected_page_ids,
        max_workers=max_workers,
        aspect_ratio=...,
        resolution=...,
        app=app
    )
else:
    # 标准项目 → generate_images_task
    task_manager.submit_task(
        task.id,
        generate_images_task,
        ...  # 现有参数不变
    )
```

### Fix 3: 前端传递 restyle task_id 到 SlidePreview

**方案 A (简单 — 推荐)**: Home.tsx 传 task_id 给 SlidePreview 的 navigate state

```typescript
// Home.tsx
const response = await restyleGenerate(projectId);
const taskId = response.data?.task_id;
navigate(`/project/${projectId}/preview`, {
  state: { restyleTaskId: taskId }
});

// SlidePreview.tsx — 初始化时检查是否有正在进行的 restyle task
const restyleTaskId = (location.state as any)?.restyleTaskId;
useEffect(() => {
  if (restyleTaskId) {
    // 将 restyle task 关联到所有页面并开始轮询
    const pageIds = currentProject.pages.map(p => p.id).filter(Boolean);
    pollImageTask(restyleTaskId, pageIds);
  }
}, [restyleTaskId, currentProject?.id]);
```

**方案 B (健壮)**: 后端 API 增加 `active_tasks` 字段，SlidePreview 加载项目时自动发现正在进行的任务

```python
# GET /api/projects/{id} 响应增加
{
  "data": {
    ...project,
    "active_tasks": [{"task_id": "xxx", "task_type": "RESTYLE_IMAGES", "status": "PROCESSING"}]
  }
}
```

推荐方案 A，改动最小。方案 B 更通用但影响面大。

## Files to Modify

| File | Change | Bug |
|------|--------|-----|
| `backend/controllers/project_controller.py` L702-711 | restyle 验证分支 | Bug 1 |
| `backend/controllers/project_controller.py` L748-770 | restyle 任务分派 | Bug 2 |
| `frontend/src/pages/Home.tsx` L596-600 | 传递 task_id 到 navigate state | Bug 3 |
| `frontend/src/pages/SlidePreview.tsx` | 初始化轮询 restyle task | Bug 3 |

## Acceptance Criteria

- [x] Restyle 项目在 SlidePreview 中"生成此页"不再 400 错误
- [x] Restyle 项目在 SlidePreview 中"批量生成"正常工作
- [x] Restyle 项目创建后导航到 SlidePreview 能自动轮询生成进度
- [x] 非 restyle 项目行为完全不受影响
- [x] 重新生成单页时使用 restyle_images_task 而非 generate_images_task

## Risk Assessment

| 风险 | 等级 | 缓解 |
|------|------|------|
| 改动影响非 restyle 流程 | 低 | `creation_type === 'restyle'` 条件隔离 |
| navigate state 丢失 (页面刷新) | 中 | 用户刷新后不会有 task state，但 syncProject 会拉取最新数据（已生成的图片会正常显示） |

## Estimated Effort

~1-2 小时。后端 2 处修改 + 前端 2 处修改。
