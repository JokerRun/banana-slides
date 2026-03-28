---
name: e2e-restyle-testing
description: Banana Slides restyle（风格转换）和 edit 功能的端到端浏览器自动化测试流程。当用户要求跑 E2E 测试、smoke test、或手动验证 restyle pipeline 时使用本 skill——包括上传文件、触发风格转换、执行编辑、以及验证 debug artifacts 和数据库记录。也适用于用户说"跑一下 e2e"、"验证完整流程"、"test restyle"、或引用 e2e.md prompt 的场景。
---

# E2E Restyle Testing

这个 skill 记录 Banana Slides restyle + edit 的 full E2E flow，并把一次真实跑通里的 learnings 压成默认路径、fallback 和验证脚本。

重点不是“机械复读步骤”，而是：

- 先走 deterministic path，少猜 UI 行为
- 把 create project 和 batch restyle 分开，不混日志
- 用 evidence-based wording，区分“观察到什么” vs “为什么会这样”

## 前置条件

- 已加载 `agent-browser` skill
- Docker 和 docker compose 可用
- 能连接用户的 Chrome 浏览器（先跑 `agent-browser --auto-connect tab list` 确认已连接）
- 测试源文件存在: `must-style-reference/源文件-simplify.pptx`

## Flow Map

```
docker compose down
  -> docker compose up --build -d
  -> login via backend OAuth endpoint
  -> Home: create restyle project (upload + preset + submit)
  -> Preview: start batch restyle
  -> wait for completed pages
  -> edit one page
  -> validate debug artifacts
  -> validate DB + cross-check
```

## Interaction Strategy

这个应用在 `agent-browser --auto-connect` 下，不同控件的可靠交互方式差异很大。不要把所有 UI 控件都用同一种点击策略处理。

- hidden file input
  - 用 `agent-browser upload "css-selector" "/abs/path"`
  - 不要先试 `fill` / `type`
- native select
  - 优先 `agent-browser select @ref "label"`
  - 这类控件在实跑里是稳定的
- React button / tab
  - **默认优先** `agent-browser eval` + `button.click()`
  - 这次验收里多个关键按钮都表现为 `click @ref` 失败、JS click 成功
- navigation / modal / task completion 之后
  - 重新 snapshot
  - 不要复用旧 ref

通用 button click 模板：

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const text = 'BUTTON_TEXT_HERE'
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes(text))
  if (!btn) return 'not found: ' + text
  btn.scrollIntoView({ block: 'center' })
  btn.click()
  return 'clicked: ' + text
})()
EVALEOF
```

### Phase 1: 环境准备

```bash
docker compose down
docker compose up --build -d
docker compose ps
```

继续之前确认 backend ready：

```bash
docker logs banana-slides-backend --tail 5
```

### Phase 2: 浏览器登录 (GitHub SSO)

Default path：直接打开 backend OAuth endpoint，不先 debug login button。

```bash
agent-browser --auto-connect open http://localhost:5000/api/auth/oauth/github/login
```

Why this wording matters:

- 真实运行里，`agent-browser click` 过一次 `Continue with GitHub`，没有导航，也没有 backend OAuth 请求
- 前端代码实际是 `window.location.href = /api/auth/oauth/github/login`，不是 `window.open()`
- 所以**可靠结论**是“UI click 在 auto-connect run 里曾未触发导航；direct open 更稳”，不是“确定是 popup blocker”

验证登录成功：snapshot 里出现“已登录”或“素材生成 / 历史项目”等导航。

### Phase 3: Home 页创建 Restyle Project

1. 切换到 `风格转换` tab

推荐直接用 JS click：

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes('风格转换'))
  if (!btn) return 'not found'
  btn.click()
  return 'clicked'
})()
EVALEOF
```

2. 上传 source file

```bash
agent-browser upload "input[accept='.pptx,.ppt,.pdf']" "/absolute/path/to/file.pptx"
```

准则：

- `fill` / `type` / 普通 `click` 不是 file input 的正确原语
- `upload` 才是正确命令
- **Prefer CSS selector**，不要默认依赖 snapshot `@ref`

Why：hidden `<input type="file">` 经常不直接暴露在 accessibility snapshot 里；`@ref` 可能落到 wrapper/label/button，而不是实际 DOM node。之前一次真实运行里，`upload @ref` 报过：`Object id doesn't reference a Node`。

更准确的表述是：

- 不是“`@ref` 永远不行”
- 而是“只在 `@ref` 明确指向真实 `<input>` 节点时才可信；这个页面里 hidden input 场景下不该赌它”

3. 选择 `DDI Restyle` preset

