# Model Service 文档

## 概述

`backend/app/services` 目录下的模型相关 Service 提供了业务逻辑层，封装了模型管理的核心业务逻辑，协调 Repository 层和 Core 层的交互。

## 相关 Service 文件

- `model_service.py` - 模型服务
- `model_provider_service.py` - 模型供应商服务
- `model_credential_service.py` - 模型凭据服务

## Service 详解

### 1. ModelService (model_service.py)

模型服务，提供模型实例的管理和调用功能。

#### 主要方法

##### `get_available_models(model_type: ModelType, user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]`

获取可用模型列表（所有用户和工作空间可见）。

**功能**:
- 从数据库获取所有模型实例
- 检查供应商是否支持指定模型类型
- 检查是否有有效的凭据
- 返回可用模型列表

**参数**:
- `model_type`: 模型类型枚举
- `user_id`: 用户ID（已废弃，保留用于向后兼容）
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 模型列表，每个包含：
- `provider_name`: 供应商名称
- `provider_display_name`: 供应商显示名称
- `name`: 模型名称
- `display_name`: 显示名称
- `description`: 描述
- `is_available`: 是否可用（是否有有效凭据）

**使用示例**:
```python
service = ModelService(db)
models = await service.get_available_models(
    model_type=ModelType.CHAT,
    workspace_id=workspace_id
)
```

##### `create_model_instance_config(...) -> Dict[str, Any]`

创建模型实例配置。

**功能**:
- 验证供应商是否存在
- 如果设置为默认，取消其他默认模型
- 创建模型实例配置

**参数**:
- `user_id`: 用户ID
- `provider_name`: 供应商名称
- `model_name`: 模型名称
- `model_type`: 模型类型
- `model_parameters`: 模型参数（可选）
- `workspace_id`: 工作空间ID（可选）
- `is_default`: 是否为默认模型

**返回**: 创建的模型实例配置

**使用示例**:
```python
service = ModelService(db)
instance = await service.create_model_instance_config(
    user_id="user123",
    provider_name="openaiapicompatible",
    model_name="gpt-4",
    model_type=ModelType.CHAT,
    model_parameters={"temperature": 0.7},
    is_default=True
)
```

##### `get_model_instance(...) -> Any`

获取模型实例（LangChain模型对象）。

**功能**:
- 如果未指定，使用默认模型
- 获取模型实例配置
- 获取解密后的凭据
- 创建并返回 LangChain 模型实例

**参数**:
- `user_id`: 用户ID
- `provider_name`: 供应商名称（可选）
- `model_name`: 模型名称（可选）
- `workspace_id`: 工作空间ID（可选）
- `use_default`: 如果未指定，是否使用默认模型

**返回**: LangChain 模型实例

**使用示例**:
```python
service = ModelService(db)
model = await service.get_model_instance(
    user_id="user123",
    provider_name="openaiapicompatible",
    model_name="gpt-4"
)

# 使用模型
response = await model.ainvoke("Hello")
```

##### `list_model_instances(user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]`

获取所有模型实例配置（所有用户和工作空间可见）。

**返回**: 模型实例配置列表

##### `test_output(user_id: str, model_name: str, input_text: str, workspace_id: Optional[uuid.UUID] = None) -> str`

测试模型输出。

**功能**:
- 获取模型实例配置
- 获取解密后的凭据
- 创建模型实例
- 调用模型进行测试
- 返回模型输出内容

**使用示例**:
```python
service = ModelService(db)
output = await service.test_output(
    user_id="user123",
    model_name="gpt-4",
    input_text="你好，请介绍一下你自己"
)
```

### 2. ModelProviderService (model_provider_service.py)

模型供应商服务，提供供应商管理和同步功能。

#### 主要方法

##### `sync_providers_from_factory() -> List[Dict[str, Any]]`

从工厂同步供应商到数据库。

**功能**:
- 从工厂获取所有供应商信息
- 检查数据库中是否已存在
- 如果存在则更新，否则创建
- 返回同步的供应商列表

**使用示例**:
```python
service = ModelProviderService(db)
synced_providers = await service.sync_providers_from_factory()
```

##### `get_all_providers() -> List[Dict[str, Any]]`

获取所有供应商信息（从工厂获取，包含数据库中的状态）。

**功能**:
- 从工厂获取所有供应商
- 从数据库获取已注册的供应商状态
- 合并信息返回

**返回**: 供应商信息列表，包含：
- `provider_name`: 供应商名称
- `display_name`: 显示名称
- `supported_model_types`: 支持的模型类型列表
- `credential_schema`: 凭据表单规则
- `config_schemas`: 配置规则（按模型类型）
- `is_enabled`: 是否启用
- `id`: 数据库ID（如果已注册）
- `icon`: 图标URL（如果已注册）
- `description`: 描述（如果已注册）

##### `get_provider(provider_name: str) -> Dict[str, Any] | None`

获取单个供应商信息。

**返回**: 供应商信息，如果不存在则返回 `None`

##### `sync_all() -> Dict[str, Any]`

统一同步接口：同步供应商、模型和认证信息到数据库。

**功能**:
1. 同步供应商信息（从工厂同步）
2. 同步模型信息（从工厂同步到 model_instance 表，全局记录）
3. 同步认证信息（从 .env 读取并同步到 model_credential 表，全局记录）

