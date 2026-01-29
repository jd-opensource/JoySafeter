# Model 系统总体文档

## 概述

Model 系统是 Agent Platform 的核心组件之一，提供了完整的模型管理功能，包括模型供应商管理、模型实例配置、模型凭据管理等。系统采用分层架构设计，实现了模型与上下游的解耦，方便开发者进行横向扩展。

## 系统架构

### 分层架构

```
┌─────────────────────────────────────────┐
│         API 层 (api/v1/)                │
│  - models.py                            │
│  - model_providers.py                   │
│  - model_credentials.py                 │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│      Service 层 (services/)             │
│  - model_service.py                     │
│  - model_provider_service.py            │
│  - model_credential_service.py          │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│   Repository 层 (repositories/)         │
│  - model_provider.py                    │
│  - model_instance.py                    │
│  - model_credential.py                  │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│      Model 层 (models/)                 │
│  - model_provider.py                    │
│  - model_instance.py                    │
│  - model_credential.py                  │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│      Core 层 (core/model/)              │
│  - factory.py (模型工厂)                │
│  - providers/ (供应商实现)              │
│  - models/ (模型包装器)                 │
│  - utils/ (工具函数)                    │
└─────────────────────────────────────────┘
```

### 核心组件

1. **API 层**: 提供 HTTP 接口，处理请求和响应
2. **Service 层**: 实现业务逻辑，协调各层交互
3. **Repository 层**: 数据访问层，封装数据库操作
4. **Model 层**: 数据库模型定义（ORM）
5. **Core 层**: 模型工厂和供应商实现

## 目录结构

```
backend/app/
├── api/v1/
│   ├── models.py                    # 模型实例 API
│   ├── model_providers.py           # 模型供应商 API
│   └── model_credentials.py        # 模型凭据 API
│
├── services/
│   ├── model_service.py            # 模型服务
│   ├── model_provider_service.py   # 模型供应商服务
│   └── model_credential_service.py # 模型凭据服务
│
├── repositories/
│   ├── model_provider.py           # 模型供应商 Repository
│   ├── model_instance.py           # 模型实例 Repository
│   └── model_credential.py         # 模型凭据 Repository
│
├── models/
│   ├── model_provider.py           # 模型供应商模型
│   ├── model_instance.py           # 模型实例模型
│   └── model_credential.py         # 模型凭据模型
│
└── core/model/
    ├── factory.py                  # 模型工厂
    ├── providers/                  # 供应商实现
    │   ├── base.py                 # 供应商基类
    │   └── OpenaiApiCompatible.py  # OpenAI 兼容供应商
    ├── models/                      # 模型包装器
    │   ├── base.py                 # 模型包装器基类
    │   ├── chat_model.py           # 聊天模型包装器
    │   ├── embedding_model.py     # 嵌入模型包装器
    │   └── rerank_model.py         # 重排序模型包装器
    └── utils/                      # 工具函数
        └── encryption.py           # 加密工具
```

## 数据模型

### 1. ModelProvider (模型供应商)

存储供应商的基本信息和配置规则。

**主要字段**:
- `name`: 供应商唯一标识
- `display_name`: 显示名称
- `supported_model_types`: 支持的模型类型列表
- `credential_schema`: 凭据表单规则
- `config_schema`: 模型参数配置规则
- `is_enabled`: 是否启用

### 2. ModelInstance (模型实例)

存储用户配置的模型实例信息。

**主要字段**:
- `provider_id`: 供应商ID
- `model_name`: 模型名称
- `model_parameters`: 模型参数配置
- `is_default`: 是否为默认模型
- `user_id`: 用户ID（NULL 表示全局）
- `workspace_id`: 工作空间ID（NULL 表示用户级）

### 3. ModelCredential (模型凭据)

存储加密后的供应商凭据信息。

**主要字段**:
- `provider_id`: 供应商ID
- `credentials`: 加密存储的凭据
- `is_valid`: 凭据是否有效
- `last_validated_at`: 最后验证时间
- `validation_error`: 验证错误信息
- `user_id`: 用户ID（NULL 表示全局）
- `workspace_id`: 工作空间ID（NULL 表示用户级）

## 核心功能

### 1. 模型供应商管理

- **注册供应商**: 通过工厂模式注册新的供应商
- **同步供应商**: 从代码同步供应商信息到数据库
- **查询供应商**: 获取所有供应商列表和详情
- **启用/禁用**: 控制供应商的可用性

### 2. 模型实例管理

- **创建配置**: 创建模型实例配置
- **查询列表**: 获取可用模型列表
- **默认模型**: 设置和管理默认模型
- **模型测试**: 测试模型输出

### 3. 模型凭据管理

