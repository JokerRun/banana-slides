# OAuth2 User Management (GitHub + Azure China 21V) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 GitHub + Azure China OAuth2 登录、Flask Cookie 会话、owner 级数据隔离（含 global task 与 `/files/*` 归属校验），并严格控制改动范围。

**Architecture:** 采用分阶段迁移与渐进接入：M1 只做 additive schema；M2 做 owner 回填和 mineru_extract_id 落库；先完成 OAuth 服务、auth guard、owner 写入、owner 读取与 `/files` 校验，再执行 M3 非空/外键收紧。前端补齐 login/bootstrap/logout 和 401 跳转；global material 轮询迁到 `/api/tasks/<task_id>`。

**Tech Stack:** Flask, SQLAlchemy, Alembic, SQLite, Axios, React Router, Zustand, Pytest, Vitest, UV

---

## Execution Map

```text
M1 additive schema
  -> M2 backfill + mineru_extract persistence
  -> OAuth adapters + auth service
  -> auth API + session/cookie/CORS contract
  -> owner-scoped writes/reads + settings/task visibility isolation
  -> /files ownership hardening (401/404 semantics)
  -> frontend login/bootstrap + global task polling switch
  -> M3 owner constraints (NOT NULL/FK) after all write paths are owner-aware
  -> full regression verification
```

## File Structure

### Backend - Create

- `backend/models/user.py`
- `backend/models/user_oauth_account.py`
- `backend/services/auth/__init__.py`
- `backend/services/auth/oauth_providers.py`
- `backend/services/auth/auth_service.py`
- `backend/controllers/auth_controller.py`
- `backend/controllers/task_controller.py`
- `backend/utils/auth.py`
- `backend/migrations/versions/016_auth_foundation_additive.py`
- `backend/migrations/versions/017_auth_owner_backfill.py`
- `backend/migrations/versions/018_auth_owner_constraints.py`
- `backend/scripts/reassign_bootstrap_owner.py`
- `backend/tests/unit/test_oauth_providers.py`
- `backend/tests/unit/test_auth_service.py`
- `backend/tests/unit/test_api_auth.py`
- `backend/tests/integration/test_auth_owner_isolation.py`

### Backend - Modify

- `backend/models/__init__.py`
- `backend/models/project.py`
- `backend/models/material.py`
- `backend/models/task.py`
- `backend/models/reference_file.py`
- `backend/models/user.py`
- `backend/models/user_template.py`
- `backend/models/page.py`
- `backend/app.py`
- `backend/config.py`
- `backend/utils/__init__.py`
- `backend/controllers/__init__.py`
- `backend/controllers/project_controller.py`
- `backend/controllers/page_controller.py`
- `backend/controllers/export_controller.py`
- `backend/controllers/template_controller.py`
- `backend/controllers/material_controller.py`
- `backend/controllers/reference_file_controller.py`
- `backend/controllers/restyle_controller.py`
- `backend/controllers/file_controller.py`
- `backend/controllers/settings_controller.py`
- `backend/services/task_manager.py`

### Frontend - Create

- `frontend/src/pages/Login.tsx`
- `frontend/src/types/auth.ts`
- `frontend/src/tests/auth/authBootstrap.test.tsx`
- `frontend/src/tests/api/authClient.test.ts`

### Frontend - Modify

