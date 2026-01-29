# Model Repository 文档

## 概述

`backend/app/repositories` 目录下的模型相关 Repository 提供了数据访问层（DAL），封装了数据库操作，为 Service 层提供简洁的数据访问接口。

## 相关 Repository 文件

- `model_provider.py` - 模型供应商 Repository
- `model_instance.py` - 模型实例 Repository
- `model_credential.py` - 模型凭据 Repository

## Repository 详解

### 1. ModelProviderRepository (model_provider.py)

模型供应商的数据访问层。

#### 继承关系

继承自 `BaseRepository[ModelProvider]`，提供基础的 CRUD 操作。

#### 主要方法

##### `get_by_name(name: str) -> ModelProvider | None`

根据供应商名称获取供应商实例。

**参数**:
- `name`: 供应商名称

**返回**: 供应商实例，如果不存在则返回 `None`

**使用示例**:
```python
repo = ModelProviderRepository(db)
provider = await repo.get_by_name("openaiapicompatible")
```

##### `list_enabled() -> list[ModelProvider]`

获取所有启用的供应商列表。

**返回**: 启用的供应商列表

**使用示例**:
```python
repo = ModelProviderRepository(db)
enabled_providers = await repo.list_enabled()
```

#### 继承的基类方法

- `find()`: 查找所有记录
- `get(id)`: 根据ID获取记录
- `create(data)`: 创建新记录
- `update(id, data)`: 更新记录
- `delete(id)`: 删除记录

### 2. ModelInstanceRepository (model_instance.py)

模型实例配置的数据访问层。

#### 主要方法

##### `get_default(user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> ModelInstance | None`

获取默认模型实例。

**注意**: 当前实现中，所有用户和工作空间可见（不进行 user_id 和 workspace_id 过滤）

**参数**:
- `user_id`: 用户ID（已废弃，保留用于向后兼容）
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 默认模型实例，如果不存在则返回 `None`

**使用示例**:
```python
repo = ModelInstanceRepository(db)
default_instance = await repo.get_default()
```

##### `list_by_user(user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> list[ModelInstance]`

获取所有模型实例（所有用户和工作空间可见）。

**注意**: 当前实现中，不进行 user_id 和 workspace_id 过滤

**参数**:
- `user_id`: 用户ID（已废弃，保留用于向后兼容）
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 模型实例列表

**使用示例**:
```python
repo = ModelInstanceRepository(db)
instances = await repo.list_by_user()
```

##### `get_by_name(model_name: str, workspace_id: Optional[uuid.UUID] = None) -> ModelInstance | None`

根据模型名称获取模型实例。

**注意**: 当前实现中，不进行 workspace_id 过滤

**参数**:
- `model_name`: 模型名称
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 模型实例，如果不存在则返回 `None`

**使用示例**:
```python
repo = ModelInstanceRepository(db)
instance = await repo.get_by_name("gpt-4")
```

##### `get_by_provider_and_model(provider_id: uuid.UUID, model_name: str) -> ModelInstance | None`

根据供应商ID和模型名称获取实例（用于同步）。

**参数**:
- `provider_id`: 供应商ID
- `model_name`: 模型名称

**返回**: 模型实例，如果不存在则返回 `None`

**注意**: 只查询全局记录（user_id 为 NULL）

**使用示例**:
```python
repo = ModelInstanceRepository(db)
instance = await repo.get_by_provider_and_model(provider_id, "gpt-4")
```

##### `list_all() -> list[ModelInstance]`

获取所有模型实例（所有用户和工作空间可见）。

**返回**: 模型实例列表

**使用示例**:
```python
repo = ModelInstanceRepository(db)
all_instances = await repo.list_all()
```

### 3. ModelCredentialRepository (model_credential.py)

模型凭据的数据访问层。

#### 主要方法

##### `get_by_user_and_provider(user_id: Optional[str] = None, provider_id: Optional[uuid.UUID] = None, workspace_id: Optional[uuid.UUID] = None) -> ModelCredential | None`

根据用户和供应商获取凭据（所有用户和工作空间可见）。

**注意**: 当前实现中，不进行 user_id 和 workspace_id 过滤

