# OAuth2 User Management Design (GitHub + Azure China 21V)

Date: 2026-03-20  
Project: banana-slides  
Status: Draft for implementation planning

## 1. Context

Current backend is Flask + SQLite, with no user identity model and no request-level authorization boundary. Most business endpoints read/write project data directly by `project_id`.

The target is to add OAuth2 login and strict per-user data isolation.

## 2. Goals And Scope

## In Scope

1. OAuth2 Authorization Code login via GitHub and Azure China (21V tenant).
2. Cookie-based authentication with Flask signed session cookies (HttpOnly).
3. User identity model with external account binding.
4. Data isolation by owner for project-related resources.
5. Frontend login entry, current-user bootstrap, and logout.

## Out Of Scope

1. RBAC and organization-level multi-tenant authorization.
2. Automatic account merge by email across providers.
3. External IdP aggregation platform (Auth0/Keycloak) in this phase.

## 3. Key Decisions

1. **Identity key**: unique by `(provider, provider_user_id)`.
2. **Session model**: Flask signed cookie session (no server-side session store in phase 1).
3. **Provider set**: `github`, `azure` (Azure China / 21V endpoints).
4. **Isolation boundary**: owner-based filtering for all user-owned resources.
5. **OAuth profile source**: use provider API profile endpoints (`/user` + `/user/emails`, Graph `/me`) as source of truth in phase 1.

## 4. Architecture Overview

```text
Browser
  -> /api/auth/oauth/<provider>/login
  -> Provider authorize page
  -> /api/auth/oauth/<provider>/callback
  -> Backend exchanges code + fetches profile
  -> Upsert user + oauth account
  -> Set session cookie
  -> Redirect frontend app

Authenticated Browser
  -> /api/auth/me
  -> /api/projects/* (owner filtered)
  -> /files/* (ownership checked before file send)
```

## 4.1 Deployment Assumption

1. Production runs in same-site topology: frontend nginx serves app and reverse-proxies `/api` and `/files` to backend.
2. Cookie policy is designed for same-site navigation and callback flow.
3. Local development uses either same-origin proxy mode (recommended) or explicit CORS+credentials allowlist.

## 5. Provider Configuration

## GitHub

1. `GITHUB_CLIENT_ID`
2. `GITHUB_CLIENT_SECRET`
3. Scope: `user:email`
4. Callback URL: `https://<domain>/api/auth/oauth/github/callback`

## Azure China (21V)

1. `AZURE_CLIENT_ID`
2. `AZURE_CLIENT_SECRET`
3. `AZURE_AUTH_URL` (tenant-specific China cloud authorize endpoint)
4. `AZURE_TOKEN_URL` (tenant-specific China cloud token endpoint)
5. `AZURE_USER_INFO_URL` (`https://microsoftgraph.chinacloudapi.cn/v1.0/me`)
6. Scope: `openid profile email offline_access https://microsoftgraph.chinacloudapi.cn/User.Read`
7. Callback URL: `https://<domain>/api/auth/oauth/azure/callback`

## 5.1 Provider Identity Mapping And Behavior

## GitHub

1. Authorization scope is `user:email`.
2. Profile retrieval sequence is mandatory: `GET /user` then `GET /user/emails`.
3. `provider_user_id = /user.id`.
4. `provider_username = /user.login`.
5. `display_name = /user.name` if present, otherwise `/user.login`.
6. `email_at_provider` uses verified primary email from `/user/emails`; if none exists, store null.
7. `avatar_url = /user.avatar_url`.

## Azure China (21V)

1. Profile source is Graph API `GET /me` (China cloud endpoint configured via `AZURE_USER_INFO_URL`).
2. `provider_user_id = /me.id`.
3. `provider_username = /me.userPrincipalName`.
4. `display_name = /me.displayName`.
5. `email_at_provider = /me.mail` fallback `/me.userPrincipalName`.
6. `avatar_url` is optional and can be null in phase 1.

## Nonce Policy

