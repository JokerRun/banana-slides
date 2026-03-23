# Env-Only Settings Lockdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将系统从“DB 驱动 settings”切换为“env-only”，并彻底禁用应用内 settings 读写可见性。

**Architecture:** 分三阶段小步落地：先锁死 `/api/settings*`（保持 401/403 语义），再移除运行时 DB settings 依赖与启动覆盖路径，最后清理前端 settings 入口与调用，并补充一次性切换自检脚本与可选数据清理迁移。全程以 TDD 驱动并保持可回滚。

**Tech Stack:** Flask, SQLAlchemy, Alembic, React, React Router, Vitest, Pytest, UV

---

## File Structure

### Backend - Create

- `backend/scripts/check_legacy_settings_completeness.py`（一次性切换前检查：DB 有值但 env 未配置的 optional 项）
- `backend/migrations/versions/019_clear_legacy_settings_secrets.py`（可选：清空 `settings` 表历史敏感字段）
- `backend/tests/unit/test_api_settings_lockdown.py`（`/api/settings*` 锁定契约测试）

### Backend - Modify

- `backend/controllers/settings_controller.py`（所有 `/api/settings*` 路由锁定）
- `backend/config.py`（将 `DEFAULT_RESOLUTION`/`DEFAULT_ASPECT_RATIO` 改为 env 驱动）
- `backend/app.py`（移除 `_load_settings_to_config` 与 `/api/output-language` 对 DB `Settings` 的依赖）
- `backend/controllers/__init__.py`（如需调整 settings blueprint 暴露顺序/注释）
- `backend/tests/integration/test_auth_owner_isolation.py`（替换/移除 settings 测试任务相关断言）

### Frontend - Modify

- `frontend/src/App.tsx`（移除 `/settings` 路由）
- `frontend/src/pages/Home.tsx`（移除 settings 导航按钮）
- `frontend/src/components/shared/HelpModal.tsx`（移除跳转 `/settings` 行为）
- `frontend/src/components/shared/ProjectSettingsModal.tsx`（移除嵌入的全局 settings 页面）
- `frontend/src/pages/SlidePreview.tsx`（移除 `getSettings()` 依赖，改为本地/env 安全默认）
- `frontend/src/api/endpoints.ts`（删除 `/api/settings*` 相关 API 导出）
- `frontend/src/pages/Settings.tsx`（删除文件，或替换为空壳并不再路由引用）
- `frontend/src/tests/auth/authBootstrap.test.tsx`（更新 mock，移除 `SettingsPage` 断言依赖）

### Optional Docs - Modify

- `.env.example`（补充 env-only 标识说明）
- `README.md` / `README_EN.md`（更新“配置变更=改 env + 重启”的运维说明）

---

### Task 1: 锁定 Settings API 契约（401/403）

**Files:**
- Create: `backend/tests/unit/test_api_settings_lockdown.py`
- Modify: `backend/controllers/settings_controller.py`
- Modify: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（覆盖全部 `/api/settings*`，含 `/tests/*`）**

```python
def test_settings_endpoints_require_auth(app):
    with app.test_client() as client:
        assert client.get('/api/settings/').status_code == 401
        assert client.put('/api/settings/', json={}).status_code == 401
        assert client.post('/api/settings/reset').status_code == 401
        assert client.post('/api/settings/verify').status_code == 401


def test_settings_endpoints_locked_for_authenticated_user(client):
    for method, path in [
        ('get', '/api/settings/'),
        ('put', '/api/settings/'),
        ('post', '/api/settings/reset'),
        ('post', '/api/settings/verify'),
        ('post', '/api/settings/tests/text-model'),
        ('get', '/api/settings/tests/fake-task/status'),
    ]:
        resp = getattr(client, method)(path, json={} if method != 'get' else None)
        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['error']['code'] == 'SETTINGS_LOCKED'
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py -v`
Expected: FAIL（当前接口仍可读写）。

- [ ] **Step 3: 最小实现：在 settings controller 中统一返回 locked 响应**

```python
def _locked_response():
    return error_response(
        'SETTINGS_LOCKED',
        'This instance is env-managed. Edit .env and restart service.',
        403,
    )

# apply to /, /reset, /verify, /tests/<test_name>, /tests/<task_id>/status
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py -v`
Expected: PASS。

