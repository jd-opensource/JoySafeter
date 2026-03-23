# 教程 01：模型配置 —— 使用内置供应商与自定义供应商

> **适合人群**：初次配置 JoySafeter 模型，或希望接入私有/第三方 API 端点的用户。

---

## 场景说明

本教程通过两个实际案例帮助你掌握模型配置：

| 案例 | 目标 |
|------|------|
| **案例 A** | 使用内置 OpenAI 供应商，配置 GPT-4o 作为默认模型 |
| **案例 B** | 添加自定义 OpenAI 兼容供应商，接入本地部署的 Ollama / DeepSeek 等服务 |

---

## 机制先行：JoySafeter 的“模型配置”到底由哪几层组成？

很多“我明明填了 Key 但运行时没用上”的问题，本质不是 UI 操作错误，而是没理解 JoySafeter 把“模型配置”拆成了三层对象（职责不同、存储位置不同、故障表现也不同）：

### 1）Provider（供应商 / 实现模板）

- **作用**：决定“用哪个实现”创建 LangChain 模型实例（OpenAI / OpenAI-Compatible / Anthropic ...）
- **特点**：
  - **内置 Provider** 通常来自代码工厂（不一定落库）
  - **自定义 Provider** 会落库，并通过 `template_name` 指向某个内置 Provider（复用实现）

> 代码入口：`backend/app/core/model/factory.py`（provider 工厂与 create_model_instance）

### 2）Model Instance（模型实例配置）

- **作用**：决定“用哪个模型名 + 哪些参数（temperature/max_tokens…）”，以及**是否默认**
- **你在 UI 里“选模型/设默认”改的是这一层**（而不是凭据）
- **关键点**：运行时会读取 `resolved_provider_name` 来确定最终 provider

> 代码入口：`backend/app/models/model_instance.py`（`resolved_provider_name` 等解析逻辑）

### 3）Model Credential（凭据）

- **作用**：保存访问 Provider 所需的 `api_key` / `api_base` 等（加密存储），并可标记 `is_valid`
- **你在 UI 里“Configure/Validate/Save”主要改的是这一层**
- **关键点**：JoySafeter 会按“模板凭据 vs 派生凭据”的策略选择最合适的一条有效凭据

> API：`backend/app/api/v1/model_credentials.py`
> 选择与校验：`backend/app/services/model_credential_service.py`

---

## 运行时解析链路：系统到底怎么选到“最终用的模型”？

当你在 Copilot/Chat 里触发执行时，大体会走下面的链路（理解这段，你就知道应该查哪一层）：

1. **确定 Model Instance**
   - 显式指定 `provider_name + model_name` → 找对应实例
   - 否则使用默认实例（`is_default=true`）
2. **从实例得到最终 Provider**：`instance.resolved_provider_name`
3. **取该 Provider 的有效凭据**：`ModelCredentialService.get_current_credentials(provider_name, ...)`
4. **创建运行时模型**：`create_model_instance(provider_name, model_name, ..., credentials, model_parameters)`

典型错误提示与含义：

- `未找到模型 {provider}/{model} 的有效凭据`：**实例解析出来的 provider 对应的 credential 为空或无效**
- “Validate 通过但对话仍失败”：多数是 **Instance 指向的 provider/model 与你刚配置的 credential 不一致**

---

## 深度踩坑清单（先看这 5 条，少走弯路）

1. **“配置了凭据 ≠ 配置了默认模型”**
   默认模型由 **Model Instance** 决定，不是 Credential。

2. **模板 provider 与派生 provider 容易混用**
   - 模板：通常 `provider_id = NULL` 且 `provider_name=<模板名>`
   - 派生：`provider_id=<uuid>`，运行时 `resolved_provider_name` 是派生 provider 的 `name`
   你的 Instance 必须指向你期望的那一个，否则会“看起来配置对了但实际取错凭据”。

3. **`api_base` 是否要带 `/v1` 取决于你接入的服务**
   JoySafeter 不会自动补全路径；Ollama 常见是 `http://localhost:11434/v1`。

