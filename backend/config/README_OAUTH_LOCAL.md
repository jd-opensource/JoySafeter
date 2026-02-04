# 本地验证 OAuth 自定义提供商

在不依赖 GitHub/Google 等真实 OAuth 服务的情况下，用本地 Mock 服务验证 OAuth 登录流程。

## 方式一：使用内置 Mock 服务（推荐）

### 1. 启动 Mock OAuth 服务

```bash
cd backend
python scripts/mock_oauth_server.py
```

默认监听 `http://localhost:9090`，提供：

- `GET /authorize`：模拟授权页，直接重定向到后端的 callback 并带上 `code`、`state`
- `POST /token`：用 code 换 access_token
- `GET /userinfo`：用 Bearer token 返回 Mock 用户信息

### 2. 配置环境变量

在 `backend/.env` 或当前 shell 中设置：

```bash
export OAUTH_LOCAL_CLIENT_ID=local-client
export OAUTH_LOCAL_CLIENT_SECRET=local-secret
```

### 3. 启用「本地测试」提供商

编辑 `backend/config/oauth_providers.yaml`，将 `local` 的 `enabled` 改为 `true`：

```yaml
local:
  enabled: true   # 改为 true
  display_name: "本地测试"
  # ...
```

### 4. 启动后端并验证

- 启动后端（如 `uvicorn`，默认端口 8000）
- 前端登录页应出现「本地测试」按钮
- 点击后跳转到 Mock 授权页，再被重定向回后端 callback，完成登录

**注意**：后端回调 URL 由 `request.base_url` 自动生成，例如：

`http://localhost:8000/api/v1/auth/oauth/local/callback`

若后端端口或域名不同，无需在 Mock 中配置，后端会使用当前请求的 host。

---

## 方式二：自定义任意 OAuth/OIDC 提供商

在 `oauth_providers.yaml` 的 `providers` 下新增一段，无需改代码。

### 使用 OIDC Discovery（推荐，适用于 Keycloak、Authentik 等）

```yaml
my_sso:
  enabled: true
  display_name: "企业 SSO"
  icon: "key"
  client_id: ${OAUTH_MY_SSO_CLIENT_ID}
  client_secret: ${OAUTH_MY_SSO_CLIENT_SECRET}
  issuer: "https://your-keycloak.example.com/realms/myrealm"
  scope: "openid email profile"
  user_mapping:
    id: "sub"
    email: "email"
    name: "name"
    avatar: "picture"
```

系统会请求 `{issuer}/.well-known/openid-configuration` 自动获取 `authorize_url`、`token_url`、`userinfo_url`。

### 手动指定 URL（适用于不支持 Discovery 的服务）

```yaml
my_provider:
  enabled: true
  display_name: "自定义"
  icon: "key"
  client_id: ${OAUTH_MY_CLIENT_ID}
  client_secret: ${OAUTH_MY_CLIENT_SECRET}
  authorize_url: "https://your-idp.com/oauth/authorize"
  token_url: "https://your-idp.com/oauth/token"
  userinfo_url: "https://your-idp.com/oauth/userinfo"
  scope: "openid email profile"
  user_mapping:
    id: "sub"      # 用户唯一 ID 在 userinfo 中的字段名
    email: "email"
    name: "name"
    avatar: "picture"
```

在对应 IdP 中配置的 **回调 URL（Redirect URI）** 必须为：

`http(s)://<你的后端域名>:<端口>/api/v1/auth/oauth/<provider 名称>/callback`

例如：`http://localhost:8000/api/v1/auth/oauth/my_provider/callback`。

更多示例见 `oauth_providers.example.yaml`。
