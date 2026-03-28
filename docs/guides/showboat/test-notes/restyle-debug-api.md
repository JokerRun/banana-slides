# Restyle Debug Artifact API — 验证文档

*2026-03-28T05:24:51Z by Showboat 0.6.1*
<!-- showboat-id: 932eb724-0085-4aba-abb1-a175d629f55f -->

## Overview

本文档测试并记录 Banana Slides 的 **Restyle Debug Artifact** 系统。该系统在风格转换（restyle）和编辑（edit）流程中自动生成结构化的 debug 数据，用于追踪 AI provider 调用链路、诊断 drift/fallback 问题。

核心组件：
- `backend/services/restyle_edit_debug.py` — artifact 写入 + 结构化日志
- `backend/services/task_manager.py` — first-pass restyle 集成点
- `backend/services/ai_service.py` — single-page edit 集成点
- Config: `DEBUG_RESTYLE_CONTEXT=true` + `RESTYLE_EDIT_DEBUG_DIR`

测试数据来自刚刚完成的 E2E 运行：
- First-pass restyle task: `b6dfba00-32fe-4952-8a51-136372f40d9b`
- Single-page edit task: `5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6`

## 1. Config 验证

确认 debug 功能已启用，artifact 目录正确配置。

```bash
grep "DEBUG_RESTYLE_CONTEXT\|RESTYLE_EDIT_DEBUG_DIR" .env 2>/dev/null || echo "not set in .env"
```

```output
DEBUG_RESTYLE_CONTEXT=true
```

```bash
grep "DEBUG_RESTYLE_CONTEXT\|RESTYLE_EDIT_DEBUG_DIR" backend/config.py
```

```output
    DEBUG_RESTYLE_CONTEXT = os.getenv('DEBUG_RESTYLE_CONTEXT', 'false').lower() in ('true', '1', 'yes')
    RESTYLE_EDIT_DEBUG_DIR = os.getenv(
        'RESTYLE_EDIT_DEBUG_DIR',
```

## 2. Debug Artifact 目录结构

验证 first-pass restyle 和 single-page edit 两种 flow 各自的 artifact 目录结构。

### 2a. First-pass restyle（批量风格转换）

预期结构：`<task_id>/task/{started,summary}.json` + `<task_id>/pages/page-NNN-<page_id>/{context_built,provider_decision,provider_request,provider_result,saved_version}.json`

```bash
find data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b -type f | sort
```

```output
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/context_built.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/provider_decision.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/provider_request.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/provider_result.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/saved_version.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-002-7b05bde7-12f0-40d7-9fd4-a77ca43eaed9/context_built.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-002-7b05bde7-12f0-40d7-9fd4-a77ca43eaed9/provider_decision.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-002-7b05bde7-12f0-40d7-9fd4-a77ca43eaed9/provider_request.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-002-7b05bde7-12f0-40d7-9fd4-a77ca43eaed9/provider_result.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-002-7b05bde7-12f0-40d7-9fd4-a77ca43eaed9/saved_version.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/task/started.json
data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/task/summary.json
```

✅ First-pass 结构正确：task/ 下有 started + summary，pages/ 下每页都有完整的 5 个 artifact 文件。

### 2b. Single-page edit（单页编辑）

预期结构：扁平目录，`<task_id>/{context_built,provider_decision,provider_request,provider_result,saved_version}.json`（没有 task/ 和 pages/ 子目录）。

```bash
find data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6 -type f | sort
```

```output
data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/context_built.json
data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/provider_decision.json
data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/provider_request.json
data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/provider_result.json
data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/saved_version.json
```

✅ Edit 结构正确：扁平目录，5 个 artifact 文件，无 task/ 或 pages/ 子目录。

## 3. Artifact 内容验证 — First-pass Restyle

### 3a. task/started.json

记录任务启动元数据：page 数量、style ref 数量、分辨率等。

```bash
python3 -m json.tool data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/task/started.json
```

```output
{
    "event": {
        "aspect_ratio": "16:9",
        "max_workers": 8,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "resolution": "2K",
        "restyle_prompt_len": 956,
        "restyle_prompt_present": true,
        "selected_page_ids": [
            "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
            "7b05bde7-12f0-40d7-9fd4-a77ca43eaed9"
        ],
        "style_ref_count": 1,
        "total_pages": 2
    },
    "event_name": "started",
    "trace": {
        "flow_kind": "first_pass_restyle",
        "page_count": 2,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "task_id": "b6dfba00-32fe-4952-8a51-136372f40d9b"
    }
}
```