**返回**: 同步结果，包含：
- `providers`: 同步的供应商数量
- `models`: 同步的模型数量
- `credentials`: 同步的认证信息数量
- `errors`: 错误列表

**使用示例**:
```python
service = ModelProviderService(db)
result = await service.sync_all()
print(f"同步完成：供应商 {result['providers']} 个，模型 {result['models']} 个")
```

##### `_sync_models() -> int`

同步模型到 model_instance 表（全局记录，user_id 和 workspace_id 为 NULL）。

**内部方法**，由 `sync_all()` 调用。

##### `_sync_credentials() -> int`

从 .env 读取认证信息并同步到 model_credential 表（全局记录）。

**内部方法**，由 `sync_all()` 调用。

### 3. ModelCredentialService (model_credential_service.py)

模型凭据服务，提供凭据的创建、验证和管理功能。

#### 主要方法

##### `create_or_update_credential(...) -> Dict[str, Any]`

创建或更新凭据。

**功能**:
- 验证供应商是否存在
- 验证凭据（如果 `validate=True`）
- 加密凭据
- 检查是否已存在，存在则更新，否则创建

**参数**:
- `user_id`: 用户ID
- `provider_name`: 供应商名称
- `credentials`: 凭据字典（明文）
- `workspace_id`: 工作空间ID（可选）
- `validate`: 是否验证凭据

**返回**: 创建的凭据信息（不包含解密后的凭据）

**使用示例**:
```python
service = ModelCredentialService(db)
credential = await service.create_or_update_credential(
    user_id="user123",
    provider_name="openaiapicompatible",
    credentials={"api_key": "sk-..."},
    validate=True
)
```

##### `validate_credential(credential_id: uuid.UUID) -> Dict[str, Any]`

验证凭据。

**功能**:
- 获取凭据
- 解密凭据
- 验证凭据有效性
- 更新验证状态

**返回**: 验证结果，包含：
- `is_valid`: 是否有效
- `error`: 错误信息（如果有）
- `last_validated_at`: 最后验证时间

##### `get_credential(credential_id: uuid.UUID, include_credentials: bool = False) -> Dict[str, Any]`

获取凭据信息。

**参数**:
- `credential_id`: 凭据ID
- `include_credentials`: 是否包含解密后的凭据（仅用于内部使用）

**返回**: 凭据信息

##### `list_credentials(user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> List[Dict[str, Any]]`

获取所有凭据（所有用户和工作空间可见）。

**返回**: 凭据列表

##### `delete_credential(credential_id: uuid.UUID) -> None`

删除凭据。

##### `get_decrypted_credentials(provider_name: str, user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> Optional[Dict[str, Any]]`

获取解密后的凭据（所有用户和工作空间可见）。

**功能**:
- 优先查找全局凭据（user_id 为 NULL）
- 如果没有全局凭据，查找任意有效凭据
- 返回解密后的凭据

**注意**: 这是内部方法，用于获取凭据以创建模型实例

## 服务层设计原则

### 1. 单一职责

每个 Service 负责一个明确的业务领域：
- `ModelService`: 模型实例管理
- `ModelProviderService`: 供应商管理
- `ModelCredentialService`: 凭据管理

### 2. 依赖注入

Service 通过构造函数接收依赖（如 `AsyncSession`），便于测试和扩展。

### 3. 事务管理

Service 负责事务管理，通过 `commit()` 方法提交事务。

### 4. 错误处理

Service 层处理业务逻辑错误，抛出适当的异常（如 `NotFoundException`、`BadRequestException`）。

## 数据流

```
API 层
    ↓
Service 层（业务逻辑）
    ↓
Repository 层（数据访问）
    ↓
Core 层（模型工厂）
    ↓
数据库
```

## 使用示例

### 完整的业务流程

```python
from app.services.model_provider_service import ModelProviderService
from app.services.model_credential_service import ModelCredentialService
from app.services.model_service import ModelService
from app.core.model import ModelType

# 1. 同步供应商和模型
provider_service = ModelProviderService(db)
result = await provider_service.sync_all()

# 2. 创建凭据
credential_service = ModelCredentialService(db)
credential = await credential_service.create_or_update_credential(
    user_id="user123",
    provider_name="openaiapicompatible",
    credentials={"api_key": "sk-..."},
    validate=True
)

# 3. 创建模型实例配置
model_service = ModelService(db)
instance = await model_service.create_model_instance_config(
    user_id="user123",
    provider_name="openaiapicompatible",
    model_name="gpt-4",
    model_type=ModelType.CHAT,
    is_default=True
)

# 4. 获取模型实例并使用
model = await model_service.get_model_instance(
    user_id="user123",
    provider_name="openaiapicompatible",
    model_name="gpt-4"
)
response = await model.ainvoke("Hello, world!")
```

## 注意事项

1. **异步操作**: 所有方法都是异步的，需要使用 `await`
2. **事务管理**: Service 负责事务提交，Repository 只执行操作
3. **凭据安全**: 凭据在 Service 层加密/解密，API 层不返回明文
4. **全局可见性**: 当前实现中，模型和凭据对所有用户和工作空间可见
5. **错误处理**: Service 层应该处理业务逻辑错误并抛出适当的异常

## 扩展指南

要添加新的业务逻辑：

1. 在相应的 Service 类中添加新方法
2. 使用 Repository 进行数据访问
3. 使用 Core 层的工厂创建模型实例
4. 处理异常并返回适当的错误信息
5. 在 API 层调用新方法
