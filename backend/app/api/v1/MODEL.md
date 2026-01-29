# Model API 文档

## 概述

`backend/app/api/v1` 目录下的模型相关 API 提供了模型管理的 HTTP 接口，包括模型实例、模型供应商和模型凭据的管理功能。

## 文件结构

- `models.py` - 模型实例管理 API
- `model_providers.py` - 模型供应商管理 API
- `model_credentials.py` - 模型凭据管理 API

## API 端点

### 模型实例 API (`models.py`)

#### 1. 获取可用模型列表
- **端点**: `GET /api/v1/models`
- **功能**: 获取指定类型的可用模型列表
- **参数**:
  - `model_type` (query): 模型类型，如 "chat", "embedding" 等
  - `workspaceId` (query, optional): 工作空间ID
- **返回**: 可用模型列表，包含供应商信息、模型名称、是否可用等

#### 2. 创建模型实例配置
- **端点**: `POST /api/v1/models/instances`
- **功能**: 创建新的模型实例配置
- **请求体**:
  - `provider_name`: 供应商名称
  - `model_name`: 模型名称
  - `model_type`: 模型类型
  - `model_parameters`: 模型参数配置（可选）
  - `workspaceId`: 工作空间ID（可选）
  - `is_default`: 是否为默认模型
- **返回**: 创建的模型实例配置

#### 3. 获取模型实例配置列表
- **端点**: `GET /api/v1/models/instances`
- **功能**: 获取所有模型实例配置
- **参数**:
  - `workspaceId` (query, optional): 工作空间ID
- **返回**: 模型实例配置列表

#### 4. 测试模型输出
- **端点**: `POST /api/v1/models/test-output`
- **功能**: 测试指定模型的输出
- **请求体**:
  - `model_name`: 模型名称
  - `input`: 输入文本
  - `workspaceId`: 工作空间ID（可选）
- **返回**: 模型输出结果

### 模型供应商 API (`model_providers.py`)

#### 1. 获取所有供应商列表
- **端点**: `GET /api/v1/model-providers`
- **功能**: 获取所有已注册的模型供应商信息
- **返回**: 供应商列表，包含：
  - `provider_name`: 供应商名称
  - `display_name`: 显示名称
  - `supported_model_types`: 支持的模型类型列表
  - `credential_schema`: 凭据表单规则
  - `config_schemas`: 配置规则（按模型类型）
  - `is_enabled`: 是否启用

#### 2. 获取单个供应商详情
- **端点**: `GET /api/v1/model-providers/{provider_name}`
- **功能**: 获取指定供应商的详细信息
- **参数**:
  - `provider_name` (path): 供应商名称
- **返回**: 供应商详情

#### 3. 同步供应商、模型和认证信息
- **端点**: `POST /api/v1/model-providers/sync`
- **功能**: 统一同步接口，将供应商、模型和认证信息同步到数据库
- **说明**:
  - 同步供应商信息（从工厂同步）
  - 同步模型信息（从工厂同步到 model_instance 表，全局记录）
  - 同步认证信息（从 .env 读取并同步到 model_credential 表，全局记录）
- **返回**: 同步结果统计

### 模型凭据 API (`model_credentials.py`)

#### 1. 创建或更新凭据
- **端点**: `POST /api/v1/model-credentials`
- **功能**: 创建或更新模型供应商的凭据
- **请求体**:
  - `provider_name`: 供应商名称
  - `credentials`: 凭据字典（明文）
  - `workspaceId`: 工作空间ID（可选）
  - `validate`: 是否验证凭据（默认 true）
- **返回**: 创建的凭据信息（不包含解密后的凭据）

#### 2. 获取凭据列表
- **端点**: `GET /api/v1/model-credentials`
- **功能**: 获取所有凭据列表
- **参数**:
  - `workspaceId` (query, optional): 工作空间ID
- **返回**: 凭据列表

#### 3. 获取凭据详情
- **端点**: `GET /api/v1/model-credentials/{credential_id}`
- **功能**: 获取指定凭据的详细信息
- **参数**:
  - `credential_id` (path): 凭据ID
- **返回**: 凭据详情（不包含解密后的凭据）

#### 4. 验证凭据
- **端点**: `POST /api/v1/model-credentials/{credential_id}/validate`
- **功能**: 验证指定凭据的有效性
- **参数**:
  - `credential_id` (path): 凭据ID
- **返回**: 验证结果，包含 `is_valid`、`error`、`last_validated_at`

#### 5. 删除凭据
- **端点**: `DELETE /api/v1/model-credentials/{credential_id}`
- **功能**: 删除指定凭据
- **参数**:
  - `credential_id` (path): 凭据ID

## 数据流

```
客户端请求
    ↓
API 路由层 (models.py, model_providers.py, model_credentials.py)
    ↓
Service 层 (ModelService, ModelProviderService, ModelCredentialService)
    ↓
Repository 层 (ModelInstanceRepository, ModelProviderRepository, ModelCredentialRepository)
    ↓
数据库 (model_instance, model_provider, model_credential 表)
```

## 依赖关系

- **Service 层**: 依赖 `ModelService`、`ModelProviderService`、`ModelCredentialService`
- **Core 层**: 依赖 `app.core.model` 模块（工厂、模型类型等）
- **数据库**: 使用 SQLAlchemy 异步会话

## 注意事项

1. **认证**: 当前代码中用户认证部分被注释，使用匿名用户ID，后续需要恢复认证机制
2. **全局可见性**: 模型实例和凭据对所有用户和工作空间可见（user_id 和 workspace_id 为 NULL 的记录）
3. **凭据加密**: 所有凭据在存储前都会进行加密处理
4. **同步机制**: 供应商和模型信息通过工厂模式从代码同步到数据库

## 扩展指南

要添加新的 API 端点：

1. 在相应的文件中添加新的路由函数
2. 使用 `@router.get/post/put/delete` 装饰器
3. 通过 Service 层处理业务逻辑
4. 返回统一的响应格式（使用 `success_response`）
