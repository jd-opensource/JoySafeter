# 用户身份联邦领域重构设计

## 状态

- 日期：2026-08-15
- 状态：架构方向已确认，书面规格待复核
- 范围：用户 OAuth/OIDC/JD SSO 登录、Provider 配置、登录状态、外部身份绑定、登录页跳转策略、API 启动校验
- 不属于本领域：Agent 运行身份、Agent Identity Provider、模型 Provider、凭据领域

## 1. 结论

系统建立独立的 **Identity Federation（用户身份联邦）** 领域，统一承载 GitHub、Google、OIDC、JD SSO 等外部用户身份登录。

```text
HTTP API
   |
   v
Identity Federation Application
   |             |                |
   v             v                v
ProviderRegistry LoginAttemptStore FederatedAccountGateway
   |             |                |
   v             v                v
Config Compiler  Redis Adapter    Auth/User Persistence
   |
   v
Protocol Adapter Registry
   |-- OAuth2/OIDC Adapter
   +-- JD SSO Adapter
```

核心裁决：

1. 不在现有 `OAuthConfigLoader` 上增加 `auto/true/false` 三态补丁。
2. Provider 定义与部署激活分离；是否启用由部署配置显式决定，不根据 Secret 是否存在进行猜测。
3. API 不识别 `oauth2`、`jd_sso` 等协议，不包含 JD 重试、Cookie 或 state 特判。
4. 协议适配器不创建用户、不访问数据库、不签发 JoySafeter JWT。
5. Application Coordinator 是登录流程、LoginAttempt 和回调编排的唯一所有者。
6. 激活 Provider 的配置在 API 启动时编译为不可变 Registry；错误必须阻止启动。
7. 不保留旧 `shared/oauth` 运行时兼容层；迁移完成后删除旧接口和旧配置名。

## 2. 当前根因

当前实现不是一个完整领域，而是若干职责临时拼接：

- `joysafeter_shared/oauth/config.py` 同时承担 YAML IO、环境变量展开、Provider 激活、模板合并、配置容错和运行时单例。
- loader 捕获 YAML、Provider 和字段错误后继续启动，导致部署表现为“SSO 按钮消失”，而不是明确的配置失败。
- `factory.py` 对未知协议回退到 OAuth2，可能把错误配置送入错误的安全协议。
- `oauth.py` 直接判断 `jd_sso`，拥有 JD retry、Cookie 前置行为和 Redis state 细节。
- `OAuthService` 同时拥有 URL 构造、Redis state、用户查找/创建和外部账号绑定。
- API 与 `OAuthService` 会重复写入同一个 OAuth state，生命周期没有单一所有者。
- 默认配置声明 JD `enabled: true`，环境示例却提供空凭据；同一仓库的默认契约自相矛盾。
- 登录页无条件选择 Provider 列表第一项自动跳转，而 `SSO_DEFAULT_PROVIDER` 只存在于 env 示例和文档、没有运行时代码读取；登录行为与部署配置脱节。
- `shared/oauth` 依赖 FastAPI Request、Redis、HTTP、settings 和领域模型，不具备 shared 模块应有的稳定复用边界。

根因是缺失“用户身份联邦”边界，而不是缺失一个更复杂的开关。

## 3. 设计原则

### 3.1 显式激活

部署必须声明启用哪些 Provider。Secret 的存在不能改变系统能力，防止不同环境因残留变量而产生不一致行为。

### 3.2 配置先编译、运行时只读取

YAML、模板、环境变量和协议校验只在 composition root 中处理。请求期间只使用不可变的 `ProviderRegistry`，不再 lazy load 或请求时 reload。

### 3.3 协议行为内聚

OAuth2 state、OIDC discovery、JD Cookie、verifyTicket 签名和 JD retry 都属于协议适配器。API 和用户领域不得判断协议字符串。

### 3.4 业务编排与传输分离

API 只完成输入转换和 HTTP 响应映射。登录尝试、回调消费、账号绑定、新用户策略和令牌签发由 application 层协调。

### 3.5 默认关闭、启用即严格

没有配置启用 Provider 时，密码登录等本地认证继续工作。任何被显式启用的 Provider 不完整或非法时，API 必须启动失败。

### 3.6 安全失败不可降级