```bash
agent-browser select @<combobox-ref> "DDI Restyle"
```

4. 点击 Home 页主按钮 `开始风格转换`

这一步是 **create project**，对应后端 `POST /api/projects/restyle`，不是 batch restyle。

对这个按钮，默认就用 JS click，不要先赌 `click @ref`。

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes('开始风格转换'))
  if (!btn) return 'not found'
  btn.scrollIntoView({ block: 'center' })
  btn.click()
  return 'clicked'
})()
EVALEOF
```

Create-project 阶段关注这些日志：

- `📁 Source file saved`
- `🎨 Style ref ... saved`
- `📄 Converting source file to images`
- `✅ Converted N pages`

### Phase 4: Preview 页启动 Batch Restyle

Home submit 成功后会跳到 `/project/<project_id>/preview`。

注意：Home toast 文案还写着“点击批量生成图片”，但 restyle 项目的真实按钮文案是 `开始风格转换 (N)`。以 preview 页按钮为准，不要被 toast 文案误导。

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes('开始风格转换'))
  if (!btn) return 'not found'
  btn.scrollIntoView({ block: 'center' })
  btn.click()
  return 'clicked'
})()
EVALEOF
```

如果 preview 页按钮点击后仍然没有 backend 请求，再重新 snapshot + 重跑一次 JS click。这个页面里按钮文字唯一，按 text click 足够稳定。

Batch restyle 阶段重点日志：

```bash
docker logs banana-slides-backend --tail 20
```

- `🌐 GenAI conversation request` —— AI 请求已发送
- `✅ Restyle page N/M completed` —— 单页完成
- `📊 Restyle progress: X/Y completed` —— 批量进度
- `🏁 Restyle task ... COMPLETED` —— 全部完成

典型耗时：每页约 `2-5 min`，看 model 和并发。

### Phase 5: 编辑页面 (Edit)

Restyle 完成后，选中一个已完成 page，点击 `编辑`。

`编辑` 按钮实跑里也出现了 `click @ref` 失效，建议直接用 JS click：

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes('编辑'))
  if (!btn) return 'not found'
  btn.scrollIntoView({ block: 'center' })
  btn.click()
  return 'clicked'
})()
EVALEOF
```

1. 在 textbox 输入 edit instruction，例如：`请将标题文字颜色改为深蓝色`
2. 点击 `生成图片`

这个按钮同样建议直接 JS click：

```bash
agent-browser eval --stdin <<'EVALEOF'
(function() {
  const btn = Array.from(document.querySelectorAll('button,[role="button"]'))
    .find((node) => node.textContent && node.textContent.includes('生成图片'))
  if (!btn) return 'not found'
  btn.click()
  return 'clicked'
})()
EVALEOF
```

3. 等待 `1-3 min`
4. 完成后确认出现 `历史版本` 按钮，且 version count 增长

Edit 阶段日志建议盯：

```bash
docker logs banana-slides-backend --tail 30
```

- 成功特征：`✅ Task <task_id> COMPLETED`
- 失败特征：`Task <task_id> FAILED` 或 provider/network stack trace

Retry guidance：

- Edit 可能遇到瞬时 provider/network 错误，例如 `RemoteProtocolError: Server disconnected`
- 如果任务失败，不要立刻怀疑 skill 步骤错了
- 重新打开 edit modal，重新输入/确认 prompt，再提交一次
- 重试时重新 snapshot，不复用失败前的 modal refs

### Phase 6: 验证 Debug Artifacts

Debug artifacts 在宿主机 `data/debug/restyle-context/`，容器内对应 `/app/debug/restyle-context/`。

目录结构有两种，不要混：

**first-pass batch restyle**

```
data/debug/restyle-context/<task_id>/
├── task/
│   ├── started.json       # task 元数据：page 数量、style ref 数量
│   └── summary.json       # 最终状态：completed/failed、各页结果
└── pages/
    └── page-<NNN>-<page_id>/
        ├── context_built.json      # 图片清单、prompt 长度、snapshot 状态
        ├── provider_decision.json  # model 选择、thinking level
        ├── provider_request.json   # 完整 prompt、reference image 路径
        ├── provider_result.json    # 耗时、图片尺寸、错误信息
        └── saved_version.json      # 输出路径、version number、snapshot 是否持久化
