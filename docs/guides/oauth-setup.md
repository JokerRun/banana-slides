# OAuth 登录配置指南

本文档说明如何为 Banana Slides 配置 GitHub（和可选的 Azure China 21V）OAuth 登录。

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
    │──── click ──▶│── /api/auth/oauth/github/login ──▶ build state ──────│─▶ 302 github.com
    │              │                                        │              │
    │◀── github authorizes ──────────────────────────────────│              │
    │              │                                        │              │
    │──── callback▶│── /api/auth/oauth/github/callback ──▶ exchange code  │
    │              │                                   set session cookie   │
    │◀── 302 ─────│◀── redirect to FRONTEND_URL ◀──────────│              │
    │              │                                        │              │
    │──── app loads, GET /api/auth/me (cookie attached) ──▶│              │
    │◀── 200 { user } ◀──────────────────────────────────────│              │
                  └──────────────────────────────────────────────────────────┘
```

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

## 2. 环境变量配置

### 2.1 生产环境（Docker Compose 部署）

假设域名为 `https://slide.example.com`，编辑项目根目录 `.env`：

```bash
# ========== 必填：Flask Session 签名密钥 ==========
# 生产环境务必设置一个随机强密码，不要使用默认值
SECRET_KEY=your-random-secret-key-at-least-32-chars

# ========== 必填：OAuth - GitHub ==========
GITHUB_CLIENT_ID=Ov23liXXXXXXXXXXXXXX
GITHUB_CLIENT_SECRET=a5b7db983aXXXXXXXXXXXXXXXXXXXXXXXXXXXX
GITHUB_REDIRECT_URI=https://slide.example.com/api/auth/oauth/github/callback

# ========== 必填：前端地址（OAuth callback 后重定向目标）==========
# 生产环境前后端同域，填公共域名即可
FRONTEND_URL=https://slide.example.com

# ========== 必填：CORS ==========
# 生产环境前后端同域时可设为域名，或保持 * （不推荐）
CORS_ORIGINS=https://slide.example.com

# ========== 必填：Session Cookie 安全 ==========
# HTTPS 部署时必须设为 true
SESSION_COOKIE_SECURE=true

# ========== 可选：OAuth - Azure China 21V ==========
# AZURE_CLIENT_ID=your-azure-client-id
# AZURE_CLIENT_SECRET=your-azure-client-secret
# AZURE_REDIRECT_URI=https://slide.example.com/api/auth/oauth/azure/callback
```

### 2.2 开发环境（Vite Dev Server + Flask Dev Server）

开发环境前端在 `:3000`、后端在 `:5000`，Vite proxy 转发 `/api/*`。

```bash
SECRET_KEY=dev-secret-key

GITHUB_CLIENT_ID=Ov23liXXXXXXXXXXXXXX
GITHUB_CLIENT_SECRET=a5b7db983aXXXXXXXXXXXXXXXXXXXXXXXXXXXX
GITHUB_REDIRECT_URI=http://localhost:5000/api/auth/oauth/github/callback

# 开发环境前后端分离，callback 回到 5000 后需要重定向回 3000
FRONTEND_URL=http://localhost:3000

CORS_ORIGINS=http://localhost:3000

# 开发环境 HTTP，不开 Secure
SESSION_COOKIE_SECURE=false
```

> 💡 **开发 vs 生产的关键区别：**
> - 开发环境 callback 直达后端 `:5000`，所以 `GITHUB_REDIRECT_URI` 指向 `localhost:5000`
> - 生产环境 callback 走 nginx 代理，`GITHUB_REDIRECT_URI` 指向公共域名

---

## 3. Docker Compose 生产部署

```bash
# 1. 确认 .env 配置完成（参考上面 2.1）
cat .env | grep -E 'GITHUB_|FRONTEND_URL|SECRET_KEY|SESSION_COOKIE'

# 2. 启动服务
docker compose -f docker-compose.prod.yml up -d

# 3. 验证后端启动
curl https://slide.example.com/health
# => {"status":"ok","message":"Banana Slides API is running"}

# 4. 验证 OAuth 跳转
# 浏览器打开：https://slide.example.com/api/auth/oauth/github/login
# 应重定向到 GitHub 授权页面
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

## 4. 验证清单

| 检查项 | 命令 / 方法 |
|--------|-------------|
| 后端健康 | `curl https://slide.example.com/health` |
| OAuth 跳转 | 浏览器打开 `https://slide.example.com/api/auth/oauth/github/login` |
| Callback 回跳 | 授权后应回到 `https://slide.example.com/`（而非后端 JSON 页） |
| Session 生效 | 登录后 `GET /api/auth/me` 返回用户信息 |
| Cookie Secure | DevTools → Application → Cookies，确认 `session` cookie 有 `Secure; HttpOnly; SameSite=Lax` |
| Logout | `POST /api/auth/logout` 后 `/api/auth/me` 返回 401 |

---

## 5. 常见问题

### Q: OAuth callback 后停留在后端 JSON 页面？

A: `FRONTEND_URL` 未设置或设置错误。检查 `.env` 中 `FRONTEND_URL` 是否指向前端地址。

### Q: GitHub 报 "redirect_uri mismatch"？

A: GitHub OAuth App 的 **Authorization callback URL** 必须与 `.env` 中 `GITHUB_REDIRECT_URI` **完全匹配**（包括 `http/https`、端口、路径）。

### Q: 登录成功但 `/api/auth/me` 返回 401？

可能原因：
1. **Cookie 跨域丢失** — 确认 `CORS_ORIGINS` 包含前端域名，且 `SESSION_COOKIE_SECURE=true`（HTTPS 环境）
2. **反向代理剥离 Cookie** — 确认外层 proxy 正确传递 `Cookie` / `Set-Cookie` 头
3. **SameSite 限制** — 默认 `Lax`，要求 callback redirect 是顶级导航（目前是 302，符合要求）

### Q: 如何注销所有用户 Session？

更换 `.env` 中的 `SECRET_KEY` 并重启后端即可。Flask 签名 session 依赖此密钥，密钥变更后所有旧 session 自动失效。
