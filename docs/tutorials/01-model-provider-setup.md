# 教程 01：模型配置 —— 用 Secrets 管理供应商密钥

> **状态：** 已按 v2 真实代码核对（2026-07-03）。
> **适合人群**：初次配置 JoySafeter 模型，或需要接入私有 / 第三方 OpenAI 兼容端点的用户。

---

## 机制先行：v2 里“模型配置”长什么样？

v1 的三层对象（Provider / ModelInstance / ModelCredential）以及 `/api/v1/models`、
`/api/v1/model-credentials`、独立的“Models 设置页”**都已移除**。v2 把模型配置收敛成两件事：

1. **Secret（凭据）** —— 一条加密存储的供应商密钥记录，表 `joysafeter_secrets`，API `/api/v1/secrets`，
   UI 在 **资源 → 密钥** 页（`/managed/secrets`）。字段：
   - `name`：显示名
   - `provider` / `protocol`：供应商 / 协议标识（默认 `custom`）
   - `data`：键值对，放 `api_key` / `base_url` 等真正的连接信息（**AES-256-GCM 加密**存储）
   - `is_default`：是否为项目默认凭据
2. **Agent 的模型选择** —— 在 Agent 编辑器里选引擎（`claude` / `codex` / `native`）与模型；Agent 行上的
   `model`（JSONB）+ `secret_ref` 决定运行时用哪条 Secret。

**运行时如何生效**：任务被调度到沙箱时，orchestrator 解密对应 Secret，把里面的键（如
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_BASE_URL` 等）作为**容器环境变量**注入沙箱，
沙箱内的 CLI harness（Claude Code / Codex / `ccb`）读取这些环境变量直连模型。**密钥绝不经 gRPC 过线**，
只经容器 env 注入。

> 换句话说：v2 里“模型流量”由沙箱内的 CLI 引擎直接发起，平台 Python 侧不再有 ModelRouter / 供应商
> 适配器层。你配置的是“往沙箱注入哪些密钥环境变量”，而不是一个中心化的模型网关。

---

## 案例 A：配置一条 Anthropic（Claude）凭据

1. 左侧导航进入 **资源 → 密钥**（`/managed/secrets`）。
2. 新建一条 Secret：
   - `name`：`claude-prod`
   - `provider`：`anthropic`（`protocol` 可留 `custom`）
   - `data`：
     ```json
     { "ANTHROPIC_API_KEY": "sk-ant-xxxxxxxx" }
     ```
   - 勾选 **设为默认**（`is_default`），让未显式指定 Secret 的 Agent 复用它。
3. 保存。

对应 API：

```bash
curl -X POST http://localhost:8000/api/v1/secrets \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <platform-token>" \
  -d '{
    "name": "claude-prod",
    "provider": "anthropic",
    "protocol": "custom",
    "data": { "ANTHROPIC_API_KEY": "sk-ant-xxxxxxxx" },
    "is_default": true
  }'
```

> 列表接口返回的 `data` 是**脱敏**的（不回显明文密钥）。

---

## 案例 B：接入 OpenAI 兼容端点（DeepSeek / 本地 Ollama / LM Studio 等）

许多服务都提供 OpenAI 兼容 API，只需把 `base_url` 指向对应网关即可，无需专门的“供应商适配器”。

1. 在 **资源 → 密钥**（`/managed/secrets`）新建：
   - `name`：`local-ollama`
   - `provider`：`openai`（或 `custom`）
   - `data`：
     ```json
     {
       "OPENAI_API_KEY": "not-needed",
       "OPENAI_BASE_URL": "http://host.docker.internal:11434/v1"
     }
     ```
2. 保存后，在 Agent 编辑器里把该 Agent 的引擎设为对应 CLI 引擎、模型名填成端点支持的模型（如
   `llama3:8b` / `deepseek-chat`），并把该 Agent 的 Secret 指向这条 `local-ollama`。

> **踩坑提示**
> - `base_url` 是否要带 `/v1` 取决于你接入的服务，平台不会自动补全。
> - 沙箱容器默认收紧网络（`NetworkMode=none` + Envoy 出口白名单）。要让沙箱能访问你的本地 / 内网端点，
>   该域名必须在 Envoy 出口白名单内，且地址要从**沙箱容器**（而非你的浏览器）可达（本机服务通常用
>   `host.docker.internal`）。
> - 具体环境变量名（`OPENAI_API_KEY` vs `ANTHROPIC_API_KEY` 等）取决于沙箱内 CLI 引擎读取哪个变量——
>   与你选择的引擎（`claude` / `codex` / `native`）匹配即可。

---

## 案例 C：企业 SSO 登录

若组织使用统一身份认证，JoySafeter 的 SSO 是可插拔的（`joysafeter_shared/oauth/`）：

| 方式 | 说明 |
|------|------|
| 标准 OAuth2 / OIDC | GitHub / Google 等模板，在 `backend/config` 的 OAuth 配置中填入 Client ID/Secret 启用 |
| JD SSO | 京东内部单点登录（非标准 OAuth2，`jd_sso` 协议处理器） |

前端 `/signin` 支持 SSO 自动跳转（`GET /api/v1/auth/oauth/providers` → 取首个 provider →
授权地址）。SSO 登录后自动创建用户并关联到默认组织 / 项目，凭据与权限体系与手动注册用户一致。

---

## 常见问题

**Q：我建了 Secret，运行时却没用上？**
默认凭据由 `is_default` 决定；若某个 Agent 显式绑定了别的 Secret（`secret_ref`），则以 Agent 上的为准。
确认该 Agent 指向的 Secret 与你刚配置的是同一条。

**Q：验证密钥有效性的接口在哪？**
v2 没有集中的 model-credentials 校验端点。最直接的验证方式是：在一个绑定该 Secret 的 Agent 上开一个
Session 发一条消息，看沙箱内引擎是否成功调用模型（失败会在会话事件流里以 `error` / `session.status_*`
体现）。

**Q：密钥安全吗？**
`data` 以 AES-256-GCM 加密落库，仅在任务调度时解密并作为容器环境变量注入目标沙箱，不经 gRPC 传输、
不写入事件流。

---

## 下一步

- [教程 02](./02-mcp-service-setup.md)：给 Agent 接入 MCP 工具（凭据放 Vaults）
- [教程 04](./04-agent-build-and-run.md)：在 Agent 编辑器里选引擎 / 模型，并在 Session 中运行