- [ ] **Step 5: 修正冲突集成测试（删除旧 settings tests owner-scope 用例）**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k settings -v`
Expected: PASS（或无匹配测试）。

- [ ] **Step 6: Commit**

```bash
git add backend/tests/unit/test_api_settings_lockdown.py backend/controllers/settings_controller.py backend/tests/integration/test_auth_owner_isolation.py
git commit -m "fix(settings): lock /api/settings endpoints for env-only mode"
```

### Task 2: 启动 preflight 与 env 配置收敛（S2核心）

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/app.py`
- Modify: `backend/tests/unit/test_api_settings_lockdown.py`

- [ ] **Step 1: 写失败测试（required env 缺失或非法时 fail-fast）**

```python
def test_startup_preflight_missing_required_env(monkeypatch):
    monkeypatch.delenv('AI_PROVIDER_FORMAT', raising=False)
    # expect create_app() to raise ValueError


def test_startup_preflight_invalid_provider(monkeypatch):
    monkeypatch.setenv('AI_PROVIDER_FORMAT', 'bad-provider')
    # expect create_app() to raise ValueError
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py -k preflight -v`
Expected: FAIL（当前未实现 preflight）。

- [ ] **Step 3: 最小实现：在 app startup 增加 preflight，按 raw env 校验 required 项**

```python
def _preflight_env_or_raise():
    # validate AI_PROVIDER_FORMAT in env and provider-specific API key presence
    ...
```

- [ ] **Step 4: 修改 config 收敛（`DEFAULT_RESOLUTION`/`DEFAULT_ASPECT_RATIO` 改为 env 读取）**

```python
DEFAULT_ASPECT_RATIO = os.getenv('DEFAULT_ASPECT_RATIO', '16:9')
DEFAULT_RESOLUTION = os.getenv('DEFAULT_RESOLUTION', '2K')
```

- [ ] **Step 5: 补充输出语言路径测试（`/api/output-language` 不再读 DB Settings）**

```python
def test_output_language_reads_from_config_not_db(app, monkeypatch):
    app.config['OUTPUT_LANGUAGE'] = 'en'
    with app.test_client() as c:
        resp = c.get('/api/output-language')
        assert resp.status_code == 200
        assert resp.get_json()['data']['language'] == 'en'
```

- [ ] **Step 6: 最小实现：删掉 `_load_settings_to_config` 调用并让 `/api/output-language` 只读 `app.config`**

```python
@app.route('/api/output-language', methods=['GET'])
def get_output_language():
    return {'data': {'language': app.config.get('OUTPUT_LANGUAGE', Config.OUTPUT_LANGUAGE)}}
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py -k "preflight or output_language or settings_endpoints" -v`
Expected: PASS。

- [ ] **Step 8: 后端定向回归**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py -v`
Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add backend/config.py backend/app.py backend/tests/unit/test_api_settings_lockdown.py
git commit -m "refactor(config): add env preflight and remove runtime DB settings dependency"
```