4. **文档/示例里的 provider_name 需要与你实际系统一致**
   后端接口 `provider_name` 字段含义是“供应商名称或模板名称”（见 `model_credentials.py` 的 Field 描述）。
   如果你看到 `openai_api_compatible` / `openaiapicompatible` 这类差异，照抄前先以系统返回的 provider 列表为准。

5. **把 `model_name` 放进 credentials 容易造成语义混淆**
   `model_name` 本质属于 Instance 层；credentials 只负责“怎么连”（key/base）。
  （某些兼容实现会容忍，但不建议当成规范写法。）

---

## API 认证：使用 Platform API Token

> **重要**：在多租户环境下，所有 REST API 调用都需要携带认证 Token。

JoySafeter 支持两种认证方式：

1. **Session Cookie**（通过浏览器登录后自动携带）
2. **Platform API Token**（适用于脚本、CI/CD、自动化调用）

**获取 Token**：进入 **Settings → API Tokens → Create Token**，设置名称和有效期后生成。

**在 curl 中使用**：
```bash
# 所有 API 请求都应携带 Authorization 头
curl http://localhost:8000/api/v1/models \
  -H "Authorization: Bearer <your-platform-token>"
```

> 本教程后续的 curl 示例省略了 `-H "Authorization: Bearer ..."` 以保持简洁，但在生产环境中务必携带。

---

## 企业 SSO 登录

如果你的组织使用统一身份认证，JoySafeter 支持多种 SSO 方式：

| 方式 | 说明 |
|------|------|
| **GitHub / Google / Microsoft** | 内置模板，在 `backend/config/oauth_providers.yaml` 中填入 Client ID/Secret 即可启用 |
| **OIDC 通用** | 支持 Keycloak、Authentik、GitLab 等标准 OIDC Provider |
| **JD SSO** | 京东内部单点登录（非标准 OAuth2） |

配置详见 `backend/config/README_OAUTH_LOCAL.md`。

SSO 登录后，系统自动创建用户并关联到对应的组织/工作区，模型凭据和权限体系与手动注册用户完全一致。

---

## 案例 A：配置内置 OpenAI 供应商

### 步骤 1：进入模型设置页面

1. 点击顶部导航 **Settings（设置）**
2. 选择左侧 **Models（模型）**
3. 在供应商列表中找到 **OpenAI**

### 步骤 2：配置 API 凭据

点击 OpenAI 旁边的 **Configure（配置）** 按钮，填写以下信息：

```
API Key：sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Base URL：https://api.openai.com/v1  （默认，不填也可）
```

点击 **Validate（验证）** 确认凭据有效后，点击 **Save（保存）**。

### 步骤 3：为 Agent 选择 GPT-4o

1. 进入任意 Agent 的 **Builder（构建器）**
2. 选中 Agent 节点，在右侧属性面板中找到 **Model（模型）**
3. 从下拉列表中选择 `gpt-4o`

### 步骤 4：测试模型输出（可选）

在设置页面，对应模型行有 **Test Output（测试输出）** 按钮，可快速发送一条消息验证模型是否正常响应。

---

## 案例 B：添加自定义 OpenAI 兼容供应商

许多私有部署服务（Ollama、LM Studio、DeepSeek、阿里百炼等）都支持 OpenAI 兼容 API。

### 步骤 1：了解自定义凭据 Schema

JoySafeter 的内置 `OpenaiApiCompatible` 供应商通过以下字段接受任意 OpenAI 兼容端点：

| 字段 | 说明 | 示例 |
|------|------|------|
| `api_key` | API 密钥（无密钥时填 `not-needed`） | `sk-xxxxxxxx` |
| `api_base` | API Base URL | `http://localhost:11434/v1` |
| `model_name` | 模型名称 | `llama3:8b` |

### 步骤 2：通过 UI 添加自定义供应商凭据

1. 进入 **Settings → Models**
2. 点击 **+ Add Custom Provider（添加自定义供应商）**
3. 选择类型为 **OpenAI Compatible**
4. 填写配置：

```
名称：My Ollama         （自定义显示名称）
API Key：not-needed
API Base：http://localhost:11434/v1
Model Name：llama3:8b
```