1. OAuth `state` is required for both providers and must be validated.
2. `nonce` is optional metadata in phase 1 and not used as identity source validation gate.
3. The system does not parse/validate provider ID tokens in phase 1.

## 6. Data Model Changes

## New Tables

### `users`

1. `id` (uuid string, PK)
2. `display_name` (nullable)
3. `avatar_url` (nullable)
4. `is_active` (bool, default true)
5. `created_at`, `updated_at`

### `user_oauth_accounts`

1. `id` (uuid string, PK)
2. `user_id` (FK -> users.id, indexed)
3. `provider` (`github` / `azure`, indexed)
4. `provider_user_id` (string, indexed)
5. `provider_username` (nullable)
6. `email_at_provider` (nullable)
7. `raw_profile` (JSON text, nullable)
8. `created_at`, `updated_at`
9. Unique constraint: `(provider, provider_user_id)`

## Existing Tables To Extend

1. `projects.owner_id` (FK users.id, indexed, eventually non-null)
2. `user_templates.owner_id` (FK users.id, indexed, eventually non-null)
3. `materials.owner_id` (FK users.id, indexed; required because global materials may have `project_id = null`)
4. `tasks.owner_id` (FK users.id, indexed)
5. `reference_files.owner_id` (FK users.id, indexed)
6. `reference_files.mineru_extract_id` (string, indexed, nullable at first; used for `/files/mineru/<extract_id>/*` ownership mapping)

## 7. Migration Strategy

## Phase M1 (safe additive)

1. Add `users`, `user_oauth_accounts`.
2. Add nullable `owner_id` columns to target tables.
3. Add required indexes and uniqueness constraints.

## Phase M2 (backfill)

1. Create bootstrap user (e.g., `bootstrap-local-user`).
2. Backfill existing rows in `projects`, `user_templates`, `materials`, `tasks` with bootstrap user.
3. Backfill existing rows in `reference_files` using related project owner; fallback to bootstrap user if project is missing.
4. Keep legacy `reference_files.mineru_extract_id` as null (only new parses populate it).
5. Verify counts and referential integrity.

## Phase M3 (tighten)

1. Set `projects.owner_id`, `user_templates.owner_id`, `tasks.owner_id`, `materials.owner_id`, `reference_files.owner_id` to non-null.
2. Enable auth guard globally for business endpoints.

## Phase M4 (legacy ownership handoff)

1. Add one admin-only script to reassign bootstrap-owned legacy resources to a real account by `target_user_id`.
2. Keep bootstrap user disabled for login.
3. Run handoff before production cutover, or explicitly accept bootstrap-owned resources as inaccessible historical data.

## 8. Backend Components

## New Modules

1. `backend/services/auth/oauth_providers.py`
2. `backend/services/auth/auth_service.py`
3. `backend/controllers/auth_controller.py`
4. `backend/utils/auth.py` (session + decorator helpers)

## OAuth Provider Adapter Design

Reuse `OAuth` base + provider-specific adapters (as in referenced Dify style), but add strict validation and shared error mapping.

1. `GitHubOAuth`
2. `AzureChinaOAuth`

Each provider implements:

1. `get_authorization_url(state, nonce)`
2. `exchange_code_for_token(code)`
3. `fetch_user_info(access_token)`
4. `normalize_user_info(...) -> { provider_user_id, display_name, email, avatar_url, username }`

## 9. Auth API Surface

1. `GET /api/auth/oauth/<provider>/login`
2. `GET /api/auth/oauth/<provider>/callback`
3. `GET /api/auth/me`
4. `POST /api/auth/logout`

Behavior:

1. login endpoint creates and stores `state`/`nonce` in short-lived server session.
2. callback validates state, exchanges token, fetches profile, upserts user/account, sets authenticated session.
3. callback rotates session identity by calling `session.clear()` before setting auth keys.
4. `me` returns normalized user profile for frontend bootstrap.
5. logout clears session cookie via `session.clear()`.

## 9.1 Browser Redirect And API Error Contract

## Browser endpoints (`/login` and `/callback`)

