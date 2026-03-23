# OAuth 登录配置指南

本文档说明如何为 Banana Slides 配置 GitHub 和 Azure China 21V OAuth 登录。

---

## 架构概览

```
Browser ──▶ nginx (:443) ──▶ frontend (SPA)
                │
                └── /api/* ──▶ backend (:5000)
```

生产环境中 nginx 将 `/api/*` 反向代理到后端，前后端**共享同一个域名**（如 `https://slide.example.com`）。
OAuth callback URL 走公共域名，由 nginx 转发到后端处理。

```text
                  ┌──────────────────────────────────────────────────────────┐
                  │                   OAuth Flow                            │
                  │                                                         │
  Browser         │  slide.example.com (nginx)          Backend (:5000)    │
    │              │        │                                │              │
    │──── click ──▶│── /api/auth/oauth/{provider}/login ─▶ build state ───│─▶ 302 provider
    │              │                                        │              │
    │◀── provider authorizes ───────────────────────────────│              │
    │              │                                        │              │
    │──── callback▶│── /api/auth/oauth/{provider}/callback▶ exchange code  │
    │              │                                   set session cookie   │
    │◀── 302 ─────│◀── redirect to FRONTEND_URL ◀──────────│              │
    │              │                                        │              │
    │──── app loads, GET /api/auth/me (cookie attached) ──▶│              │
    │◀── 200 { user } ◀──────────────────────────────────────│              │
                  └──────────────────────────────────────────────────────────┘
```

> `{provider}` 可以是 `github` 或 `azure`。

---

## 1. 创建 GitHub OAuth App