✅ started.json 字段完整：trace 包含 flow_kind/task_id/project_id，event 包含 total_pages=2、style_ref_count=1、resolution=2K。

### 3b. task/summary.json

记录任务最终状态和每页结果。

```bash
python3 -m json.tool data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/task/summary.json
```

```output
{
    "event": {
        "completed": 2,
        "failed": 0,
        "page_results": [
            {
                "error": null,
                "image_path": "0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/7b05bde7-12f0-40d7-9fd4-a77ca43eaed9_v1.png",
                "page_id": "7b05bde7-12f0-40d7-9fd4-a77ca43eaed9",
                "page_order_index": 2,
                "version_number": 1
            },
            {
                "error": null,
                "image_path": "0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v1.png",
                "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
                "page_order_index": 1,
                "version_number": 1
            }
        ],
        "status": "COMPLETED",
        "total_pages": 2
    },
    "event_name": "summary",
    "trace": {
        "flow_kind": "first_pass_restyle",
        "page_count": 2,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "task_id": "b6dfba00-32fe-4952-8a51-136372f40d9b"
    }
}
```

✅ summary.json：status=COMPLETED、completed=2、failed=0、每页都有 image_path 和 version_number=1、error=null。

### 3c. Page-level artifacts — provider_decision.json

记录 AI provider 选择决策（model、thinking level）。

```bash
python3 -m json.tool data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/provider_decision.json
```

```output
{
    "event": {
        "model": "gemini-3.1-flash-image-preview",
        "provider": "GenAIImageProvider",
        "ref_image_count": 2,
        "thinking_level": "high"
    },
    "event_name": "provider_decision",
    "trace": {
        "flow_kind": "first_pass_restyle",
        "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
        "page_order_index": 1,
        "page_version_number": null,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "source_version_number": null,
        "task_id": "b6dfba00-32fe-4952-8a51-136372f40d9b"
    }
}
```

✅ provider_decision：model=gemini-3.1-flash-image-preview、thinking_level=high、ref_image_count=2（原始 slide + style ref）。

### 3d. Page-level artifacts — provider_result.json

记录 provider 返回结果：耗时、图片尺寸、错误阶段。

```bash
python3 -m json.tool data/debug/restyle-context/b6dfba00-32fe-4952-8a51-136372f40d9b/pages/page-001-2f9dd85b-4a73-4559-9c2a-4e8385108d3f/provider_result.json
```

```output
{
    "event": {
        "elapsed_seconds": 254.982,
        "error_stage": null,
        "model": "gemini-3.1-flash-image-preview",
        "provider": "GenAIImageProvider",
        "result_image_size": [
            2752,
            1536
        ]
    },
    "event_name": "provider_result",
    "trace": {
        "flow_kind": "first_pass_restyle",
        "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
        "page_order_index": 1,
        "page_version_number": null,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "source_version_number": null,
        "task_id": "b6dfba00-32fe-4952-8a51-136372f40d9b"
    }
}
```

✅ provider_result：elapsed_seconds=255s、error_stage=null、result_image_size=2752×1536（2K 16:9）。

## 4. Artifact 内容验证 — Single-page Edit

Edit flow 的关键差异：使用 multi-turn conversation context，包含 snapshot 持久化状态。

### 4a. context_built.json — 编辑上下文

```bash
python3 -c "
import json
data = json.load(open(\"data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/context_built.json\"))
# Show event without the full image_manifest details for readability
event = data[\"event\"]
event[\"image_manifest\"] = f\"[{len(event[\"image_manifest\"])} items]\"
print(json.dumps({\"trace\": data[\"trace\"], \"event\": event}, indent=2, ensure_ascii=False))
"
```