### Task 3: 删除前端 Settings 入口与路由

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/Home.tsx`
- Modify: `frontend/src/components/shared/HelpModal.tsx`
- Modify: `frontend/src/components/shared/ProjectSettingsModal.tsx`
- Modify: `frontend/src/tests/auth/authBootstrap.test.tsx`

- [ ] **Step 1: 写失败测试（`/settings` 应重定向，且不再渲染 SettingsPage）**

```tsx
it('redirects /settings to / when authenticated', async () => {
  vi.mocked(getAuthMe).mockResolvedValue({ success: true, data: { user: { id: 'u1', is_active: true } } })
  window.history.replaceState({}, '', '/settings')
  render(<App />)
  await waitFor(() => expect(screen.getByText('HOME_PAGE')).toBeInTheDocument())
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx`
Expected: FAIL（当前仍有 `/settings` 路由）。

- [ ] **Step 3: 最小实现：移除 App 路由与 Home 导航 Settings 按钮；HelpModal 不再跳 `/settings`；ProjectSettingsModal 移除 global settings tab**

```tsx
// App.tsx remove:
// <Route path="/settings" ... />
```

- [ ] **Step 4: 再跑测试确认通过**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/Home.tsx frontend/src/components/shared/HelpModal.tsx frontend/src/components/shared/ProjectSettingsModal.tsx frontend/src/tests/auth/authBootstrap.test.tsx
git commit -m "refactor(frontend): remove settings entry and route in env-only mode"
```

### Task 4: 清理前端 `/api/settings*` 调用与 Settings 页面依赖

**Files:**
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/pages/SlidePreview.tsx`
- Modify: `frontend/src/tests/api/authClient.test.ts`
- Delete: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: 写失败测试（编译/类型层面不再引用 settings API）**

```bash
cd frontend && npm run build:check
```

Expected: FAIL（清理前会有依赖链）。

- [ ] **Step 2: 最小实现：删除 settings API 导出与 Settings 页文件，替换 SlidePreview 中 `getSettings()` 检查逻辑**

```tsx
// SlidePreview: 不再请求 /api/settings
// 对 1K 警告逻辑改为基于本地默认分辨率常量或不阻塞执行
```

- [ ] **Step 3: 运行前端检查与测试**

Run: `cd frontend && npm run build:check`
Expected: PASS。

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx src/tests/api/authClient.test.ts`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/endpoints.ts frontend/src/pages/SlidePreview.tsx frontend/src/tests/api/authClient.test.ts frontend/src/pages/Settings.tsx
git commit -m "refactor(frontend): remove settings api surface and page"
```

### Task 5: 一次性切换前 completeness check 脚本

**Files:**
- Create: `backend/scripts/check_legacy_settings_completeness.py`

- [ ] **Step 1: 写脚本行为测试（最小可运行断言）**

```bash
uv run python backend/scripts/check_legacy_settings_completeness.py --help
```

Expected: 目前 FAIL（脚本不存在）。

- [ ] **Step 2: 实现脚本（只读 DB + 比对 env）**

```python
# 输出: missing optional env for non-empty legacy settings columns
# exit code: 0 when clean, 2 when mismatches found
```

- [ ] **Step 3: 运行脚本验证**

Run: `uv run python backend/scripts/check_legacy_settings_completeness.py --strict`
Expected: 输出差异列表或“clean”。

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/check_legacy_settings_completeness.py
git commit -m "chore(ops): add pre-cutover completeness check for legacy settings"
```

### Task 6: 可选敏感字段清理迁移（S3，窗口后执行）

**Files:**
- Create: `backend/migrations/versions/019_clear_legacy_settings_secrets.py`

- [ ] **Step 1: 写迁移前检查脚本命令（确认回滚窗口已关闭）**

```bash
echo "Confirm rollback window closed before running 019"
```

- [ ] **Step 2: 实现迁移（仅清空敏感字段，不删表）**

```sql
UPDATE settings
SET api_key = NULL,
    mineru_token = NULL,
    baidu_ocr_api_key = NULL;
```

- [ ] **Step 3: 执行迁移并验证**

Run: `cd backend && uv run alembic upgrade head`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/019_clear_legacy_settings_secrets.py
git commit -m "chore(migration): clear legacy settings secrets after env-only cutover"
```

### Task 7: 回归验证与文档收口

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_EN.md`

- [ ] **Step 1: 更新文档（配置变更流程=改 env + 重启）**

```text
No in-app settings management.
Use env/secrets and restart service.
```

- [ ] **Step 2: 后端回归测试**

Run: `uv run pytest backend/tests/unit/test_api_settings_lockdown.py backend/tests/unit/test_api_auth.py backend/tests/integration/test_auth_owner_isolation.py -v`
Expected: PASS。

- [ ] **Step 3: 前端回归测试**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx src/tests/api/authClient.test.ts`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add .env.example README.md README_EN.md
git commit -m "docs(config): document env-only settings workflow"
```

---

## Execution Notes

1. 实施建议按 `S1 -> S2 -> S3(optional)` 顺序，不要并行执行 `S3`。
2. `S3` 前确保回滚窗口关闭，或保留 `settings` 快照恢复路径。
3. 每个任务完成后建议调用 `@requesting-code-review` 做一次快速审阅再推进下一任务。