- `frontend/src/api/client.ts`
- `frontend/src/api/endpoints.ts`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/pages/Home.tsx`
- `frontend/src/store/useProjectStore.ts`
- `frontend/src/components/shared/MaterialGeneratorModal.tsx`

---

### Task 1: M1 增量迁移（仅 additive，不回填）

**Files:**
- Create: `backend/migrations/versions/016_auth_foundation_additive.py`
- Create: `backend/models/user.py`
- Create: `backend/models/user_oauth_account.py`
- Modify: `backend/models/__init__.py`
- Modify: `backend/models/project.py`
- Modify: `backend/models/material.py`
- Modify: `backend/models/task.py`
- Modify: `backend/models/reference_file.py`
- Modify: `backend/models/user.py`
- Modify: `backend/models/user_template.py`
- Test: `backend/tests/unit/test_auth_service.py`

- [ ] **Step 1: 写失败测试（新模型 + 唯一键 + 字段存在）**

```python
def test_oauth_identity_unique_key(db_session):
    # duplicate (provider, provider_user_id) -> IntegrityError
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_auth_service.py -k "unique or schema" -v`
Expected: FAIL.

- [ ] **Step 3: 实现 M1 migration 与模型**

```text
users (include is_active default true)
user_oauth_accounts (unique provider/provider_user_id)
nullable owner_id columns on projects/user_templates/materials/tasks/reference_files
nullable reference_files.mineru_extract_id + index
```

- [ ] **Step 4: 执行迁移**

Run: `cd backend && uv run alembic upgrade head`
Expected: success.

- [ ] **Step 5: 测试通过**

Run: `uv run pytest backend/tests/unit/test_auth_service.py -k "unique or schema" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/016_auth_foundation_additive.py backend/models backend/tests/unit/test_auth_service.py
git commit -m "feat(auth): add additive auth schema and owner columns (M1)"
```

### Task 2: M2 回填迁移 + mineru_extract_id 落库

**Files:**
- Create: `backend/migrations/versions/017_auth_owner_backfill.py`
- Modify: `backend/controllers/reference_file_controller.py`
- Modify: `backend/models/reference_file.py`
- Create: `backend/scripts/reassign_bootstrap_owner.py`
- Test: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（回填 owner + extract_id 持久化）**

```python
def test_backfill_owner_and_persist_extract_id(app):
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "backfill or mineru" -v`
Expected: FAIL.

- [ ] **Step 3: 实现 M2 migration（bootstrap + 回填）**

```text
bootstrap user must be created with is_active=false
reference_files owner fallback to bootstrap when project missing
```

- [ ] **Step 4: 解析流程持久化 `extract_id -> reference_files.mineru_extract_id`**

- [ ] **Step 5: 提供 bootstrap 交接脚本**

Run: `uv run python backend/scripts/reassign_bootstrap_owner.py --help`
Expected: has `--target-user-id` and `--dry-run`.

- [ ] **Step 6: 执行迁移并验证**

Run: `cd backend && uv run alembic upgrade head`
Expected: success.

- [ ] **Step 7: 测试通过**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "backfill or mineru" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/migrations/versions/017_auth_owner_backfill.py backend/controllers/reference_file_controller.py backend/models/reference_file.py backend/scripts/reassign_bootstrap_owner.py backend/tests/integration/test_auth_owner_isolation.py
git commit -m "feat(auth): backfill legacy ownership and persist mineru extract mapping (M2)"
```

### Task 3: OAuth Provider Adapters + Auth Service

**Files:**
- Create: `backend/services/auth/oauth_providers.py`
- Create: `backend/services/auth/auth_service.py`
- Create: `backend/services/auth/__init__.py`
- Modify: `backend/config.py`
- Test: `backend/tests/unit/test_oauth_providers.py`
- Test: `backend/tests/unit/test_auth_service.py`

- [ ] **Step 1: 写失败测试（GitHub/Azure China normalize）**

```python
def test_github_email_from_verified_primary(): ...
def test_azure_email_fallback_to_upn(): ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_oauth_providers.py backend/tests/unit/test_auth_service.py -v`
Expected: FAIL.

- [ ] **Step 3: 实现 provider 抽象 + GitHubOAuth + AzureChinaOAuth**

- [ ] **Step 4: 实现 `AuthService.upsert_user_from_oauth()`（provider + provider_user_id 唯一）**

- [ ] **Step 5: 配置项接入**

```text
GITHUB_CLIENT_ID/SECRET
AZURE_CLIENT_ID/SECRET/AUTH_URL/TOKEN_URL/USER_INFO_URL
```

- [ ] **Step 6: 测试通过**