```output
{
  "trace": {
    "flow_kind": "edit_restyle",
    "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
    "page_order_index": 1,
    "page_version_number": null,
    "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
    "source_version_number": 1,
    "task_id": "5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6"
  },
  "event": {
    "baseline_images_count": 2,
    "current_images_count": 1,
    "degraded_context": false,
    "image_manifest": "[3 items]",
    "snapshot_source": "persisted",
    "turns_summary": [
      {
        "image_count": 0,
        "index": 1,
        "role": "user",
        "text_len": 2572
      },
      {
        "image_count": 2,
        "index": 2,
        "role": "user",
        "text_len": 0
      },
      {
        "image_count": 1,
        "index": 3,
        "role": "user",
        "text_len": 0
      },
      {
        "image_count": 0,
        "index": 4,
        "role": "user",
        "text_len": 26
      }
    ]
  }
}
```

✅ Edit context_built 关键字段：
- `flow_kind=edit_restyle`、`source_version_number=1`（基于 v1 做编辑）
- `snapshot_source=persisted`（snapshot 从 DB 恢复，非重新生成）
- `degraded_context=false`（上下文完整，未降级）
- `turns_summary`：4 轮对话 — Turn 1 系统 prompt(2572 chars)、Turn 2 基线图片(2)、Turn 3 当前版本图片(1)、Turn 4 编辑指令(26 chars)
- `image_manifest`：3 张图（original_slide + style_ref + current_v1）

### 4b. provider_result.json — 编辑结果

```bash
python3 -m json.tool data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/provider_result.json
```

```output
{
    "event": {
        "baseline_images_count": 2,
        "context_mode": "restyle_conversation",
        "conversation_attempted": true,
        "current_images_count": 1,
        "degraded_context": false,
        "model": "gemini-3.1-flash-image-preview",
        "provider": "GenAIImageProvider",
        "provider_fallback": false,
        "snapshot_present": true
    },
    "event_name": "provider_result",
    "trace": {
        "flow_kind": "edit_restyle",
        "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
        "page_order_index": 1,
        "page_version_number": null,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "source_version_number": 1,
        "task_id": "5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6"
    }
}
```

✅ Edit result 关键字段：
- `conversation_attempted=true` — 走了 multi-turn conversation 路径
- `provider_fallback=false` — 没有 fallback 到单次调用
- `degraded_context=false` — 上下文未因图片过多而被裁剪
- `snapshot_present=true` — 有 prompt snapshot 可用于恢复上下文

### 4c. saved_version.json — 版本写入记录

```bash
python3 -m json.tool data/debug/restyle-context/5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6/saved_version.json
```

```output
{
    "event": {
        "image_path": "0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v2.png",
        "page_order_index": 1,
        "version_number": 2
    },
    "event_name": "saved_version",
    "trace": {
        "flow_kind": "edit_restyle",
        "page_id": "2f9dd85b-4a73-4559-9c2a-4e8385108d3f",
        "page_order_index": 1,
        "page_version_number": 2,
        "project_id": "0eba3c60-0a38-4243-a72b-e9f49a92c607",
        "source_version_number": 1,
        "task_id": "5b407bdf-e3fd-4fdf-aa46-96cf82a7d0f6"
    }
}
```

✅ saved_version：source_version=1 → version=2，image_path 指向 v2.png，版本链正确。

## 5. 数据库交叉验证

将 debug artifacts 的数据与 SQLite 数据库记录做交叉比对，确认一致性。

```bash
docker exec banana-slides-backend python3 -c "
import sqlite3, json
db = sqlite3.connect(\"/app/backend/instance/database.db\")
db.row_factory = sqlite3.Row
PID = \"0eba3c60-0a38-4243-a72b-e9f49a92c607\"

print(\"=== Tasks ===\")
for r in db.execute(\"SELECT id, task_type, status FROM tasks WHERE project_id=? ORDER BY created_at\", (PID,)):
    print(f\"  {r[0][:8]}... type={r[1]:<20s} status={r[2]}\")

print()
print(\"=== Pages ===\")
for r in db.execute(\"SELECT id, order_index, status, generated_image_path FROM pages WHERE project_id=? ORDER BY order_index\", (PID,)):
    print(f\"  order={r[1]} id={r[0][:8]}... status={r[2]} image={r[3]}\")

print()
print(\"=== Image Versions ===\")
for r in db.execute(\"\"\"
    SELECT piv.version_number, piv.image_path, piv.is_current, p.order_index
    FROM page_image_versions piv JOIN pages p ON piv.page_id=p.id
    WHERE p.project_id=? ORDER BY p.order_index, piv.version_number
\"\"\", (PID,)):
    cur = \" <- current\" if r[2] else \"\"
    print(f\"  page {r[3]} v{r[0]}: {r[1]}{cur}\")
db.close()
"
```

