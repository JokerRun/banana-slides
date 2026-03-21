# Env-Only Settings Lockdown Design

Date: 2026-03-21  
Project: banana-slides  
Status: Ready for implementation planning

## 1. Context

当前系统 `settings` 是全局单例，且任意已登录用户可通过 `/api/settings` 修改全局配置（含 API key/token）。

在“小团队共用 + 无管理员角色”的约束下，这有明显风险：

1. 任意成员可改全局密钥与模型配置。
2. 配置来源分裂（env + DB）导致排障困难。
3. 全局配置治理无清晰边界。

## 2. Goals

1. 运行时配置唯一真值源收敛到 env/secrets。
2. 应用内 settings 完全不可见、不可修改。
3. 提供安全切换 runbook 与可执行回滚路径。

## 3. Out Of Scope

1. 本阶段不引入 RBAC 或管理员角色。
2. 本阶段不实现 per-user settings。
3. 本阶段不新增后台管理界面。

## 4. Key Decisions

1. **Single source of truth**：配置仅来自 `.env` 或部署 secrets manager。
2. **Settings lockdown**：`/api/settings*` 全部锁定，不提供读写能力。
3. **Frontend lockdown**：前端移除 settings 导航与专属路由。
4. **Rollback model**：只支持代码版本回滚，不提供运行时开关切回。

## 5. Target Architecture

```text
Env / Secrets
  -> Flask Config
  -> Runtime Services (AI/MinerU/OCR)

No DB Settings Runtime Read/Write
No Frontend Settings Entry/Route
```

## 6. Runtime Config Inventory

以下配置项统一迁移为 env 真值源。

| Runtime concern | Legacy settings column | Target env source | Required | Secret | Missing policy |
|---|---|---|---|---|---|
| AI provider format | `ai_provider_format` | `AI_PROVIDER_FORMAT` | Yes | No | startup fail-fast |
| API base URL | `api_base_url` | `GOOGLE_API_BASE` or `OPENAI_API_BASE` | No | No | fallback to provider default |
| API key | `api_key` | `GOOGLE_API_KEY` or `OPENAI_API_KEY` | Yes | Yes | startup fail-fast |
| Text model | `text_model` | `TEXT_MODEL` | Yes | No | use config default only in local dev |
| Image model | `image_model` | `IMAGE_MODEL` | Yes | No | use config default only in local dev |
| Image caption model | `image_caption_model` | `IMAGE_CAPTION_MODEL` | No | No | disable caption fallback |
| MinerU base | `mineru_api_base` | `MINERU_API_BASE` | No | No | disable MinerU-related features |
| MinerU token | `mineru_token` | `MINERU_TOKEN` | No | Yes | disable MinerU-related features |
| Baidu OCR key | `baidu_ocr_api_key` | `BAIDU_OCR_API_KEY` | No | Yes | disable OCR-related features |
| Output language | `output_language` | `OUTPUT_LANGUAGE` | Yes | No | fallback to `zh` |
| Image resolution | `image_resolution` | `DEFAULT_RESOLUTION` | Yes | No | fallback to `2K` |
| Image aspect ratio | `image_aspect_ratio` | `DEFAULT_ASPECT_RATIO` | Yes | No | fallback to `16:9` |
| Description workers | `max_description_workers` | `MAX_DESCRIPTION_WORKERS` | Yes | No | fallback to `5` |
| Image workers | `max_image_workers` | `MAX_IMAGE_WORKERS` | Yes | No | fallback to `8` |
| Text reasoning toggle | `enable_text_reasoning` | `ENABLE_TEXT_REASONING` | Yes | No | fallback to `false` |
| Text thinking budget | `text_thinking_budget` | `TEXT_THINKING_BUDGET` | Yes | No | fallback to `1024` |
| Image thinking level | `image_thinking_level` | `IMAGE_THINKING_LEVEL` | Yes | No | fallback to `none` |

## 7. API Contract

## 7.1 Locked endpoints

1. `GET /api/settings` -> locked
2. `PUT /api/settings` -> locked
3. `POST /api/settings/reset` -> locked
4. `POST /api/settings/verify` -> locked