1. Login endpoint returns HTTP redirect to provider authorize URL.
2. Callback success redirects to frontend route `/`.
3. Callback failure redirects to `/login?reason=<error_code>`.

## JSON endpoints (`/me` and `/logout`)

1. `/api/auth/me` unauthenticated returns `401` JSON: `{ "code": "AUTH_REQUIRED", "message": "..." }`.
2. `/api/auth/logout` always returns `200` and clears session state.
3. Unsupported provider returns `400` JSON on login endpoint if provider is requested via API call mode.

## 10. Session And Security Controls

1. Use `SECRET_KEY` for signed session.
2. Session payload only stores `user_id`, `provider`, `provider_user_id`, and lightweight metadata (no provider access token).
3. Cookie attributes: `HttpOnly`, `Secure` (true on HTTPS), `SameSite=Lax`.
4. Configure session TTL via Flask permanent session lifetime (default 7 days).
5. CSRF/Replay protection via OAuth `state`.
6. For cross-origin local dev (if used), enable explicit CORS allowlist and `supports_credentials=true`; never use wildcard with credentials.
7. Logout clears cookie and invalidates in-browser session state.
8. Session fixation mitigation: clear session before setting authenticated identity on callback.
9. Centralized auth errors with non-sensitive payloads.
10. Do not return provider access tokens to frontend.
11. Enforce active user check (`is_active`) in auth decorator.

## 11. Authorization Integration

## Request Guard

Introduce `@require_auth` and a helper to fetch current user id from session.

Write-path rules (mandatory):

1. `owner_id` is assigned server-side only and ignored/rejected if sent by client.
2. Any create on child resources must verify parent ownership first.
3. Any update must prevent cross-owner re-parenting (`project_id` reassignment to foreign project).
4. Any delete must resolve resource under current owner scope before deletion.

## Owner Filter Pattern

Replace direct `Model.query.get(id)` usage for user-owned resources with owner-scoped queries, e.g.:

```text
Project.query.filter_by(id=project_id, owner_id=current_user.id).first()
```

Apply same policy to create/list/update/delete flows in:

1. `project_controller.py`
2. `page_controller.py` (via owner-validated project/page traversal)
3. `export_controller.py`
4. `template_controller.py` (`/api/user-templates`)
5. `material_controller.py`
6. `reference_file_controller.py`

## 11.1 Resource Authorization Matrix

1. `/api/projects*`: auth required, ownership root = `projects.owner_id`.
2. `/api/projects/<project_id>/pages*`: auth required, ownership derived from parent project.
3. `/api/projects/<project_id>/tasks*`: auth required, ownership root = `tasks.owner_id` and project cross-check.
4. `/api/projects/<project_id>/export*`: auth required, ownership derived from parent project.
5. `/api/projects/<project_id>/template*`: auth required, ownership derived from parent project.
6. `/api/user-templates*`: auth required, ownership root = `user_templates.owner_id`.
7. `/api/materials*` and `/api/projects/<project_id>/materials*`: auth required, ownership root = `materials.owner_id` with optional project cross-check.
8. `/api/reference-files*`: auth required, ownership root = `reference_files.owner_id` and project cross-check where applicable.
9. `/api/projects/restyle`: auth required, creates project with `owner_id = current_user.id`.
10. `/api/projects/<project_id>/restyle/generate`: auth required, ownership derived from parent project.
11. `/api/projects/<project_id>/pages/<page_id>/restyle/generate`: auth required, ownership derived from parent project and page-project consistency.
12. `/api/tasks/<task_id>`: auth required, for non-project/global tasks, ownership root = `tasks.owner_id`.
13. `/files/<project_id>/*`: auth required, ownership derived from project owner.
14. `/files/user-templates/<template_id>/*`: auth required, ownership derived from `user_templates.owner_id`.
15. `/files/materials/<filename>`: auth required, ownership resolved by matching material record and owner.
16. `/files/mineru/<extract_id>/*`: auth required, ownership resolved by `reference_files.mineru_extract_id` lookup.

## 11.2 Global Task Policy