- 未知协议不得回退。
- Redis/LoginAttemptStore 不可用时不得开始外部登录。
- state/correlation 缺失、过期、重复消费或 Provider 不匹配时必须拒绝回调。
- 上游响应、ticket、code、client secret 和 token 不进入日志或错误详情。

## 4. 领域边界

### 4.1 垂直领域模块

新增：

```text
backend/app/joysafeter_identity_federation/
  domain/
    models.py
    errors.py
    ports.py
    policies.py
  application/
    coordinator.py
    commands.py
    results.py
  infrastructure/
    config.py
    registry.py
    state_store.py
    protocols/
      base.py
      oauth2.py
      jd_sso.py
  bootstrap.py
```

选择垂直模块而不是继续向 `joysafeter_domain/services`、`joysafeter_shared` 和 API 分散文件，原因是：

- 一个工程师可以在单一目录理解完整身份联邦能力。
- 内部仍保持 domain/application/infrastructure 的依赖方向。
- 后续增加 SAML 或企业自定义协议时，只扩展本领域，不继续污染通用 shared 包。
- 明确区别于 `Agent Identity`，避免两种身份概念再次合并。

### 4.2 依赖规则

```text
domain <- application <- API
domain <- infrastructure
application <- bootstrap -> infrastructure
```

硬约束：

- `domain` 不得导入 FastAPI、SQLAlchemy、Redis、httpx、yaml、全局 settings 或 API DTO。
- `application` 只能依赖 domain ports 和稳定的 auth/user gateway 接口。
- `infrastructure` 实现 ports，可以依赖 Redis、httpx、yaml 和 settings。
- API 只依赖 application commands/results 和 bootstrap 暴露的 facade。
- API 不得导入 `infrastructure.protocols`。
- 协议适配器不得导入 AuthService、数据库 repository 或 JWT 模块。

这些规则通过静态 import-boundary 测试固化。

## 5. 核心领域模型

### 5.1 ProviderId

稳定的小写标识，例如 `github`、`google`、`jd`。只用于选择 Provider，不等同于协议。

### 5.2 ProtocolId

首批固定：

- `oauth2`
- `jd_sso`

Protocol ID 必须由已注册适配器提供。未知值是配置错误，不存在默认协议回退。

### 5.3 ProviderDefinition

Provider catalog 中经过结构解析、但尚未解析部署 Secret 的定义：

```text
ProviderDefinition
  id
  display_name
  icon
  protocol
  template
  raw protocol configuration
```

它不包含 `enabled`，也不负责决定当前部署是否激活。

### 5.4 ActiveProvider

配置编译完成后的不可变运行时对象：

```text
ActiveProvider
  id
  display_name
  icon
  protocol
  validated protocol configuration
```

只有 `ActiveProvider` 可以进入 `ProviderRegistry`。

### 5.5 LoginAttempt

一次外部登录的服务端状态：

```text
LoginAttempt
  id
  provider_id
  callback_url
  redirect_uri
  correlation_method
  retry_count
  created_at
  expires_at
```

要求：

- 默认 TTL 为 600 秒。
- 回调时原子消费，最多成功消费一次。
- Provider、redirect URI 和 correlation 必须匹配。
- callback URL 在创建时完成站内路径/允许来源校验，回调阶段不重新信任客户端输入。

### 5.6 FederatedPrincipal

协议适配器输出的统一外部身份：

```text
FederatedPrincipal
  provider_id
  subject
  email
  email_verified
  display_name
  avatar_url
  claims
```

`subject` 是 Provider 内稳定用户 ID。用户绑定键是 `(provider_id, subject)`，不得使用 email 作为外部账号主键。

`email_verified` 只有在上游协议提供可验证语义时才可为 `true`。JD 根据 username 构造的 `username@jd.com` 属于推导值，必须标记为未验证，不能用于自动绑定已有 JoySafeter 用户。

## 6. 配置契约

### 6.1 环境变量

采用：

```text
IDENTITY_FEDERATION_PROVIDERS=jd,github
IDENTITY_FEDERATION_CONFIG_PATH=/app/config/identity_federation_providers.yaml
IDENTITY_FEDERATION_LOGIN_MODE=chooser
```

规则：

