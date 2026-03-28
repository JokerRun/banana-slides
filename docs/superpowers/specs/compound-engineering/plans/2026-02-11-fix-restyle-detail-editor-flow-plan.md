---
title: "fix: Restyle 模式 — DetailEditor 页面流程修复"
type: fix
date: 2026-02-11
---

# 🐛 fix: Restyle 模式下 DetailEditor 页面流程死锁 & 导航错误

## Overview

Restyle 项目在创建后被错误导航到 DetailEditor（描述编辑页），而非 SlidePreview（预览页）。且 DetailEditor 完全没有 restyle 模式的处理逻辑，导致：

1. "生成图片 →" 按钮因 `disabled={!hasAllDescriptions}` 被永久禁用（restyle 项目无 description）
2. 描述相关操作（批量生成描述、导出描述、AI 修改描述）对 restyle 项目无意义且会触发 400 错误
3. 用户被困在 DetailEditor 无法前进到 SlidePreview

## Root Cause Analysis

```
Home.tsx (restyle submit)
  ├─ Step 1: createRestyleProject() ✅
  ├─ Step 2: restyleGenerate()      ✅ (异步启动图片生成)
  └─ Step 3: navigate(`/detail`)    ❌ 注释写 "Navigate to SlidePreview" 但实际导航到 /detail

DetailEditor.tsx
  ├─ hasAllDescriptions = pages.every(p => p.description_content)  → false (restyle无description)
  ├─ "→ 生成图片" button: disabled={!hasAllDescriptions}          → 永久禁用 ❌
  ├─ "批量生成描述" button: 调用 generateDescriptions()            → 400 error ❌
  ├─ "导出描述" button: disabled (无description)                   → 正常但无意义
  └─ 无任何 creation_type === 'restyle' 判断                       → 零 restyle 适配 ❌

SlidePreview.tsx
  └─ 已正确处理 restyle: 原始slide对比缩略图、生成按钮等           ✅
```

## Proposed Fix — 两个修复点

### Fix 1: Home.tsx — Restyle 导航目标改为 SlidePreview (1行改动)

```
Before: navigate(`/project/${projectId}/detail`)   // line 600
After:  navigate(`/project/${projectId}/preview`)
```

**理由**: Restyle 项目跳过 outline → description 流程，`restyleGenerate()` 已启动异步图片生成。SlidePreview 已有完善的 restyle 支持（进度轮询、原始slide对比、单页重生成）。

### Fix 2: DetailEditor.tsx — 增加 restyle 模式兼容 (防御性修复)

即使 Fix 1 修正了主路径，用户仍可能通过 History 页 / 直接 URL 访问 restyle 项目的 DetailEditor。需要以下处理：

#### 2a. "→ 生成图片" 按钮 — restyle 项目始终可点击

```tsx
// Before:
disabled={!hasAllDescriptions}

// After:
disabled={currentProject.creation_type !== 'restyle' && !hasAllDescriptions}
```

#### 2b. 隐藏无意义的描述操作按钮 (restyle 模式)

对 restyle 项目隐藏:
- "批量生成描述" 按钮
- "导出描述" 按钮
- AI 修改输入框 (AiRefineInput)
- "x/y 页已完成" 计数器

#### 2c. 可选增强: restyle 项目显示提示横幅

```
┌──────────────────────────────────────────────────────┐
│ ℹ️ 风格转换项目不需要编辑描述，点击右上角 → 进入预览  │
└──────────────────────────────────────────────────────┘
```

## Files to Modify

| File | Change | Impact |
|------|--------|--------|
| `frontend/src/pages/Home.tsx` L600 | `/detail` → `/preview` | **主修复**: 修正导航目标 |
| `frontend/src/pages/DetailEditor.tsx` L240 | 放开 restyle 按钮 disabled 条件 | **防御修复**: 解除按钮死锁 |
| `frontend/src/pages/DetailEditor.tsx` | 条件隐藏描述操作区 | **UX 优化**: 减少困惑 |

## Acceptance Criteria

- [x] Restyle 项目创建后直接跳转 SlidePreview
- [x] 通过 History/URL 访问 restyle 项目的 DetailEditor 时，"→" 按钮可点击
- [x] Restyle 项目在 DetailEditor 不显示无意义的描述操作
- [x] 非 restyle 项目行为完全不受影响

## Risk Assessment

| 风险 | 等级 | 缓解 |
|------|------|------|
| 修改影响非 restyle 流程 | 低 | 条件分支隔离, `creation_type !== 'restyle'` |
| History 页跳转行为变化 | 无 | History 页已有 `from: 'history'` state, 不受影响 |

## Estimated Effort

~30 分钟，纯前端修改，无后端/数据库变更。