1. Keep existing `tasks.project_id` non-null constraint for compatibility.
2. Use sentinel `project_id = 'global'` for non-project material generation tasks (current behavior).
3. Add `owner_id` to every task row, including `project_id='global'` tasks.
4. Add API endpoint `GET /api/tasks/<task_id>` for global tasks, authorization by `tasks.owner_id` only.
5. Keep `GET /api/projects/<project_id>/tasks/<task_id>` for project-bound tasks with dual checks (`task.owner_id` + `task.project_id`).
6. Frontend material-center polling must switch to `/api/tasks/<task_id>` for global material tasks.

## File Access Hardening

For `/files/...` endpoints:

1. Resolve ownership using DB lookup, never by path prefix alone.
2. For project-scoped paths, enforce `project.owner_id == current_user.id`.
3. For user-template paths, enforce `user_template.owner_id == current_user.id`.
4. For materials global path, map filename to material row and enforce `material.owner_id == current_user.id`.
5. For mineru paths, map `extract_id` to `reference_files.mineru_extract_id` and enforce owner match.
6. Reject not-owned resources with 404.
7. Keep path traversal checks already present.

## 12. Frontend Changes

1. Add login page with provider buttons (GitHub, Azure).
2. App bootstrap calls `GET /api/auth/me`.
3. If unauthenticated, redirect to `/login`.
4. Add logout action calling `POST /api/auth/logout`.
5. Configure axios to include credentials consistently.
6. Add 401 interceptor routing to login.

Local dev contract:

1. Preferred: run frontend proxy so browser sees same-origin `/api`.
2. If split origins are used, backend CORS must use explicit origins and credentials support.

## 13. Error Handling

## OAuth Errors

1. invalid/missing `state` -> redirect `/login?reason=oauth_state_invalid`.
2. provider returned `error` or missing `code` -> redirect `/login?reason=oauth_callback_invalid`.
3. provider exchange failure -> redirect `/login?reason=oauth_token_exchange_failed`.
4. profile retrieval/parsing failure -> redirect `/login?reason=oauth_profile_failed`.
5. disabled user -> redirect `/login?reason=user_disabled`.

## Authorization Errors

1. unauthenticated -> 401.
2. resource not owned -> 404 (preferred to avoid resource enumeration).

## 14. Testing Strategy

## Unit Tests

1. provider adapter URL building + token/profile parse.
2. auth service upsert logic for `users` and `user_oauth_accounts`.
3. session guard behavior for authenticated/unauthenticated requests.

## Integration Tests

1. full login callback happy path (mock provider APIs).
2. owner isolation: user A cannot read/update/delete user B project.
3. file endpoint ownership enforcement.

## Regression Tests

1. authenticated create/generate/export workflow unchanged.
2. polling and task status remain user-consistent.

## 15. Rollout Plan

1. Deploy migration M1 and M2 first.
2. Deploy backend auth endpoints and owner-filter logic behind feature flag if needed.
3. Deploy frontend login/bootstrap UI.
4. Enable strict auth requirement globally after smoke tests.
5. Monitor auth failures, 401/404 ratios, and task isolation logs.

## 16. Risks And Mitigations

1. **Risk**: partial owner filter coverage.  
   **Mitigation**: central query helpers + targeted integration tests per controller.

2. **Risk**: file URL bypass for unauthorized users.  
   **Mitigation**: ownership check in `/files` handlers before `send_from_directory`.

3. **Risk**: legacy data with null owner IDs causing false 404.  
   **Mitigation**: migration backfill and constraint hardening sequence.

4. **Risk**: leaked OAuth client secrets in history/env misuse.  
   **Mitigation**: rotate secrets immediately and enforce `.env` exclusion.

## 17. Acceptance Criteria

1. User can sign in with GitHub and Azure China.
2. `/api/auth/me` returns stable authenticated identity.
3. All project operations are isolated by owner.
4. User template/material/task visibility is owner-isolated.
5. Unauthorized file reads are blocked.
6. Existing authenticated product flows (generate/export/edit) work without regressions.