1. 前往 [GitHub → Settings → Developer Settings → OAuth Apps → New](https://github.com/settings/applications/new)

2. 填写表单：

   | 字段                         | 开发环境                                                    | 生产环境（以 `slide.example.com` 为例）                              |
   |------------------------------|-------------------------------------------------------------|----------------------------------------------------------------------|
   | **Application name**         | `Banana Slides (dev)`                                       | `Banana Slides`                                                      |
   | **Homepage URL**             | `http://localhost:3000`                                     | `https://slide.example.com`                                          |
   | **Authorization callback URL** | `http://localhost:5000/api/auth/oauth/github/callback`   | `https://slide.example.com/api/auth/oauth/github/callback`           |

   > ⚠️ **callback URL 必须与 `.env` 中的 `GITHUB_REDIRECT_URI` 完全一致**，包括协议和尾部斜杠。

3. 创建后记录 **Client ID** 和 **Client Secret**。

---

## 2. 创建 Azure China 21V OAuth App

Azure China（世纪互联运营）的 OAuth 配置比 GitHub 复杂，需要在 **Azure 中国版门户** 注册应用并配置 API 权限。

> ⚠️ **Azure 中国版（21Vianet）与 Azure 国际版是完全隔离的环境**，endpoint 域名不同，不可混用。

### 2.1 前置条件

- 一个 **Azure 中国版（21Vianet）** 租户（tenant），通常由公司 IT 管理员创建
- 拥有该租户的 **全局管理员** 或 **应用程序管理员** 角色（用于注册应用和授权 API 权限）
- 如果你只有普通用户权限，需要联系 IT 管理员协助完成步骤 2.2 ~ 2.5

### 2.2 注册应用

1. 登录 [Azure 中国门户](https://portal.azure.cn)

2. 导航到 **Microsoft Entra ID**（原 Azure Active Directory）→ **应用注册** → **新注册**

3. 填写表单：

   | 字段 | 值 |
   |------|-----|
   | **名称** | `Banana Slides` |
   | **受支持的帐户类型** | 根据需求选择（见下表） |
   | **重定向 URI (Web)** | `https://slide.example.com/api/auth/oauth/azure/callback` |

   **帐户类型选择指南：**

   | 选项 | 适用场景 |
   |------|---------|
   | 仅此组织目录中的帐户（单租户） | 仅限公司内部员工登录 |
   | 任何组织目录中的帐户（多租户） | 允许任何 Azure 中国版组织的用户登录 |

   > 💡 大多数内部部署场景选择 **单租户** 即可。

4. 注册完成后，在 **概述** 页面记录：
   - **应用程序(客户端) ID** → 即 `AZURE_CLIENT_ID`
   - **目录(租户) ID** → 用于构建 endpoint URL

### 2.3 创建客户端密码

1. 在应用注册页面左侧 → **证书和密码** → **客户端密码** → **新客户端密码**

2. 填写描述（如 `banana-slides-prod`），选择过期时间

   > ⚠️ Azure 客户端密码有过期时间（最长 24 个月），到期后需要重新生成并更新 `.env`，否则登录会失败。建议设置日历提醒。

3. 记录 **值**（Value）→ 即 `AZURE_CLIENT_SECRET`

   > ⚠️ 此值只显示一次，离开页面后无法再查看。

### 2.4 配置 API 权限

1. 左侧 → **API 权限** → **添加权限** → **Microsoft Graph（中国版）**

2. 选择 **委托的权限**，勾选以下权限：

   | 权限 | 用途 |
   |------|------|
   | `openid` | OpenID Connect 登录 |
   | `profile` | 读取用户 displayName |
   | `email` | 读取用户邮箱 |
   | `User.Read` | 读取登录用户的基本信息 |
   | `offline_access` | 获取 refresh token（可选） |

3. **重要：** 点击 **代表 \<租户名\> 授予管理员同意**

   > 如果不授予管理员同意，普通用户登录时会看到"需要管理员审批"的错误页面。

### 2.5 确定 Endpoint URL

Azure China 21V 的 endpoint 取决于你的 **租户 ID** 和 **帐户类型**：

**单租户（推荐）：**

```text
AUTH_URL:      https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/authorize
TOKEN_URL:     https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/token
USER_INFO_URL: https://microsoftgraph.chinacloudapi.cn/v1.0/me
```

**多租户：**

```text
AUTH_URL:      https://login.partner.microsoftonline.cn/common/oauth2/v2.0/authorize
TOKEN_URL:     https://login.partner.microsoftonline.cn/common/oauth2/v2.0/token
USER_INFO_URL: https://microsoftgraph.chinacloudapi.cn/v1.0/me
```

将 `{tenant-id}` 替换为步骤 2.2 中记录的 **目录(租户) ID**。

> ⚠️ **不要使用国际版域名！** 常见错误对照：
>
> | ❌ 国际版（不可用） | ✅ 中国版 |
> |---|---|
> | `login.microsoftonline.com` | `login.partner.microsoftonline.cn` |
> | `graph.microsoft.com` | `microsoftgraph.chinacloudapi.cn` |

### 2.6 Azure 配置一览图

```text
Azure 中国门户 (portal.azure.cn)
└── Microsoft Entra ID
    └── 应用注册
        └── Banana Slides
            ├── 概述
            │   ├── 应用程序(客户端) ID  ──▶  AZURE_CLIENT_ID
            │   └── 目录(租户) ID        ──▶  用于 AUTH_URL / TOKEN_URL
            ├── 证书和密码
            │   └── 客户端密码 (Value)    ──▶  AZURE_CLIENT_SECRET
            ├── 身份验证
            │   └── 重定向 URI (Web)     ──▶  AZURE_REDIRECT_URI
            └── API 权限
                └── Microsoft Graph (中国版)
                    ├── openid
                    ├── profile
                    ├── email
                    ├── User.Read
                    └── offline_access
```

---

## 3. 环境变量配置

### 3.1 生产环境（Docker Compose 部署）

假设域名为 `https://slide.example.com`，编辑项目根目录 `.env`：

```bash
# ========== 必填：Flask Session 签名密钥 ==========
# 生产环境务必设置一个随机强密码，不要使用默认值
SECRET_KEY=your-random-secret-key-at-least-32-chars

# ========== 必填：前端地址（OAuth callback 后重定向目标）==========
# 生产环境前后端同域，填公共域名即可
FRONTEND_URL=https://slide.example.com

# ========== 必填：CORS ==========
CORS_ORIGINS=https://slide.example.com

# ========== 必填：Session Cookie 安全 ==========
# HTTPS 部署时必须设为 true
SESSION_COOKIE_SECURE=true

# ========== OAuth - GitHub ==========
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
GITHUB_REDIRECT_URI=https://slide.example.com/api/auth/oauth/github/callback

# ========== OAuth - Azure China 21V ==========
AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
AZURE_CLIENT_SECRET=your-azure-client-secret-value
AZURE_REDIRECT_URI=https://slide.example.com/api/auth/oauth/azure/callback
# 单租户：将 {tenant-id} 替换为你的目录(租户) ID
# 多租户：使用 common 替代 {tenant-id}
AZURE_AUTH_URL=https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/authorize
AZURE_TOKEN_URL=https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/token
# 通常不需要修改，默认值即可
# AZURE_USER_INFO_URL=https://microsoftgraph.chinacloudapi.cn/v1.0/me
```

**环境变量速查表：**

| 变量 | 来源 | 必填 |
|------|------|:----:|
| `GITHUB_CLIENT_ID` | GitHub OAuth App → Client ID | ✅ |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App → Client Secret | ✅ |
| `GITHUB_REDIRECT_URI` | 与 GitHub OAuth App callback URL 一致 | ✅ |
| `AZURE_CLIENT_ID` | Azure 门户 → 应用注册 → 概述 → 应用程序(客户端) ID | ⚡ |
| `AZURE_CLIENT_SECRET` | Azure 门户 → 证书和密码 → 客户端密码 Value | ⚡ |
| `AZURE_REDIRECT_URI` | 与 Azure 门户重定向 URI 一致 | ⚡ |
| `AZURE_AUTH_URL` | 见 2.5 节，需替换 tenant-id | ⚡ |
| `AZURE_TOKEN_URL` | 见 2.5 节，需替换 tenant-id | ⚡ |
| `AZURE_USER_INFO_URL` | 通常使用默认值 | ❌ |
| `FRONTEND_URL` | 前端访问地址 | ✅ |
| `SECRET_KEY` | 自行生成的随机密钥 | ✅ |
| `SESSION_COOKIE_SECURE` | HTTPS 时设 `true` | ✅ |

> ✅ = 必填 / ⚡ = 启用 Azure 登录时必填 / ❌ = 可选（有默认值）

### 3.2 开发环境（Vite Dev Server + Flask Dev Server）

开发环境前端在 `:3000`、后端在 `:5000`，Vite proxy 转发 `/api/*`。

```bash
SECRET_KEY=dev-secret-key

# GitHub
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
GITHUB_REDIRECT_URI=http://localhost:5000/api/auth/oauth/github/callback

# Azure China（开发环境可选）
# AZURE_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# AZURE_CLIENT_SECRET=your-azure-client-secret-value
# AZURE_REDIRECT_URI=http://localhost:5000/api/auth/oauth/azure/callback
# AZURE_AUTH_URL=https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/authorize
# AZURE_TOKEN_URL=https://login.partner.microsoftonline.cn/{tenant-id}/oauth2/v2.0/token

# 开发环境前后端分离，callback 回到 5000 后需要重定向回 3000
FRONTEND_URL=http://localhost:3000

CORS_ORIGINS=http://localhost:3000

# 开发环境 HTTP，不开 Secure
SESSION_COOKIE_SECURE=false
```

> 💡 **开发 vs 生产的关键区别：**
> - 开发环境 callback 直达后端 `:5000`，所以 `*_REDIRECT_URI` 指向 `localhost:5000`
> - 生产环境 callback 走 nginx 代理，`*_REDIRECT_URI` 指向公共域名
> - Azure 的 `AUTH_URL` / `TOKEN_URL` **不区分开发/生产**，始终指向 Azure 中国版 endpoint

---

## 4. Docker Compose 生产部署

```bash
# 1. 确认 .env 配置完成（参考上面 3.1）
cat .env | grep -E 'GITHUB_|AZURE_|FRONTEND_URL|SECRET_KEY|SESSION_COOKIE'

# 2. 启动服务
docker compose -f docker-compose.prod.yml up -d

# 3. 验证后端启动
curl https://slide.example.com/health
# => {"status":"ok","message":"Banana Slides API is running"}

# 4. 验证 GitHub OAuth 跳转
# 浏览器打开：https://slide.example.com/api/auth/oauth/github/login
# 应重定向到 GitHub 授权页面

# 5. 验证 Azure OAuth 跳转
# 浏览器打开：https://slide.example.com/api/auth/oauth/azure/login
# 应重定向到 Azure 中国版登录页面
```

### nginx 注意事项

内置的 `frontend/nginx.conf` 已经配置了 `/api` 反向代理，Docker Compose 中 nginx 监听 `:80`。

如果你在前面有一层外部 nginx/Caddy 做 HTTPS 终止，确保：

1. **传递 `Host` 和 `X-Forwarded-Proto` 头**（session cookie 的 `Secure` 标志依赖这些）
2. **传递 Cookie**（不要在外层 proxy 剥离 `Set-Cookie` / `Cookie` 头）

外层 nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name slide.example.com;

    ssl_certificate     /etc/ssl/slide.example.com.crt;
    ssl_certificate_key /etc/ssl/slide.example.com.key;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

---

## 5. 验证清单

| 检查项 | 命令 / 方法 |
|--------|-------------|
| 后端健康 | `curl https://slide.example.com/health` |
| GitHub OAuth 跳转 | 浏览器打开 `https://slide.example.com/api/auth/oauth/github/login` |
| Azure OAuth 跳转 | 浏览器打开 `https://slide.example.com/api/auth/oauth/azure/login` |
| Callback 回跳 | 授权后应回到 `https://slide.example.com/`（而非后端 JSON 页） |
| Session 生效 | 登录后 `GET /api/auth/me` 返回用户信息 |
| Cookie Secure | DevTools → Application → Cookies，确认 `session` cookie 有 `Secure; HttpOnly; SameSite=Lax` |
| Logout | `POST /api/auth/logout` 后 `/api/auth/me` 返回 401 |

---

## 6. 常见问题

### Q: OAuth callback 后停留在后端 JSON 页面？

A: `FRONTEND_URL` 未设置或设置错误。检查 `.env` 中 `FRONTEND_URL` 是否指向前端地址。

### Q: GitHub 报 "redirect_uri mismatch"？

A: GitHub OAuth App 的 **Authorization callback URL** 必须与 `.env` 中 `GITHUB_REDIRECT_URI` **完全匹配**（包括 `http/https`、端口、路径）。

### Q: Azure 登录跳转后显示 "AADSTS50011: reply URL does not match"？

A: Azure 门户中注册的 **重定向 URI** 必须与 `.env` 中 `AZURE_REDIRECT_URI` **完全匹配**。检查：
1. 协议是否一致（`http` vs `https`）
2. 域名和端口是否一致
3. 路径是否一致（`/api/auth/oauth/azure/callback`）

### Q: Azure 登录显示 "需要管理员审批"？

A: 管理员未授予 API 权限同意。联系租户管理员在 Azure 门户 → 应用注册 → API 权限页面点击 **代表组织授予管理员同意**。

### Q: Azure 登录报 "AADSTS7000215: Invalid client secret"？

A: 客户端密码已过期或值错误。Azure 密码有过期时间（最长 24 个月），需到门户重新生成并更新 `.env` 中的 `AZURE_CLIENT_SECRET`。

### Q: 登录成功但 `/api/auth/me` 返回 401？

可能原因：
1. **Cookie 跨域丢失** — 确认 `CORS_ORIGINS` 包含前端域名，且 `SESSION_COOKIE_SECURE=true`（HTTPS 环境）
2. **反向代理剥离 Cookie** — 确认外层 proxy 正确传递 `Cookie` / `Set-Cookie` 头
3. **SameSite 限制** — 默认 `Lax`，要求 callback redirect 是顶级导航（目前是 302，符合要求）

### Q: 如何注销所有用户 Session？

更换 `.env` 中的 `SECRET_KEY` 并重启后端即可。Flask 签名 session 依赖此密钥，密钥变更后所有旧 session 自动失效。

### Q: 可以只启用其中一个 Provider 吗？

可以。只配置你需要的 Provider 环境变量即可。未配置的 Provider（`CLIENT_ID` 为空）在 Login 页面上的按钮仍会显示，但点击后后端会返回错误。如需隐藏未配置的按钮，可修改 `frontend/src/pages/Login.tsx` 中的 `providers` 数组。
