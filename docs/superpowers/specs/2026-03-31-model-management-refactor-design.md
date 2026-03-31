# 模型管理功能重构设计

## 背景

当前模型管理系统存在职责混乱、分支逻辑过多、代码冗余等问题。本次重构目标是在不改变数据库架构的前提下，划清 service 职责边界，清理垃圾逻辑，统一 API 语义，前后端对齐。

## 核心规则

1. **内置 provider**：只能添加/清除认证信息，一个 provider 一个认证
2. **自定义 provider**：一步创建 provider + model + 认证，支持整体删除（级联）
3. **全局系统级**：workspace_id 和 user_id 是预留字段，当前忽略
4. **custom 模板**：is_template=true 的 provider 不在前端列表中显示

## 1. 后端 Service 层职责划分

### 1.1 ModelProviderService — provider 生命周期的唯一入口

**保留方法：**
- `sync_providers_from_factory()` — 同步内置 provider
- `get_all_providers()` — 查询所有 provider（过滤掉 is_template=True）
- `get_provider(provider_name)` — 查询单个 provider
- `update_provider_defaults(provider_name, default_parameters)` — 更新默认参数
- `delete_provider(provider_name)` — 删除自定义 provider（级联删除 credential + instance）
- `sync_all()` — 统一同步接口
- `_ensure_model_instances_for_provider(provider)` — 确保模型实例存在
- `_sync_models()` — 同步模型

**新增方法：**
- `add_custom_provider(credentials, model_name, display_name, model_parameters, validate)` — 一步创建自定义 provider + credential + model_instance。从 credential_service._add_one_custom_model 移入。

**从 credential_service 移入的内部方法：**
- `_create_derived_provider(template, name, display_name, template_name)` — 创建派生 provider DB 记录

**简化：**
- `get_all_providers()` 合并 factory_provider 存在/不存在两个分支的 dict 构建逻辑
- `get_provider()` 简化为两段式：DB 存在 / DB 不存在

### 1.2 ModelCredentialService — 只管认证 CRUD

**保留方法：**
- `upsert_credential(provider_name, credentials, validate)` — 为已有 provider 创建/更新认证（原 create_or_update_credential 简化版，删掉 custom 分支和派生逻辑）
- `validate_credential(credential_id)` — 重新验证
- `get_credential(credential_id, include_credentials)` — 获取详情
- `list_credentials()` — 列表
- `delete_credential(credential_id)` — 删除内置 provider 的认证记录。自定义 provider 的 credential 拒绝删除，返回 400
- `get_decrypted_credentials(provider_name, user_id)` — 按 provider_name 获取解密凭证

**保留的内部方法：**
- `_upsert_credential(provider_id, encrypted, is_valid, validation_error, user_id)` — upsert 逻辑
- `_validate_for_provider(provider, credentials, provider_id)` — 验证凭证

**删除的方法：**
- `_add_one_custom_model` → 移到 provider_service
- `_create_derived_provider` → 移到 provider_service
- `_ensure_model_instances` → 删除，provider_service 自己处理
- `_update_default_model_cache` → 移到 model_service
- `_update_default_model_cache_if_needed` → 移到 model_service
- `get_current_credentials` → 删除（是 get_decrypted_credentials 的透传）
- `_get_first_model_name_for_provider` → 移到 provider_service（自定义 provider 验证需要）

### 1.3 ModelService — 模型实例和运行时

**保留方法（全部保留，部分简化）：**
- `get_available_models(model_type, user_id)` — 获取可用模型列表
- `get_overview()` — 全局概览
- `update_model_instance(instance_id, model_parameters, is_default)` — 更新实例
- `create_model_instance_config(...)` — 创建实例配置
- `update_model_instance_default(...)` — 更新默认状态
- `get_model_instance(user_id, provider_name, model_name, use_default)` — 获取 LangChain 模型对象
- `get_runtime_model_by_name(model_name, user_id)` — 按名称获取运行时模型
- `list_model_instances()` — 列表
- `test_output(...)` — 测试输出
- `test_output_stream(...)` — 流式测试输出