Run: `uv run pytest backend/tests/unit/test_oauth_providers.py backend/tests/unit/test_auth_service.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/auth backend/config.py backend/tests/unit/test_oauth_providers.py backend/tests/unit/test_auth_service.py
git commit -m "feat(auth): implement OAuth adapters and auth account upsert service"
```

### Task 4: Auth API + Session/Cookie/CORS Contract

**Files:**
- Create: `backend/controllers/auth_controller.py`
- Create: `backend/utils/auth.py`
- Modify: `backend/controllers/__init__.py`
- Modify: `backend/utils/__init__.py`
- Modify: `backend/app.py`
- Modify: `backend/config.py`
- Test: `backend/tests/unit/test_api_auth.py`

- [ ] **Step 1: 写失败测试（state 校验 + me 401 + inactive user）**

```python
def test_auth_me_unauthenticated_returns_401(client): ...
def test_callback_invalid_state_redirects_login_reason(client): ...
def test_callback_inactive_user_redirects_user_disabled(client): ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/unit/test_api_auth.py -v`
Expected: FAIL.

- [ ] **Step 3: 实现 auth endpoints**

```text
GET /api/auth/oauth/<provider>/login
GET /api/auth/oauth/<provider>/callback
GET /api/auth/me
POST /api/auth/logout
```

- [ ] **Step 4: 在 callback 与 `require_auth` 中强制 `users.is_active` 检查**

- [ ] **Step 5: session/cookie/cors 配置落实**

```python
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = bool_env
PERMANENT_SESSION_LIFETIME = timedelta(days=7)
CORS(..., supports_credentials=True)
```

- [ ] **Step 6: credentials=true 时拒绝 wildcard CORS origin**

- [ ] **Step 7: 测试通过**

Run: `uv run pytest backend/tests/unit/test_api_auth.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/controllers/auth_controller.py backend/utils/auth.py backend/controllers/__init__.py backend/utils/__init__.py backend/app.py backend/config.py backend/tests/unit/test_api_auth.py
git commit -m "feat(auth): add auth api with secure session and active-user checks"
```

### Task 5: Owner-Scoped Task Visibility + Task Owner Writes

**Files:**
- Create: `backend/controllers/task_controller.py`
- Modify: `backend/controllers/__init__.py`
- Modify: `backend/app.py`
- Modify: `backend/models/task.py`
- Modify: `backend/controllers/project_controller.py`
- Modify: `backend/controllers/page_controller.py`
- Modify: `backend/controllers/export_controller.py`
- Modify: `backend/controllers/material_controller.py`
- Modify: `backend/controllers/restyle_controller.py`
- Modify: `backend/controllers/settings_controller.py`
- Modify: `backend/services/task_manager.py`
- Test: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（global task owner-only）**

```python
def test_global_task_status_owner_only(client_user_a, client_user_b): ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "global_task or settings" -v`
Expected: FAIL.

- [ ] **Step 3: 所有 `Task(...)` 创建点写入 `owner_id=current_user.id`**

```text
must cover:
project_controller.py
page_controller.py
export_controller.py
material_controller.py
restyle_controller.py
settings_controller.py
```

- [ ] **Step 4: 新增 `GET /api/tasks/<task_id>`（owner scope）**

- [ ] **Step 5: `/api/settings/tests/<task_id>/status` 同样应用 owner scope（或复用 /api/tasks）**

- [ ] **Step 6: 测试通过**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "global_task or settings" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/controllers/task_controller.py backend/controllers/__init__.py backend/app.py backend/models/task.py backend/controllers/project_controller.py backend/controllers/page_controller.py backend/controllers/export_controller.py backend/controllers/material_controller.py backend/controllers/restyle_controller.py backend/controllers/settings_controller.py backend/services/task_manager.py backend/tests/integration/test_auth_owner_isolation.py
git commit -m "feat(authz): enforce owner-scoped task writes and reads across all task endpoints"
```

### Task 6: 控制器 Owner Scope + Global Auth Guard Rollout

**Files:**
- Modify: `backend/controllers/project_controller.py`
- Modify: `backend/controllers/page_controller.py`
- Modify: `backend/controllers/export_controller.py`
- Modify: `backend/controllers/template_controller.py`
- Modify: `backend/controllers/material_controller.py`
- Modify: `backend/controllers/reference_file_controller.py`
- Modify: `backend/controllers/restyle_controller.py`
- Modify: `backend/controllers/settings_controller.py`
- Test: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（unauthenticated=401, non-owner=404）**

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "isolation or auth_required" -v`
Expected: FAIL.