```output
=== Tasks ===
  b6dfba00... type=RESTYLE_IMAGES       status=COMPLETED
  5b407bdf... type=EDIT_PAGE_IMAGE      status=COMPLETED

=== Pages ===
  order=0 id=2f9dd85b... status=COMPLETED image=0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v2.png
  order=1 id=7b05bde7... status=COMPLETED image=0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/7b05bde7-12f0-40d7-9fd4-a77ca43eaed9_v1.png

=== Image Versions ===
  page 0 v1: 0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v1.png
  page 0 v2: 0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v2.png <- current
  page 1 v1: 0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/7b05bde7-12f0-40d7-9fd4-a77ca43eaed9_v1.png <- current
```

### 交叉比对结果

| 检查项 | DB | Debug Artifact | 结果 |
|--------|-----|----------------|------|
| Task1 status | COMPLETED | summary.status=COMPLETED | ✅ |
| Task2 status | COMPLETED | provider_result recorded | ✅ |
| Page 0 当前版本 | v2 (after edit) | saved_version.version=2 | ✅ |
| Page 1 当前版本 | v1 (first pass only) | saved_version.version=1 | ✅ |
| Page 0 image path | ...v2.png | saved_version.image_path=...v2.png | ✅ |
| Edit source version | — | trace.source_version=1 | ✅ |
| Edit flow kind | EDIT_PAGE_IMAGE | trace.flow_kind=edit_restyle | ✅ |

## 6. 生成文件完整性

确认 debug artifacts 引用的图片文件在宿主机上实际存在。

```bash
for f in \
  data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v1.png \
  data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v2.png \
  data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/7b05bde7-12f0-40d7-9fd4-a77ca43eaed9_v1.png; do
  if [ -f "$f" ]; then
    size=$(du -h "$f" | cut -f1)
    echo "✅ $f ($size)"
  else
    echo "❌ MISSING: $f"
  fi
done
```

```output
✅ data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v1.png (3.4M)
✅ data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/2f9dd85b-4a73-4559-9c2a-4e8385108d3f_v2.png (3.2M)
✅ data/uploads/0eba3c60-0a38-4243-a72b-e9f49a92c607/pages/7b05bde7-12f0-40d7-9fd4-a77ca43eaed9_v1.png (4.3M)
```

```bash
uv run pytest backend/tests/integration/test_restyle_flow.py -v -k "debug" 2>&1 | grep -E "PASSED|FAILED|ERROR" | head -5
```

```output
backend/tests/integration/test_restyle_flow.py::TestRestyleDebugArtifacts::test_restyle_all_pages_failed_marks_task_failed_and_summary_failed PASSED [ 50%]
backend/tests/integration/test_restyle_flow.py::TestRestyleDebugArtifacts::test_restyle_single_page_writes_task_and_page_debug_artifacts PASSED [100%]
```

✅ 2/2 debug artifact 专项测试通过：
- `test_restyle_all_pages_failed_marks_task_failed_and_summary_failed` — 验证全部页面失败时 summary.status 正确标记为 FAILED
- `test_restyle_single_page_writes_task_and_page_debug_artifacts` — 验证单页 restyle 的层级 artifact 写入

## 结论

Restyle Debug Artifact API 全部功能验证通过：

1. ✅ **Config**：`DEBUG_RESTYLE_CONTEXT=true` 启用 artifact 写入
2. ✅ **目录结构**：first-pass 使用层级结构（task/ + pages/），edit 使用扁平结构
3. ✅ **First-pass artifacts**：started.json / summary.json / 每页 5 个文件全部完整
4. ✅ **Edit artifacts**：conversation context、snapshot 恢复、版本链全部正确
5. ✅ **DB ↔ Debug 交叉验证**：7 项检查全部一致
6. ✅ **文件完整性**：所有引用的图片文件存在且大小合理
7. ✅ **集成测试**：2/2 通过，包含 failure 语义和 artifact 写入验证