**新增内部方法：**
- `_resolve_and_create_model(model_name, user_id)` — 统一 resolve provider → get credential → create model 逻辑，消除 test_output / test_output_stream / get_runtime_model_by_name / get_model_instance 四处重复

**从 credential_service 移入：**
- `_update_default_model_cache(provider_name, model_name, model_type, model_parameters)` — 更新默认模型缓存
- `_update_default_model_cache_if_needed(provider_name)` — 条件刷新缓存

**简化：**
- `_build_provider_credentials_context` 中 global vs user-scoped 优先级判断简化（当前全局系统设计下不需要）
- 所有调用 `credential_service._update_default_model_cache` 的地方改为调自己的方法
- 所有调用 `credential_service.get_current_credentials` 的地方改为调 `credential_service.get_decrypted_credentials`

## 2. 后端 API 层重构

### 2.1 Provider 端点 (`/v1/model-providers`)

| 方法 | 路径 | 说明 | 变化 |
|------|------|------|------|
| GET | `/` | 列表（过滤 is_template=True） | 不变 |
| GET | `/{provider_name}` | 详情 | 不变 |
| POST | `/custom` | **新增**：添加自定义 provider | 新增 |
| PATCH | `/{provider_name}/defaults` | 更新默认参数 | 不变 |
| POST | `/sync` | 同步 | 不变 |
| DELETE | `/{provider_name}` | 删除自定义 provider（级联） | 不变 |

**新增 Schema：**
```python
class CustomProviderCreate(BaseModel):
    model_name: str = Field(description="模型名称")
    credentials: Dict[str, Any] = Field(description="凭据字典（明文）")
    display_name: Optional[str] = Field(default=None, description="自定义显示名称")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="模型参数")
    validate: bool = Field(default=True, description="是否验证凭据")
```

### 2.2 Credential 端点 (`/v1/model-credentials`)

| 方法 | 路径 | 说明 | 变化 |
|------|------|------|------|
| POST | `/` | 创建/更新内置 provider 认证 | 简化 schema |
| GET | `/` | 列表 | 不变 |
| GET | `/{credential_id}` | 详情 | 不变 |
| POST | `/{credential_id}/validate` | 重新验证 | 不变 |
| DELETE | `/{credential_id}` | 删除内置 provider 认证 | 增加校验 |

**简化 Schema：**
```python
class CredentialCreate(BaseModel):
    provider_name: str = Field(description="供应商名称")
    credentials: Dict[str, Any] = Field(description="凭据字典（明文）")
    validate: bool = Field(default=True, alias="should_validate", description="是否验证凭据")
```

删除字段：`provider_display_name`、`model_name`、`model_parameters`

**DELETE 校验：** 如果 credential 关联的 provider 是自定义 provider（provider_type='custom' 且 is_template=False），返回 400 提示走 `DELETE /model-providers/{name}`。

### 2.3 Model 端点 (`/v1/models`)

不变。

## 3. 前端重构

### 3.1 types/models.ts

**新增：**
```typescript
export interface CreateCustomProviderRequest {
  model_name: string
  credentials: Record<string, any>
  display_name?: string
  model_parameters?: Record<string, unknown>
  validate?: boolean
}
```

**简化 CreateCredentialRequest：**
```typescript
export interface CreateCredentialRequest {
  provider_name: string
  credentials: Record<string, any>
  validate?: boolean
}
```

删除字段：`providerDisplayName`、`model_name`、`model_parameters`

### 3.2 hooks/queries/models.ts

**简化 useCreateCredential：**
- body 只发 `{ provider_name, credentials, validate }`
- onSuccess 不再需要 `if (request.model_name)` 分支

**新增 useCreateCustomProvider：**
```typescript
export function useCreateCustomProvider() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (request: CreateCustomProviderRequest) => {
      return await apiPost<ModelCredential>(`${MODEL_PROVIDERS_PATH}/custom`, request)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
      queryClient.invalidateQueries({ queryKey: [...modelKeys.all, 'available'] })
    },
  })
}
```