```

**single-page edit**

```
data/debug/restyle-context/<task_id>/
├── context_built.json      # 包含 turns_summary（conversation 上下文）
├── provider_decision.json  # conversation_supported、snapshot_present
├── provider_request.json   # 完整多轮 conversation 内容
├── provider_result.json    # conversation_attempted、degraded_context
└── saved_version.json      # source_version → new version number
```

优先用 bundled script，少手抄命令：

```bash
uv run python .agents/skills/e2e-restyle-testing/scripts/check_debug_artifacts.py <first_pass_task_id>
uv run python .agents/skills/e2e-restyle-testing/scripts/check_debug_artifacts.py <edit_task_id>
```

必要时再手动 spot check：

- batch: `task/summary.json`
- batch success run: 每个 `pages/page-*` 目录都有 5 个 page-level artifacts
- edit: `context_built.json` 里的 `snapshot_source` 应为 `persisted`
- edit: `saved_version.json` 的 version 应该比 source version 新
- edit failure run: `provider_result.json` 里可能已经有错误信息，但 `error_stage` 不一定可靠；以 task status + error message 为准

### Phase 7: 验证数据库

优先用 script，不要每次手写一大段 `docker exec python -c`：

```bash
uv run python .agents/skills/e2e-restyle-testing/scripts/inspect_restyle_db.py \
  --project-id <project_id> \
  --first-pass-task-id <first_pass_task_id> \
  --edit-task-id <edit_task_id>
```

Schema gotchas：

- 表名是 `page_image_versions`，不是 `image_versions`
- page 排序字段是 `order_index`，不是 `page_index`
- `projects` 没有 `name`
- 当前激活版本靠 `is_current`

### Phase 8: 交叉验证 (Cross-Validation)

最后确认 DB 和 artifacts 讲的是同一个故事：

- task status: `tasks.status` vs `summary.json -> event.status`
- current image path: `pages.generated_image_path` vs `saved_version.json -> event.image_path`
- version number: `page_image_versions.version_number` vs `saved_version.json -> event.version_number`
- source version: `saved_version.json -> trace.source_version_number` 应该对应 edit 前的 current version
- snapshot persisted: DB `restyle_base_prompt_snapshot IS NOT NULL` and debug `snapshot_persisted / snapshot_source`
- file exists: debug 里 `/app/uploads/...` 要映射回宿主机 `data/uploads/...`

## Reliable Learnings

1. **SSO login**
   - 真实证据：UI click 曾无导航、无 backend OAuth 请求
   - 更稳做法：直接 `open http://localhost:5000/api/auth/oauth/github/login`
   - 不要过度归因成 popup blocker；代码不是 `window.open`

2. **file upload**
   - 可靠结论：用 `agent-browser upload`
   - 更稳定位：用 CSS selector 指向真实 `<input>`
   - 不要写成“`@ref` 永远不行”；准确说法是“hidden file input 页面里不该依赖它”

3. **button click no-op**
   - 这次验收里，tab / create-project button / preview start button / edit button / generate button 都出现了 `click @ref` 失效
   - 对这个 app 的 React button，`eval -> button.click()` 应视为默认路径，不只是 fallback
   - 这个结论仍然是“本应用 + auto-connect 环境下的稳定经验”，不是对所有 React 应用的泛化

4. **stale refs**
   - 页面导航、modal 打开、生成完成后都要重新 snapshot

5. **SQLite schema 不要猜**
   - `page_image_versions`
   - `order_index`
   - `projects` 无 `name`

6. **artifact layout depends on flow**
   - batch restyle: `task/ + pages/`
   - single-page edit: task root flat files

7. **container path vs host path**
   - debug artifacts 里常见 `/app/uploads/...`
   - 宿主机对应 `data/uploads/...`

## Bundled Scripts

- `scripts/check_debug_artifacts.py`
  - auto-detect `batch` vs `edit`
  - 检查必需 artifact 是否齐全
  - 输出关键字段：status, version, snapshot source, missing files

- `scripts/inspect_restyle_db.py`
  - 直接读宿主机 `data/instance/database.db`
  - 打印 project/pages/tasks/page_image_versions
  - 可选对 first-pass task 和 edit task 做 cross-check

## Quick Reference

```bash
docker compose down
docker compose up --build -d
docker compose ps
docker logs banana-slides-backend --tail 30

agent-browser --auto-connect tab list
agent-browser --auto-connect open http://localhost:5000/api/auth/oauth/github/login
agent-browser upload "input[accept='.pptx,.ppt,.pdf']" "/absolute/path/to/file.pptx"

# For React buttons in this app, prefer eval click by visible text

uv run python .agents/skills/e2e-restyle-testing/scripts/check_debug_artifacts.py <task_id>
uv run python .agents/skills/e2e-restyle-testing/scripts/inspect_restyle_db.py --project-id <project_id>

uv run pytest backend/tests/integration/test_restyle_flow.py -v
```