5. 点击 **Validate** → **Save**

### 步骤 3：通过 API 添加（高级）

也可以直接调用 REST API（以当前后端实现为准：`/api/v1/model-credentials`，字段名见 `backend/app/api/v1/model_credentials.py`）。

#### 方式 1：只创建/更新“凭据”（不负责创建模型实例）

适用于：你已经有对应的 Model Instance，只是想更新 key/base。

```bash
# 创建/更新凭据（模板或已存在的 provider）
curl -X POST http://localhost:8000/api/v1/model-credentials \
  -H "Content-Type: application/json" \
  -d '{
    "provider_name": "openaiapicompatible",
    "credentials": {
      "api_key": "not-needed",
      "api_base": "http://localhost:11434/v1"
    },
    "validate": true
  }'
```

#### 方式 2：一步到位“添加一个自定义模型”（会创建 provider + credential + instance）

适用于：你就是要新增一个本地模型（最不容易遗漏 instance/default）。

```bash
curl -X POST http://localhost:8000/api/v1/model-credentials \
  -H "Content-Type: application/json" \
  -d '{
    "provider_name": "custom",
    "providerDisplayName": "My Ollama",
    "credentials": {
      "api_key": "not-needed",
      "api_base": "http://localhost:11434/v1"
    },
    "model_name": "llama3:8b",
    "model_parameters": {
      "temperature": 0.7,
      "max_tokens": 4096
    },
    "validate": true
  }'
```

> 说明：当前后端支持 `provider_name=custom` 且携带 `model_name` 作为“一步添加自定义模型”的语义入口。

### 步骤 4：创建模型实例配置

如果你走的是“方式 1（只创建凭据）”，仍需要创建模型实例（Instance 层）：

```bash
# 创建模型实例
curl -X POST http://localhost:8000/api/v1/models/instances \
  -H "Content-Type: application/json" \
  -d '{
    "provider_name": "openaiapicompatible",
    "model_name": "llama3:8b",
    "model_parameters": {
      "temperature": 0.7,
      "max_tokens": 4096
    },
    "is_default": false
  }'
```

如果你走的是“方式 2（provider_name=custom + model_name）”，则这一步通常已经由后端自动完成。

### 步骤 5：验证配置（建议按“实例/凭据”分别验证）

```bash
# 1) 查看所有模型实例（确认 provider_name/model_name/is_default 是否符合预期）
curl http://localhost:8000/api/v1/models

# 2) 查看凭据列表（确认 is_valid=true，且 provider_name 指向正确）
curl http://localhost:8000/api/v1/model-credentials
```

测试模型输出（若你系统提供该接口）：

```bash
curl -X POST http://localhost:8000/api/v1/models/test-output \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "llama3:8b",
    "provider_name": "openaiapicompatible",
    "message": "你好，请介绍一下你自己"
  }'
```

---

## 常见问题

### Q：凭据验证失败怎么办？

- 检查 `api_base` 末尾是否有 `/v1`（如 `http://localhost:11434/v1`）
- 确认服务已经启动（`ollama serve` / `lm-studio start`）
- 检查 `api_key` 是否正确（无需认证的服务填 `not-needed`）

### Q：内置供应商和自定义供应商的区别？

| | 内置供应商 | 自定义供应商 |
|---|---|---|
| 配置方式 | UI 直接配置 | 选择 OpenAI Compatible 类型 |
| 支持的模型 | 固定列表 | 任意 OpenAI 兼容模型 |
| 适用场景 | OpenAI、Anthropic 等主流 | 本地部署、第三方兼容 API |

### Q：如何更新或删除凭据？

```bash
# 删除凭据
curl -X DELETE http://localhost:8000/api/v1/model-credentials/{credential_id}

# 验证现有凭据
curl -X POST http://localhost:8000/api/v1/model-credentials/{credential_id}/validate
```

---

## 下一步

- 了解如何在 Agent Builder 中选择并使用配置好的模型
- 参考教程 04：构建各类 Graph，将模型集成到工作流中