- **创建/更新**: 创建或更新供应商凭据
- **加密存储**: 所有凭据加密存储
- **验证凭据**: 验证凭据的有效性
- **查询凭据**: 获取凭据列表和详情
- **删除凭据**: 删除不再需要的凭据

### 4. 模型调用

- **创建实例**: 通过工厂创建 LangChain 模型实例
- **统一接口**: 提供统一的模型调用接口
- **参数配置**: 支持模型参数的动态配置

## 工作流程

### 1. 初始化流程

```
1. 系统启动
   ↓
2. 调用 sync_all() 同步供应商、模型和凭据
   ↓
3. 从工厂获取供应商信息
   ↓
4. 同步到数据库（model_provider 表）
   ↓
5. 从工厂获取模型列表
   ↓
6. 同步到数据库（model_instance 表，全局记录）
   ↓
7. 从 .env 读取凭据
   ↓
8. 加密并同步到数据库（model_credential 表，全局记录）
```

### 2. 使用模型流程

```
1. 用户请求使用模型
   ↓
2. API 层接收请求
   ↓
3. Service 层处理业务逻辑
   ↓
4. Repository 层查询数据库
   ↓
5. Service 层获取解密后的凭据
   ↓
6. Core 层工厂创建模型实例
   ↓
7. 返回模型实例供使用
```

### 3. 创建凭据流程

```
1. 用户提交凭据
   ↓
2. API 层接收请求
   ↓
3. Service 层验证供应商是否存在
   ↓
4. Service 层验证凭据（可选）
   ↓
5. Service 层加密凭据
   ↓
6. Repository 层保存到数据库
   ↓
7. 返回创建结果
```

## API 端点总览

### 模型实例 API

- `GET /api/v1/models` - 获取可用模型列表
- `POST /api/v1/models/instances` - 创建模型实例配置
- `GET /api/v1/models/instances` - 获取模型实例配置列表
- `POST /api/v1/models/test-output` - 测试模型输出

### 模型供应商 API

- `GET /api/v1/model-providers` - 获取所有供应商列表
- `GET /api/v1/model-providers/{provider_name}` - 获取单个供应商详情
- `POST /api/v1/model-providers/sync` - 同步供应商、模型和认证信息

### 模型凭据 API

- `POST /api/v1/model-credentials` - 创建或更新凭据
- `GET /api/v1/model-credentials` - 获取凭据列表
- `GET /api/v1/model-credentials/{credential_id}` - 获取凭据详情
- `POST /api/v1/model-credentials/{credential_id}/validate` - 验证凭据
- `DELETE /api/v1/model-credentials/{credential_id}` - 删除凭据

## 扩展指南

### 添加新供应商

1. 在 `core/model/providers/` 创建新的供应商类
2. 继承 `BaseProvider` 并实现所有抽象方法
3. 在工厂中注册新供应商
4. 运行同步接口更新数据库

### 添加新模型类型

1. 在 `ModelType` 枚举中添加新类型
2. 在供应商中实现该类型的支持
3. 创建对应的模型包装器（如需要）

### 添加新 API 端点

1. 在相应的 API 文件中添加路由
2. 在 Service 层添加业务逻辑
3. 在 Repository 层添加数据访问方法（如需要）

## 安全考虑

1. **凭据加密**: 所有凭据在存储前都进行加密
2. **访问控制**: API 层应该实现认证和授权（当前为临时实现）
3. **验证机制**: 提供凭据验证功能，确保凭据有效
4. **错误处理**: 不暴露敏感信息 in 错误消息

## 性能优化

1. **索引优化**: 数据库表添加了适当的索引
2. **预加载**: 使用 `selectinload` 预加载关联对象
3. **缓存**: 可以考虑添加缓存层（未来优化）

## 注意事项

1. **全局可见性**: 当前实现中，模型实例和凭据对所有用户和工作空间可见（user_id 和 workspace_id 为 NULL 的记录）
2. **认证**: 当前代码中用户认证部分被注释，使用匿名用户ID，后续需要恢复认证机制
3. **同步机制**: 供应商和模型信息通过工厂模式从代码同步到数据库
4. **凭据管理**: 凭据加密存储，解密操作只在 Service 层进行

## 相关文档

- [API 层文档](./api/v1/MODEL.md)
- [Service 层文档](./services/MODEL.md)
- [Repository 层文档](./repositories/MODEL.md)
- [Model 层文档](./models/MODEL.md)
- [Core 层文档](./core/model/MODEL.md)
- [Core 层详细文档](./core/model/README_CN.md)

## 未来改进

1. **多租户支持**: 完善用户和工作空间的隔离机制
2. **缓存机制**: 添加缓存层提高性能
3. **监控和日志**: 添加模型调用的监控和日志
4. **限流和配额**: 实现模型调用的限流和配额管理
5. **更多供应商**: 支持更多模型供应商