- `IDENTITY_FEDERATION_PROVIDERS` 缺失或空值：不启用任何外部用户身份 Provider。
- 列表顺序决定前端默认展示顺序。
- 重复项、空项、未知 Provider 均为启动错误。
- 不引入 `auto`；Secret 是否存在不影响激活决策。
- `IDENTITY_FEDERATION_LOGIN_MODE` 只允许 `chooser` 或 `redirect`，默认 `chooser`。
- `redirect` 模式自动跳转到激活列表第一项；激活列表为空时是启动配置错误。
- 删除未生效的 `SSO_DEFAULT_PROVIDER`；前端不得维护第二份 Provider 选择配置。
- 删除旧 `OAUTH_CONFIG_PATH` 和 YAML `enabled`，不保留双读兼容。

### 6.2 Provider Catalog

默认文件重命名为：

```text
backend/config/identity_federation_providers.yaml
```

示例：

```yaml
version: 1

providers:
  github:
    display_name: GitHub
    icon: github
    protocol: oauth2
    template: github
    client_id: ${OAUTH_GITHUB_CLIENT_ID}
    client_secret: ${OAUTH_GITHUB_CLIENT_SECRET}

  jd:
    display_name: JD SSO
    icon: building
    protocol: jd_sso
    client_id: ${JD_CLIENT_ID}
    client_secret: ${JD_CLIENT_SECRET}
    authorize_url: ${JD_AUTHORIZE_URL}
    userinfo_url: ${JD_USERINFO_URL}
    scope: openid email
    user_mapping:
      id: userId
      email: email
      name: username
      avatar: ""

settings:
  default_redirect_url: /managed/quickstart
  allow_registration: true
  auto_link_by_email: true
```

JD `token_url` 不属于当前 verifyTicket 协议必需字段，最终协议 schema 不应为了复用 OAuth2 配置而强制或保留无效字段。

### 6.3 编译流程

启动时严格执行：

1. 读取文件；配置路径存在但文件不存在时失败。
2. YAML 解析并验证 `version/providers/settings` 结构，未知顶层字段失败。
3. 解析所有 Provider 的公共结构和 Protocol ID。
4. 读取 `IDENTITY_FEDERATION_PROVIDERS`，验证名称、重复和顺序。
5. 仅对激活 Provider 展开环境变量；未定义变量保留为空是禁止的。
6. 应用 Provider template。
7. 调用对应协议适配器的配置 schema 完成字段和 URL 校验。
8. 聚合全部错误并一次性抛出 `FederationConfigurationError`。
9. 成功后生成不可变 `ProviderRegistry`。

非激活 Provider 不要求部署 Secret，但其结构和 Protocol ID 仍必须合法，避免 catalog 中存在潜伏错误。

Loopback、私网和 link-local endpoint 默认全部拒绝。只有 `ENVIRONMENT=development`、Provider ID 严格等于 `local` 时，才允许 loopback HTTP endpoint 用于仓库文档中的本地 Mock OAuth 验证；staging、production 和其他 Provider 不存在该例外。

### 6.4 内部 JD 部署

公司内部环境必须显式配置：

```text
IDENTITY_FEDERATION_PROVIDERS=jd
IDENTITY_FEDERATION_LOGIN_MODE=redirect
JD_CLIENT_ID=...
JD_CLIENT_SECRET=...
JD_AUTHORIZE_URL=...
JD_USERINFO_URL=...
```

缺少任何 JD 必需值时启动失败。JD Dockerfile 保持有效；本设计不删除内部部署构建链。

## 7. 协议适配器

### 7.1 接口

协议适配器提供两个完整能力，而不是当前仅提供 `get_user_info()`：

```text
begin_login(provider, attempt, request_context) -> AuthorizationAction
complete_login(provider, attempt, callback_context) -> CompletionOutcome
```

`AuthorizationAction` 描述浏览器应访问的 URL 和需要写入的安全 correlation cookie。

`CompletionOutcome` 只有两类：

- `Authenticated(FederatedPrincipal)`
- `RestartAuthorization(reason)`

重试是否允许、最大次数和新的 LoginAttempt 由 application coordinator 决定；协议适配器只说明协议需要重新开始授权。

### 7.2 OAuth2/OIDC Adapter

负责：

- authorization URL 和 state 参数。
- code 换 token。
- userinfo 获取和 claims 映射。
- OIDC discovery 及受控缓存。
- endpoint SSRF/协议/host 校验。