## 7.2 Access semantics

1. 未登录访问：保持现有 auth 语义，返回 `401 AUTH_REQUIRED`。
2. 已登录访问：统一返回 `403 SETTINGS_LOCKED`。

## 7.3 Error response

```json
{
  "success": false,
  "error": {
    "code": "SETTINGS_LOCKED",
    "message": "This instance is env-managed. Edit .env and restart service."
  }
}
```

## 8. Frontend Contract

1. 移除 settings 导航入口。
2. 移除 `/settings` 路由定义。
3. 访问 `/settings` 走通配路由，已登录用户重定向 `/`，未登录用户重定向 `/login`。
4. 删除前端中所有 `/api/settings*` 调用与对应类型依赖。

## 9. Backend Design

## 9.1 Config loading

1. 移除启动时 DB settings 覆盖 `app.config` 的路径。
2. 运行中仅依赖 `Config`（env）构建配置。

## 9.2 Settings controller behavior

1. 保留 blueprint 仅用于返回 locked response（兼容旧客户端调用路径）。
2. 不再触发 `_sync_settings_to_config` 与任何 settings DB 写入逻辑。

## 9.3 Settings runtime call-site audit

实施必须包含 settings 读写调用点审计，保证除数据清理迁移外不再存在运行时 `Settings` 依赖。

Audit scope:

1. app startup hooks
2. controllers/services/background tasks
3. helper/utils
4. maintenance scripts/CLI

## 10. Cutover Runbook

## 10.1 Pre-cutover

1. 导出当前 `settings` 表快照（备份用途）。
2. 对照第 6 节清单，将当前实际值写入 `.env`/secrets manager。
3. 运行 preflight：检查 required env 是否全部存在。

## 10.2 Deploy

1. 发布 settings lockdown 版本。
2. 重启 backend。

## 10.3 Post-deploy verification

1. `GET /health` 正常。
2. 核心业务 smoke（auth/project/page/material/file）正常。
3. `/api/settings*` 符合 locked 语义。

## 11. Data Hygiene

建议在稳定后执行一次清理迁移，清空历史敏感字段，降低残留泄漏面。

Cleanup targets:

1. `settings.api_key`
2. `settings.mineru_token`
3. `settings.baidu_ocr_api_key`

## 12. Observability And Security Guardrails

1. 启动日志固定打印 `env_only_mode=true`。
2. 启动时若检测到 DB settings 仍存在敏感值，仅告警且不用于运行配置。
3. 统一统计 `SETTINGS_LOCKED` 命中次数，识别遗留客户端调用。
4. 禁止在日志中输出任何敏感配置明文。

## 13. Migration Phases And DoD

## Phase S1: API/UI lockdown

Definition of Done:

1. `/api/settings*` 全部 locked。
2. 前端无 settings 入口与路由。
3. 旧 settings API 前端调用全部移除。

## Phase S2: source simplification

Definition of Done:

1. DB->config 覆盖路径完全移除。
2. settings runtime call-site 审计完成且无残留。
3. required env preflight 已接入启动流程。

## Phase S3: data hygiene (optional)

Definition of Done:

1. 敏感字段已清空。
2. 回归验证通过。

## 14. Testing Strategy

1. API contract test：未登录 401、已登录 403（`SETTINGS_LOCKED`）。
2. Frontend routing test：`/settings` 被重定向，不可见。
3. Env effect test：修改 env + 重启后生效；不重启不生效。
4. No-leak test：任意 API/日志/启动输出不暴露密钥明文。
5. End-to-end smoke：核心业务主链不受影响。

## 15. Rollback Strategy

仅支持**代码版本回滚**，不提供运行时 feature-flag 回切。

Rollback steps:

1. 回滚到上一稳定版本。
2. 重启服务。
3. 按旧版本 smoke 清单复核。

## 16. Final Acceptance Criteria

1. 普通登录用户无法读取或修改任何 settings。
2. 运行时配置仅由 env/secrets 决定。
3. 团队配置变更流程统一为“改 env + 重启”。
4. 无敏感配置通过 API、前端页面或日志暴露。
