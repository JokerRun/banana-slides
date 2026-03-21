# Env-Only Settings Lockdown Design

Date: 2026-03-21  
Project: banana-slides  
Status: Draft for implementation planning

## 1. Context

当前系统 `settings` 是全局单例，并且在 OAuth 上线后仍允许任意已登录用户通过 `/api/settings` 修改全局配置（包含 API key/token）。

在“小团队共用 + 无管理员角色”的约束下，这会带来高风险：

1. 任意成员可覆盖全局密钥与模型配置。
2. 配置来源分裂（env + DB）导致排障复杂。
3. 配置治理缺乏清晰边界，责任不明确。

## 2. Goals And Scope

## In Scope

1. 将运行时配置真值源收敛为 `.env`（或部署 secrets），不再由数据库驱动。
2. 禁止应用内 settings 的读与写（前后端均不可见、不可改）。
3. 保留系统稳定性与可回滚能力。

## Out Of Scope

1. 本阶段不引入管理员角色/RBAC。
2. 本阶段不实现按用户个性化 settings。
3. 本阶段不构建后台管理页面。

## 3. Key Decisions

1. **Single source of truth**：配置仅来自 env/secrets manager。
2. **Settings API lockdown**：`GET/PUT/RESET` 统一禁用。
3. **UI lockdown**：前端移除 Settings 入口与页面路由。
4. **Safe defaults**：保留非破坏性回滚路径（可恢复旧行为）。

## 4. Target Architecture

```text
Env / Secrets
    -> Flask Config
    -> Runtime Services (AI/MinerU/OCR)

No DB Settings Read/Write Path
No Frontend Settings UI
```

## 5. API Contract Changes

## Deprecated/Locked Endpoints

1. `GET /api/settings` -> `403 SETTINGS_LOCKED`
2. `PUT /api/settings` -> `403 SETTINGS_LOCKED`
3. `POST /api/settings/reset` -> `403 SETTINGS_LOCKED`

Response contract:

```json
{
  "success": false,
  "error": {
    "code": "SETTINGS_LOCKED",
    "message": "This instance is env-managed. Edit .env and restart service."
  }
}
```

## Optional Endpoint

`POST /api/settings/verify` 建议同样禁用以保持策略一致性（无 settings 可见/可改）。若保留需仅内部使用且不暴露任何配置细节。

## 6. Backend Design

## 6.1 Config Loading

1. 移除/停用 `app startup` 时的 DB settings 覆盖逻辑。
2. 运行中仅依赖 `Config`（env）提供配置。

## 6.2 Settings Controller

1. Settings blueprint 保留最小兼容壳，所有 settings 路由直接返回 `403 SETTINGS_LOCKED`。
2. 不再调用 `_sync_settings_to_config`；不再触发 settings DB 写入。

## 6.3 Data Model Handling

1. `settings` 表可暂时保留（兼容旧版本和回滚）。
2. 增加一次性数据清理迁移（可选但推荐）：清空历史敏感字段，避免残留泄漏风险。

Suggested cleanup targets:

1. `settings.api_key`
2. `settings.mineru_token`
3. `settings.baidu_ocr_api_key`

## 7. Frontend Design

1. 从导航移除 Settings 入口。
2. 从路由移除 `/settings` 页面。
3. 任何遗留 settings API 调用清理掉，避免出现 403 噪声。

## 8. Ops Workflow

```text
Change config
  -> edit .env / secret
  -> restart backend
  -> smoke check (/health + core flows)
```

## 9. Error Handling And Observability

1. 启动日志打印 `env-only mode enabled`。
2. 如检测到 DB settings 非空敏感字段，仅打印警告（不参与运行配置）。
3. 所有锁定接口统一错误码 `SETTINGS_LOCKED` 便于监控聚合。

## 10. Migration Strategy

## Phase S1: Lockdown

1. 后端 settings API 全部返回 403。
2. 前端移除 settings UI/route。

## Phase S2: Source Simplification

1. 移除 DB 覆盖 config 路径。
2. 添加日志与告警（env-only 标识）。

## Phase S3: Data Hygiene (optional)

1. 执行敏感字段清理迁移。

## 11. Testing Strategy

1. API contract test：`GET/PUT/RESET /api/settings` 均为 403 + `SETTINGS_LOCKED`。
2. E2E smoke：核心业务流不受影响（project/page/material/auth/file）。
3. Env effect test：修改 env + 重启后配置生效；不重启不生效。
4. Frontend route test：`/settings` 不可访问（404 或重定向）。

## 12. Rollback Plan

1. 恢复 settings API 原行为。
2. 恢复 DB->app.config 覆盖逻辑。
3. 恢复前端 settings 入口与路由。

## 13. Acceptance Criteria

1. 普通登录用户无法读取/修改任何 settings。
2. 所有运行时配置仅由 env 决定。
3. 团队配置变更流程统一为“改 env + 重启”。
4. 无敏感配置通过 API 暴露。