不负责：

- Redis state。
- callback URL 业务校验。
- 用户创建、账号绑定或 JWT。

### 7.3 JD SSO Adapter

负责：

- JD authorize URL。
- `sso.jd.com` Cookie 读取。
- verifyTicket 签名和调用。
- JD 响应解析及字段映射。
- 缺少 JD 会话时返回 `RestartAuthorization`。

JD callback 若不能可靠回传 OAuth state，使用短期、签名、HttpOnly、Secure、SameSite=Lax correlation cookie 保存 LoginAttempt ID。回调必须同时验证服务端 LoginAttempt，不能只信任 Cookie 内容。

Cookie 使用现有应用安全主密钥派生的独立 HMAC-SHA256 signing key，并包含用途常量、attempt ID 和过期时间。签名比较必须使用 constant-time compare；完成、失败或 retry 后均清除旧 Cookie。

JD 特有字段和重试逻辑不得出现在 API、ProviderRegistry 或用户账号服务中。

## 8. Application Coordinator

`FederatedLoginCoordinator` 是外部登录用例的唯一入口。

### 8.1 开始登录

```text
API request
 -> coordinator.begin_login(provider_id, callback_url, request_context)
 -> registry.require(provider_id)
 -> validate callback_url
 -> create LoginAttempt
 -> adapter.begin_login(...)
 -> store LoginAttempt
 -> return authorization action
```

LoginAttempt 只写一次，不允许 API 或其他 service 二次覆盖。

### 8.2 完成登录

```text
API callback
 -> coordinator.complete_login(provider_id, callback_context)
 -> resolve and atomically consume LoginAttempt
 -> adapter.complete_login(...)
 -> optional bounded restart
 -> FederatedAccountGateway.resolve_or_create(principal, policy)
 -> AuthSessionGateway.issue_login_session(user)
 -> return redirect/cookie result
```

账号绑定、用户创建和登录令牌签发分别通过稳定 gateway 调用现有 auth 能力。Coordinator 不直接操作 SQLAlchemy session，也不复制 AuthService 内部逻辑。

### 8.3 注册和自动绑定策略

`allow_registration` 与 `auto_link_by_email` 是身份联邦业务策略，由 application/domain policy 执行，不由协议适配器执行。

- 已存在 `(provider_id, subject)`：登录已绑定用户。
- 未绑定且 email 对应现有用户：仅在 `auto_link_by_email=true`、`principal.email_verified=true`、现有用户处于 active 状态且 email 规范化后精确一致时绑定。
- 外部 email 未验证、缺失或由协议适配器推导时：禁止自动绑定。
- 无现有用户：仅在 `allow_registration=true` 时创建。
- 缺失稳定 subject：拒绝，不允许用 email 代替。
- 未验证 email 与已有用户发生唯一键冲突时：拒绝登录并要求管理员或用户完成显式绑定，不得退化为自动绑定。

## 9. LoginAttemptStore

定义 domain port，Redis 实现位于 infrastructure。

必要操作：

```text
create(attempt)
consume(attempt_id) -> LoginAttempt | None
replace_for_retry(consumed_attempt, replacement)
```

要求：

- `consume` 使用 Redis 原子 GETDEL 或等价 Lua 脚本。
- 并发回调只有一个可以成功。
- Redis 不可用时，开始登录返回稳定的依赖不可用错误，不降级为无 state 登录。
- Redis key 不包含 callback URL、code、ticket 或 Secret。
- retry 创建新 attempt，旧 attempt 保持已消费状态，防止重放。

## 10. API 边界

保留现有公共路由形态，避免无必要的前端协议变化：

- `GET /auth/oauth/providers`
- `GET /auth/oauth/{provider}`
- `GET /auth/oauth/{provider}/callback`

路由名称可以暂时保留 `oauth` 作为外部 HTTP 兼容路径，但内部类型和模块统一使用 Identity Federation。该路径兼容不允许演化成旧 Python API 的兼容层。

API 只负责：

- FastAPI 参数解析。
- 构造 request/callback context。
- 调用 coordinator。
- 写入 coordinator 返回的 Cookie。
- 将稳定 application error 映射为 HTTP 或前端 redirect error code。