**参数**:
- `user_id`: 用户ID（已废弃，保留用于向后兼容）
- `provider_id`: 供应商ID
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 凭据实例，如果不存在则返回 `None`

**使用示例**:
```python
repo = ModelCredentialRepository(db)
credential = await repo.get_by_user_and_provider(provider_id=provider.id)
```

##### `get_by_provider(provider_id: uuid.UUID) -> ModelCredential | None`

根据供应商获取全局凭据（用于同步）。

**参数**:
- `provider_id`: 供应商ID

**返回**: 凭据实例，如果不存在则返回 `None`

**注意**: 只查询全局记录（user_id 为 NULL）

**使用示例**:
```python
repo = ModelCredentialRepository(db)
credential = await repo.get_by_provider(provider.id)
```

##### `list_by_user(user_id: Optional[str] = None, workspace_id: Optional[uuid.UUID] = None) -> list[ModelCredential]`

获取所有凭据（所有用户和工作空间可见）。

**注意**: 当前实现中，不进行 user_id 和 workspace_id 过滤，使用 `selectinload` 预加载关联的 provider

**参数**:
- `user_id`: 用户ID（已废弃，保留用于向后兼容）
- `workspace_id`: 工作空间ID（已废弃，保留用于向后兼容）

**返回**: 凭据列表

**使用示例**:
```python
repo = ModelCredentialRepository(db)
credentials = await repo.list_by_user()
```

##### `list_all() -> list[ModelCredential]`

获取所有凭据（所有用户和工作空间可见）。

**返回**: 凭据列表

**注意**: 使用 `selectinload` 预加载关联的 provider

**使用示例**:
```python
repo = ModelCredentialRepository(db)
all_credentials = await repo.list_all()
```

## 设计模式

### Repository 模式

Repository 模式将数据访问逻辑封装在独立的层中，提供以下优势：

1. **解耦**: Service 层不需要了解数据库细节
2. **可测试性**: 可以轻松模拟 Repository 进行单元测试
3. **可维护性**: 数据库查询逻辑集中管理
4. **可扩展性**: 可以轻松切换数据源或添加缓存层

### 基类功能

所有 Repository 都继承自 `BaseRepository`，提供：

- 通用的 CRUD 操作
- 类型安全的查询
- 关系加载支持
- 事务管理

## 查询优化

### 预加载关联

使用 SQLAlchemy 的 `selectinload` 策略预加载关联对象，避免 N+1 查询问题：

```python
result = await self.db.execute(
    select(ModelCredential)
    .options(selectinload(ModelCredential.provider))
)
```

### 索引利用

Repository 方法设计时考虑了数据库索引，确保查询性能：

- 单字段索引：`get_by_name`、`get_by_provider`
- 复合索引：`get_by_provider_and_model`

## 注意事项

1. **全局可见性**: 当前实现中，模型实例和凭据对所有用户和工作空间可见（不进行过滤）
2. **异步操作**: 所有方法都是异步的，需要使用 `await`
3. **会话管理**: Repository 接收 `AsyncSession` 实例，不负责会话的生命周期
4. **事务**: 事务管理在 Service 层进行，Repository 只执行查询和更新操作

## 使用示例

### 完整的查询流程

```python
from app.repositories.model_provider import ModelProviderRepository
from app.repositories.model_instance import ModelInstanceRepository
from app.repositories.model_credential import ModelCredentialRepository

# 在 Service 中使用
class ModelService:
    def __init__(self, db: AsyncSession):
        self.provider_repo = ModelProviderRepository(db)
        self.instance_repo = ModelInstanceRepository(db)
        self.credential_repo = ModelCredentialRepository(db)

    async def get_model_info(self, provider_name: str):
        # 获取供应商
        provider = await self.provider_repo.get_by_name(provider_name)
        if not provider:
            return None

        # 获取模型实例
        instances = await self.instance_repo.list_all()

        # 获取凭据
        credential = await self.credential_repo.get_by_provider(provider.id)

        return {
            "provider": provider,
            "instances": instances,
            "credential": credential
        }
```

## 扩展指南

要添加新的查询方法：

1. 在相应的 Repository 类中添加新方法
2. 使用 SQLAlchemy 的 `select` 构建查询
3. 考虑添加适当的索引以优化性能
4. 在 Service 层使用新方法
