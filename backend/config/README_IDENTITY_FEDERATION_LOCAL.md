# 本地验证 Identity Federation

本指南使用 `backend/config/identity_federation_providers.yaml` 中的 `local` Provider，配合本地
OAuth2/OIDC Mock 服务验证完整登录流程。Provider 是否参与运行只由
`IDENTITY_FEDERATION_PROVIDERS` 决定；Provider YAML 不包含独立激活开关。

## 1. 启动本地 Mock Provider

当前仓库不内置 Mock 服务。请启动一个监听 `http://localhost:9090` 的 OAuth2/OIDC 服务，并提供：

- `GET /authorize`：接收 `client_id`、`redirect_uri`、`response_type`、`scope`、`state`，重定向到
  `redirect_uri?code=<mock-code>&state=<state>`。
- `POST /token`：使用 code 换取 `access_token`。
- `GET /userinfo`：使用 Bearer token 返回 `sub`、`email`、`name`、`picture`。

## 2. 配置后端

在 `backend/.env` 或当前 shell 中设置：

```bash
export IDENTITY_FEDERATION_PROVIDERS=local
export IDENTITY_FEDERATION_CONFIG_PATH=
export IDENTITY_FEDERATION_LOGIN_MODE=chooser
export OAUTH_LOCAL_CLIENT_ID=local-client
export OAUTH_LOCAL_CLIENT_SECRET=local-secret
```

- `IDENTITY_FEDERATION_PROVIDERS` 是唯一的 Provider 激活来源，按逗号分隔且顺序即登录页展示顺序。
- `IDENTITY_FEDERATION_CONFIG_PATH` 留空时读取
  `backend/config/identity_federation_providers.yaml`；也可以指向另一份完整 Provider Catalog。
- `IDENTITY_FEDERATION_LOGIN_MODE=chooser` 展示登录选择页。
- `IDENTITY_FEDERATION_LOGIN_MODE=redirect` 仅适用于激活一个 Provider 的场景，并直接跳转到该 Provider。

`local` 使用 loopback HTTP endpoint，只允许 development 环境；staging 和 production 会拒绝启动。

## 3. 启动并验证

```bash
cd backend
uv run uvicorn app.joysafeter_api.main:app --reload --port 8000
```

前端登录页应显示“本地测试”。登录回调路径保持为：

```text
http://localhost:8000/api/v1/auth/oauth/local/callback
```

完成授权后，后端消费一次性登录尝试、解析 Principal、绑定联邦账号，并复用统一 AuthService
签发登录 token 与执行登录后初始化。

## 4. 添加自定义 OAuth2/OIDC Provider

在 `identity_federation_providers.yaml` 的 `providers` 下添加 Provider 定义：

```yaml
providers:
  my_sso:
    display_name: "企业 SSO"
    icon: "key"
    protocol: "oauth2"
    client_id: ${OAUTH_MY_SSO_CLIENT_ID}
    client_secret: ${OAUTH_MY_SSO_CLIENT_SECRET}
    issuer: "https://idp.example.com/realms/company"
    scope: "openid email profile"
    user_mapping:
      id: "sub"
      email: "email"
      name: "name"
      avatar: "picture"
```

然后将 Provider ID 加入激活列表：

```bash
export IDENTITY_FEDERATION_PROVIDERS=my_sso
```

不使用 OIDC Discovery 时，可在 Provider 定义中显式设置 `authorize_url`、`token_url` 和
`userinfo_url`。对应 IdP 的 Redirect URI 必须为：

```text
http(s)://<后端域名>/api/v1/auth/oauth/<provider-id>/callback
```

Provider Catalog、激活列表或 login mode 无效时，后端会在启动阶段失败，不会回退到其他配置来源。