`/providers` 响应同时返回已编译的 `login_mode`。前端仅在 `login_mode=redirect` 时跳转列表第一项；`chooser` 模式展示 Provider 按钮。前端不读取 `SSO_DEFAULT_PROVIDER`。

API 不再负责：

- 获取 config loader。
- 构造协议 authorization URL。
- 访问 Redis state。
- 判断 `jd_sso`。
- JD retry。
- 用户创建、绑定、commit/rollback。
- JWT 业务编排。

## 11. 错误模型

### 11.1 启动错误

统一 `FederationConfigurationError`，包含有序 issue 列表：

```text
provider
field
code
message
```

至少覆盖：

- 配置文件缺失或 YAML 非法。
- schema/version 非法。
- 激活 Provider 未定义。
- Protocol 未注册。
- 环境变量未解析。
- 必需字段缺失。
- endpoint URL 非法。
- Provider 列表重复或含空项。

### 11.2 运行时错误

稳定分类：

- Provider 不存在或未激活。
- LoginAttempt 缺失、过期、已消费或不匹配。
- 上游拒绝授权。
- 上游暂时不可用。
- 外部 Principal 非法。
- 注册或自动绑定策略拒绝。
- Auth session 签发失败。

日志记录稳定 code、provider、attempt ID 前缀和 operation，不记录 code、ticket、token、Secret、完整 claims 或上游敏感响应。

## 12. Composition Root 与生命周期

`joysafeter_identity_federation/bootstrap.py` 负责：

1. 注册内建 Protocol Adapter。
2. 编译 Provider Catalog。
3. 构造不可变 ProviderRegistry。
4. 构造 Redis LoginAttemptStore。
5. 绑定 FederatedAccountGateway 和 AuthSessionGateway。
6. 构造 FederatedLoginCoordinator。
7. 暴露只读 facade 给 API。

API startup 必须调用 bootstrap。配置编译错误直接传播并阻止启动；Redis 连接健康检查可以独立报告，但请求时仍必须 fail closed。

全局对象只能在 bootstrap 中创建，禁止模块 import 时读取环境变量或加载文件。

## 13. 删除与迁移

最终删除：

- `backend/app/joysafeter_shared/oauth/`
- `OAuthConfigLoader`
- `get_oauth_config()` / `reload_oauth_config()`
- `get_protocol_handler()` 的 fallback factory
- `OAuthService` 中 authorization/state/provider config 职责
- API 中所有 JD 协议判断和 Redis state 命令
- YAML `enabled`
- `OAUTH_CONFIG_PATH`
- `SSO_DEFAULT_PROVIDER`
- `backend/config/oauth_providers.yaml`

保留并迁移：

- Provider templates。
- endpoint 安全校验。
- OAuthAccount 持久化数据和现有账号绑定关系。
- 对外 HTTP 路径。
- 已确认有效的 JD verifyTicket 算法和字段映射。

不做旧新 loader 双读、协议 fallback、旧环境变量 alias 或运行时 feature compatibility。实施期间可以先并行建立新模块，但切换路由的同一批次必须删除旧运行路径。

## 14. 实施切片

### Batch 0：独立收口当前部署修复

- 将 JD/source Dockerfile build-context 契约加入已有 tracked 测试文件。
- 固化 `JOYSAFETER_ENABLED` 已删除。
- 验证并形成独立提交，避免与身份联邦重构混合。

### Batch 1：领域骨架与配置编译

- 建立 domain models、errors、ports。
- 建立严格 catalog schema、激活列表 parser 和 ProviderRegistry。
- 接入 API startup，但暂不切换请求路径。
- 配置错误开始 fail fast。

### Batch 2：协议适配器与状态所有权

- 实现完整 OAuth2/JD adapter contract。
- 实现原子 LoginAttemptStore。
- 将 JD retry 和 correlation 移入领域流程。
- 建立协议 contract tests 和安全测试。

### Batch 3：登录编排与账号 gateway

- 实现 FederatedLoginCoordinator。
- 从旧 OAuthService 提取账号解析/创建 gateway。
- 通过 AuthSessionGateway 复用现有用户初始化和 JWT 能力。
- 验证既有 OAuthAccount 数据无需迁移。

### Batch 4：API 切换与旧实现删除

- API 改为只调用 coordinator。
- 删除 API Redis/JD/config 分支。
- 删除 `shared/oauth` 和旧 OAuthService 职责。
- 重命名配置和环境变量，不保留兼容层。

