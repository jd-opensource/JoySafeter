# Model Database Models 文档

## 概述

`backend/app/models` 目录下的模型相关文件定义了数据库模型（ORM），用于持久化存储模型供应商、模型实例和模型凭据等信息。

## 相关模型文件

- `model_provider.py` - 模型供应商模型
- `model_instance.py` - 模型实例配置模型
- `model_credential.py` - 模型凭据模型

## 数据模型详解

### 1. ModelProvider (model_provider.py)

模型供应商表，存储供应商的基本信息和配置规则。

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `name` | String(100) | 供应商唯一标识，如 'openai', 'anthropic' |
| `display_name` | String(255) | 显示名称，如 'OpenAI', 'Anthropic' |
| `icon` | String(500) | 图标URL（可选） |
| `description` | String(1000) | 供应商描述（可选） |
| `supported_model_types` | JSON | 支持的模型类型列表，如 ["llm", "chat", "embedding"] |
| `credential_schema` | JSON | 凭据表单规则（JSON Schema格式） |
| `config_schema` | JSON | 模型参数配置规则（可选） |
| `is_enabled` | Boolean | 是否启用该供应商 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

#### 关系

- `credentials`: 一对多关系，关联到 `ModelCredential`

#### 索引

- `model_provider_name_idx`: 名称索引
- `model_provider_enabled_idx`: 启用状态索引

### 2. ModelInstance (model_instance.py)

模型实例配置表，存储用户配置的模型实例信息。

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | String(255) | 用户ID，如果为None则为全局模型记录 |
| `workspace_id` | UUID | 工作空间ID，如果为None则为用户级配置 |
| `provider_id` | UUID | 供应商ID（外键） |
| `model_name` | String(255) | 模型名称，如 'gpt-4o', 'claude-3-5-sonnet' |
| `model_parameters` | JSON | 模型参数配置，如 {"temperature": 0.7, "max_tokens": 2000} |
| `is_default` | Boolean | 是否为默认模型 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

#### 关系

- `provider`: 多对一关系，关联到 `ModelProvider`
- `user`: 多对一关系，关联到 `AuthUser`（可选）
- `workspace`: 多对一关系，关联到 `Workspace`（可选）

#### 索引

- `model_instance_user_id_idx`: 用户ID索引
- `model_instance_workspace_id_idx`: 工作空间ID索引
- `model_instance_provider_id_idx`: 供应商ID索引
- `model_instance_user_provider_model_idx`: 用户-供应商-模型复合索引

#### 唯一约束

- `uq_model_instance_user_provider_model`: 确保同一用户/工作空间对同一供应商+模型只有一条配置

#### 作用域说明

- **全局记录**: `user_id` 和 `workspace_id` 都为 `NULL`，所有用户可见
- **用户级配置**: `user_id` 不为 `NULL`，`workspace_id` 为 `NULL`
- **工作空间级配置**: `user_id` 和 `workspace_id` 都不为 `NULL`

### 3. ModelCredential (model_credential.py)

模型凭据表，存储加密后的供应商凭据信息。

#### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `user_id` | String(255) | 用户ID，如果为None则为全局认证信息 |
| `workspace_id` | UUID | 工作空间ID，如果为None则为用户级凭据 |
| `provider_id` | UUID | 供应商ID（外键） |
| `credentials` | String(4096) | 加密存储的凭据（base64编码） |
| `is_valid` | Boolean | 凭据是否有效 |
| `last_validated_at` | DateTime | 最后验证时间（可选） |
| `validation_error` | String(1000) | 验证错误信息（可选） |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

#### 关系

- `provider`: 多对一关系，关联到 `ModelProvider`
- `user`: 多对一关系，关联到 `AuthUser`（可选）
- `workspace`: 多对一关系，关联到 `Workspace`（可选）

#### 索引

- `model_credential_user_id_idx`: 用户ID索引
- `model_credential_workspace_id_idx`: 工作空间ID索引
- `model_credential_provider_id_idx`: 供应商ID索引
- `model_credential_user_provider_idx`: 用户-供应商复合索引

#### 约束

- `model_credential_scope_check`: 检查约束，确保作用域正确

#### 安全说明

- 所有凭据在存储前都会进行加密处理
- 凭据字段使用 base64 编码存储
- 解密操作只在服务层进行，API 层不返回解密后的凭据

## 数据关系图

```
ModelProvider (供应商)
    ├── 1:N ──> ModelCredential (凭据)
    └── 1:N ──> ModelInstance (模型实例)
            ├── N:1 ──> AuthUser (用户，可选)
            └── N:1 ──> Workspace (工作空间，可选)
```

## 使用场景

### 全局配置

当 `user_id` 和 `workspace_id` 都为 `NULL` 时，表示全局配置，所有用户和工作空间都可以使用：

```python
# 创建全局模型实例
instance = ModelInstance(
    user_id=None,
    workspace_id=None,
    provider_id=provider.id,
    model_name="gpt-4",
    model_parameters={},
    is_default=True
)
```

### 用户级配置

当 `user_id` 不为 `NULL` 但 `workspace_id` 为 `NULL` 时，表示用户级配置：

```python
# 创建用户级模型实例
instance = ModelInstance(
    user_id="user123",
    workspace_id=None,
    provider_id=provider.id,
    model_name="gpt-4",
    model_parameters={},
    is_default=False
)
```

### 工作空间级配置

当 `user_id` 和 `workspace_id` 都不为 `NULL` 时，表示工作空间级配置：

```python
# 创建工作空间级模型实例
instance = ModelInstance(
    user_id="user123",
    workspace_id=workspace_id,
    provider_id=provider.id,
    model_name="gpt-4",
    model_parameters={},
    is_default=False
)
```

## 数据库迁移

模型定义通过 Alembic 进行数据库迁移管理。相关迁移文件位于 `backend/alembic/versions/`。

## 注意事项

1. **软删除**: 所有模型都继承自 `BaseModel`，可能包含软删除功能
2. **时间戳**: 所有模型都自动维护 `created_at` 和 `updated_at` 字段
3. **外键约束**: 删除供应商时会级联删除相关的模型实例和凭据
4. **唯一性**: 模型实例有唯一约束，防止重复配置
5. **加密**: 凭据必须加密存储，不能明文保存

## 查询优化

- 使用索引加速查询
- 使用 `selectin` 加载策略优化关联查询
- 复合索引支持多条件查询

## 扩展指南

要添加新字段：

1. 在模型类中添加字段定义
2. 创建 Alembic 迁移文件
3. 运行迁移更新数据库结构
4. 更新相关的 Repository 和 Service 层代码