**useModelProvidersByConfig：**
- 删除 `templateProviders` 分类，后端已过滤 is_template=True

### 3.3 组件变更

**add-custom-model-dialog.tsx：**
- 改用 `useCreateCustomProvider` 替代 `useCreateCredential`
- props 中的 `provider: ModelProvider` 改为接收 credential_schema（因为 custom 模板不再出现在 providers 列表里）

**credential-dialog.tsx：**
- 增加"清除认证"按钮，调用 `useDeleteCredential`，只在已有 credential 时显示
- 清除后关闭 dialog

**provider-sidebar.tsx：**
- 不再有 `templateProviders` 分类
- 过滤掉 `is_template=true` 的 provider（后端已处理，前端做防御性过滤）

**detail-panel.tsx / provider-header.tsx：**
- 自定义 provider 的删除统一调 `useDeleteModelProvider`

**models-page.tsx：**
- `customProvider` 查找改为 `useModelProvider('custom')` 单独查询（因为 custom 模板不在列表里了）
- 将 credential_schema 传给 AddCustomModelDialog

## 4. 垃圾逻辑清理清单

### 后端删除项

| # | 文件 | 位置 | 说明 |
|---|------|------|------|
| 1 | credential_service.py | create_or_update_credential ~L136-143 | 删除 `if template and provider_display_name` 派生分支 |
| 2 | credential_service.py | _add_one_custom_model ~L176-237 | 整个方法移到 provider_service |
| 3 | credential_service.py | _create_derived_provider ~L43-57 | 移到 provider_service |
| 4 | credential_service.py | _ensure_model_instances ~L383-387 | 删除 |
| 5 | credential_service.py | _update_default_model_cache* ~L341-381 | 移到 model_service |
| 6 | credential_service.py | get_current_credentials ~L327-335 | 删除（透传） |
| 7 | credential_service.py | delete_credential 中自定义 provider 级联 ~L302-308 | 改为返回 400 |
| 8 | credential_service.py | _get_first_model_name_for_provider ~L38-41 | 移到 provider_service |
| 9 | model_service.py | 四处重复的 resolve 模式 | 提取 _resolve_and_create_model |
| 10 | model_service.py | 调用 credential_service._update_default_model_cache ~L254,303,347 | 改为调自己的方法 |
| 11 | provider_service.py | get_all_providers 两个分支 ~L120-157 | 合并 |
| 12 | provider_service.py | get_provider 三段式逻辑 ~L169-242 | 简化为两段 |
| 13 | model_credentials.py (API) | CredentialCreate schema | 删除多余字段 |

### 前端删除项

| # | 文件 | 说明 |
|---|------|------|
| 14 | types/models.ts | CreateCredentialRequest 删除 model_name, model_parameters, providerDisplayName |
| 15 | hooks/queries/models.ts | useCreateCredential 删除 model_name/model_parameters 分支 |
| 16 | hooks/queries/models.ts | useModelProvidersByConfig 删除 templateProviders |
| 17 | models-page.tsx | customProvider 查找方式改为单独查询 |

### 简化项

| # | 文件 | 说明 |
|---|------|------|
| 18 | model_service.py | _build_provider_credentials_context 简化 global vs user-scoped 优先级 |
| 19 | provider_service.py | get_provider 简化为两段式 |

## 5. 不变的部分

- 数据库架构（model_provider / model_credential / model_instance 三表关系）
- 加密/解密逻辑（encryption.py）
- Provider 运行时实现（core/model/providers/*.py）
- Factory 和 provider 发现机制
- Model usage 相关（model_usage_service / model_usage API）
- Playground 和 stats 前端组件
- Schema-driven 表单机制（schema-utils.ts）
- 启动同步流程（main.py）

## 6. 实施顺序

1. 后端 service 层重构（provider_service → credential_service → model_service）
2. 后端 API 层重构（model_providers.py → model_credentials.py）
3. 前端 types + hooks 重构
4. 前端组件重构
5. 端到端验证