- [ ] **Step 3: 全量改为 owner 查询与服务端 owner 赋值**

```text
Template endpoints must be explicitly covered:
- /api/projects/<project_id>/template (project owner required)
- /api/user-templates* (user template owner required)
- user-template create must set owner_id=current_user.id server-side
```

- [ ] **Step 4: 对所有业务 endpoint 显式应用 `require_auth`（`/api/output-language` 允许 public read-only）**

- [ ] **Step 5: 测试通过**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "isolation or auth_required" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/controllers/project_controller.py backend/controllers/page_controller.py backend/controllers/export_controller.py backend/controllers/template_controller.py backend/controllers/material_controller.py backend/controllers/reference_file_controller.py backend/controllers/restyle_controller.py backend/controllers/settings_controller.py backend/tests/integration/test_auth_owner_isolation.py
git commit -m "feat(authz): apply owner scope and auth guard across protected business endpoints"
```

### Task 7: `/files/*` 归属校验加固（含 mineru 映射）

**Files:**
- Modify: `backend/controllers/file_controller.py`
- Modify: `backend/models/reference_file.py`
- Test: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（`/files/*` 未登录=401，非归属=404）**

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k files -v`
Expected: FAIL.

- [ ] **Step 3: 实现 DB 驱动归属解析**

```text
/files/<project_id>/* -> project.owner_id
/files/user-templates/<template_id>/* -> user_templates.owner_id
/files/materials/<filename> -> materials.owner_id
/files/mineru/<extract_id>/* -> reference_files.mineru_extract_id + owner_id
```

- [ ] **Step 4: 保留 path traversal 防护并固定语义（401/404）**

- [ ] **Step 5: 测试通过**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k files -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/controllers/file_controller.py backend/tests/integration/test_auth_owner_isolation.py
git commit -m "fix(security): harden file routes with ownership checks and 401/404 semantics"
```

### Task 8: 前端登录入口 + Bootstrap + Logout

**Files:**
- Create: `frontend/src/pages/Login.tsx`
- Create: `frontend/src/types/auth.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/endpoints.ts`
- Test: `frontend/src/tests/auth/authBootstrap.test.tsx`
- Test: `frontend/src/tests/api/authClient.test.ts`

- [ ] **Step 1: 写失败测试（未登录跳 `/login`，登录后进入应用）**

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx`
Expected: FAIL.

- [ ] **Step 3: 实现 login 页面（GitHub/Azure 按钮）**

- [ ] **Step 4: axios `withCredentials=true` + 401 拦截重定向**

- [ ] **Step 5: 实现 `/api/auth/me` 启动探测与 `POST /api/auth/logout`**

- [ ] **Step 6: 测试通过**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx src/tests/api/authClient.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Login.tsx frontend/src/types/auth.ts frontend/src/App.tsx frontend/src/main.tsx frontend/src/api/client.ts frontend/src/api/endpoints.ts frontend/src/tests/auth/authBootstrap.test.tsx frontend/src/tests/api/authClient.test.ts
git commit -m "feat(frontend-auth): add oauth login bootstrap and logout flow"
```

### Task 9: 前端切换 Global Material 轮询到 `/api/tasks/<task_id>`

**Files:**
- Modify: `frontend/src/api/endpoints.ts`
- Modify: `frontend/src/components/shared/MaterialGeneratorModal.tsx`
- Modify: `frontend/src/store/useProjectStore.ts`
- Test: `frontend/src/tests/api/authClient.test.ts`

- [ ] **Step 1: 写失败测试（global task 使用新端点）**

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test -- src/tests/api/authClient.test.ts`
Expected: FAIL.

- [ ] **Step 3: 新增 `getGlobalTaskStatus(taskId)` 并替换 material polling**

- [ ] **Step 4: 测试通过**

Run: `cd frontend && npm run test -- src/tests/api/authClient.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/endpoints.ts frontend/src/components/shared/MaterialGeneratorModal.tsx frontend/src/store/useProjectStore.ts frontend/src/tests/api/authClient.test.ts
git commit -m "fix(frontend-authz): switch global material polling to owner-scoped task endpoint"
```

### Task 10: M3 约束收紧迁移（最后执行）

**Files:**
- Create: `backend/migrations/versions/018_auth_owner_constraints.py`
- Modify: `backend/models/project.py`
- Modify: `backend/models/material.py`
- Modify: `backend/models/task.py`
- Modify: `backend/models/reference_file.py`
- Modify: `backend/models/user_template.py`
- Test: `backend/tests/integration/test_auth_owner_isolation.py`

- [ ] **Step 1: 写失败测试（owner_id 为空插入失败）**

```python
def test_owner_columns_non_null_after_m3(db_session): ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "constraint or non_null" -v`
Expected: FAIL.

- [ ] **Step 3: 执行 M3 migration（NOT NULL + FK）**

- [ ] **Step 4: 执行迁移并验证**

Run: `cd backend && uv run alembic upgrade head`
Expected: success.

- [ ] **Step 5: 测试通过**

Run: `uv run pytest backend/tests/integration/test_auth_owner_isolation.py -k "constraint or non_null" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/018_auth_owner_constraints.py backend/models backend/tests/integration/test_auth_owner_isolation.py
git commit -m "feat(auth): tighten owner constraints after auth rollout (M3)"
```

### Task 11: 全链路回归与验收

**Files:**
- Modify: `backend/tests/unit/test_api_material.py`
- Modify: `backend/tests/unit/test_api_project.py`
- Modify: `backend/tests/integration/test_full_workflow.py`
- Modify: `backend/tests/integration/test_restyle_flow.py`
- Modify: `frontend/src/tests/store/useProjectStore.test.ts`

- [ ] **Step 1: 增加登录后核心流程回归（generate/edit/export/restyle/material）**

- [ ] **Step 2: 后端关键测试**

Run: `uv run pytest backend/tests/unit/test_api_auth.py backend/tests/unit/test_api_material.py backend/tests/integration/test_auth_owner_isolation.py backend/tests/integration/test_restyle_flow.py -v`
Expected: PASS.

- [ ] **Step 3: 前端关键测试**

Run: `cd frontend && npm run test -- src/tests/auth/authBootstrap.test.tsx src/tests/store/useProjectStore.test.ts`
Expected: PASS.

- [ ] **Step 4: lint + smoke**

Run: `npm run lint && npm run test:backend && npm run test:frontend`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/tests frontend/src/tests
git commit -m "test(auth): add owner isolation and auth regression coverage"
```

---

## Guardrails During Implementation

- 每个任务：先失败测试，再最小实现，再通过验证。
- 禁止修改已执行 migration；只新增 revision。
- `401/404` 语义固定：未登录 `401`，已登录但无归属权限 `404`。
- `/api/settings*` 必须鉴权；`/api/output-language` 保持 public read-only。
- 只改计划列出的文件，避免混入无关变更。

## Rollout Checklist

- `cd backend && uv run alembic upgrade head`
- 配置并验证 GitHub/Azure China callback
- 监控 `oauth callback failure`, `401/404 ratio`, `files unauthorized` 与 `task polling success`
- 运行 bootstrap 资产交接脚本

## Unresolved Questions

- 是否首期支持 `next` 参数回跳（登录后回来源页）？当前默认回 `/`。