### Batch 5：部署和系统验证

- 更新 env examples、Docker Compose、内部 JD 部署说明及配置挂载。
- 前端登录页改为服从后端 `login_mode`，删除无条件自动跳转和无效 `SSO_DEFAULT_PROVIDER` 文档。
- 验证 providers 为空时密码登录正常。
- 验证 JD 激活配置完整时启动并展示 JD。
- 验证 JD 激活配置不完整时启动失败。
- 验证 OAuth2、JD、并发回调、重放、Redis 故障和上游故障。

每个 Batch 必须独立通过测试和架构审查后提交，不允许把所有变化压成单个不可审查提交。

## 15. 测试与验收

### 15.1 架构测试

- domain 无框架/IO import。
- API 不导入协议 adapters、Redis 或 config compiler。
- protocols 不导入数据库、AuthService 或 JWT。
- 仓库中不存在旧 loader/factory 和 `protocol == "jd_sso"` API 判断。

### 15.2 配置测试

- 空激活列表生成空 Registry。
- 激活未知 Provider 失败。
- 重复 Provider 失败。
- 激活 Provider 缺 Secret 失败。
- 未激活 Provider 缺 Secret 不失败。
- 任意 Provider 使用未知 Protocol 失败。
- YAML/schema/URL 错误聚合并阻止启动。
- Provider 展示顺序与激活列表一致。
- `login_mode=redirect` 且 Provider 为空时启动失败。
- 非法 login mode 启动失败。
- development 下 `local` Provider 可使用 loopback Mock endpoint；staging/production 下同一配置启动失败。

### 15.3 状态安全测试

- LoginAttempt 只能消费一次。
- 并发消费只有一个成功。
- 过期、Provider 不匹配和 correlation 不匹配均拒绝。
- Redis 不可用时不生成无保护的登录流。
- JD retry 消费旧 attempt 并创建新 attempt。

### 15.4 协议测试

- OAuth2 authorization、token、userinfo 和错误映射。
- OIDC discovery endpoint 安全校验。
- JD ticket 签名向量、Cookie 缺失、verifyTicket 成功/失败和单次 retry。
- 未知 Protocol 永不回退 OAuth2。

### 15.5 应用与 API 测试

- 已绑定账号登录。
- 自动绑定策略开/关。
- 注册策略开/关。
- 稳定 subject 缺失时拒绝。
- 用户初始化与 JWT session 只执行一次。
- API 路由不暴露 Secret 或上游错误详情。
- `chooser` 模式不自动跳转，`redirect` 模式只跳转激活列表第一项。
- 现有前端 providers/authorize/callback 契约保持可用。

### 15.6 部署验收

- 通用部署未配置 `IDENTITY_FEDERATION_PROVIDERS` 时正常启动。
- 内部 JD 部署显式启用且完整配置时正常启动。
- 预发配置缺失时在启动阶段给出全部明确错误，而不是运行后隐藏 Provider。
- generic/JD Dockerfile 构建检查、backend targeted tests、完整 backend regression 和 Ruff 全部通过。

## 16. 非目标

- 本轮不设计 SAML。
- 不建设运行时动态安装协议插件。
- 不允许管理员通过数据库热更新 Provider Secret。
- 不修改现有本地密码登录协议。
- 不重构 Agent Identity Provider。
- 不修改 OAuthAccount 数据表，除非实施审计证明当前唯一约束无法表达 `(provider_id, subject)`。
- 不把模型 Provider、MCP OAuth 或 Agent 凭据纳入本领域。

## 17. 完成定义

只有同时满足以下条件才算完成：

1. Provider 激活是显式部署决策，不依赖 Secret 猜测。
2. 启用配置错误在 startup 阶段阻止服务运行。
3. API 中没有协议分支、Redis state 命令和用户创建编排。
4. JD 行为完整位于 JD adapter 与 coordinator 协议中。
5. LoginAttempt 具有原子、一次性消费语义。
6. 未知 Protocol 不存在 fallback。
7. 旧 `shared/oauth` 运行路径和配置兼容已删除。
8. 通用部署、内部 JD 部署和预发失败场景均有自动化验证。
9. 登录页行为由已校验的后端 federation 配置决定，不存在前后端重复 Provider 配置。
