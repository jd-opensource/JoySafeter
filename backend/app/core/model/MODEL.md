# Model Core 文档

## 概述

`backend/app/core/model` 目录是模型系统的核心层，提供了模型工厂、供应商抽象、模型包装器等核心功能。该模块将模型和上下游解耦，方便开发者对模型进行横向扩展。

## 目录结构

```
core/model/
├── __init__.py          # 模块导出
├── factory.py           # 模型工厂
├── providers/           # 供应商实现
│   ├── __init__.py
│   ├── base.py          # 供应商基类
│   └── OpenaiApiCompatible.py  # OpenAI 兼容供应商
├── models/               # 模型包装器
│   ├── __init__.py
│   ├── base.py          # 模型包装器基类
│   ├── chat_model.py    # 聊天模型包装器
│   ├── embedding_model.py  # 嵌入模型包装器
│   └── rerank_model.py  # 重排序模型包装器
└── utils/               # 工具函数
    ├── __init__.py
    └── encryption.py    # 加密工具
```

## 核心组件

### 1. 模型工厂 (factory.py)

`ModelFactory` 是模型系统的核心，负责管理所有供应商并提供统一的模型创建接口。

#### 主要功能

- **供应商管理**: 注册、获取供应商实例
- **模型创建**: 通过供应商创建模型实例
- **凭据验证**: 验证供应商和模型的凭据
- **信息查询**: 获取所有供应商和模型列表

#### 关键方法

```python
# 获取全局工厂实例
factory = get_factory()

# 获取所有供应商信息
providers = factory.get_all_providers()

# 创建模型实例
model = factory.create_model_instance(
    provider_name="openaiapicompatible",
    model_name="gpt-4",
    model_type=ModelType.CHAT,
    credentials={"api_key": "..."},
    model_parameters={"temperature": 0.7}
)

# 验证凭据
is_valid, error = await factory.validate_provider_credentials(
    provider_name="openaiapicompatible",
    credentials={"api_key": "..."}
)
```

### 2. 供应商层 (providers/)

供应商层定义了供应商的抽象接口和具体实现。

#### BaseProvider (base.py)

所有供应商的基类，定义了供应商必须实现的接口：

- `get_supported_model_types()`: 获取支持的模型类型列表
- `get_credential_schema()`: 获取凭据表单规则（JSON Schema）
- `get_config_schema(model_type)`: 获取模型参数配置规则
- `validate_credentials(credentials)`: 验证凭据
- `get_model_list(model_type, credentials)`: 获取模型列表
- `create_model_instance(model_name, model_type, credentials, model_parameters)`: 创建模型实例

#### 模型类型 (ModelType)

支持的模型类型枚举：

- `CHAT`: 聊天模型
- `EMBEDDING`: 嵌入模型
- `RERANK`: 重排序模型
- `SPEECH_TO_TEXT`: 语音转文本
- `TEXT_TO_SPEECH`: 文本转语音
- `MODERATION`: 内容审核

#### 实现示例

`OpenaiApiCompatible.py` 是 OpenAI API 兼容供应商的实现，支持所有兼容 OpenAI API 的模型服务。

### 3. 模型层 (models/)

模型层提供了各种模型类型的包装器，统一管理模型实例。

#### BaseModelWrapper (base.py)

模型包装器基类，提供：

- 模型实例的封装
- 方法代理（通过 `__getattr__` 代理所有方法调用）
- 供应商和模型名称的追踪

#### 具体模型包装器

- `ChatModelWrapper`: 聊天模型包装器
- `EmbeddingModelWrapper`: 嵌入模型包装器
- `RerankModelWrapper`: 重排序模型包装器

### 4. 工具函数 (utils/)

#### encryption.py

提供凭据加密和解密功能：

- `encrypt_credentials(credentials)`: 加密凭据
- `decrypt_credentials(encrypted_credentials)`: 解密凭据

## 架构设计

### 三层架构

```
工厂层 (Factory)
    ↓
供应商层 (Provider)
    ↓
模型层 (Model)
```

1. **工厂层**: 统一管理所有供应商，提供全局访问接口
2. **供应商层**: 实现特定供应商的逻辑，可横向扩展
3. **模型层**: 封装具体的模型实例，提供统一的调用接口

### 扩展机制

#### 添加新供应商

1. 创建新的供应商类，继承 `BaseProvider`
2. 实现所有抽象方法
3. 在工厂中注册供应商：

```python
from app.core.model import get_factory
from app.core.model.providers import BaseProvider

class MyProvider(BaseProvider):
    # 实现所有抽象方法
    ...

# 注册供应商
factory = get_factory()
factory.register_provider(MyProvider())
```

#### 添加新模型类型

1. 在 `ModelType` 枚举中添加新类型
2. 在供应商中实现该类型的支持
3. 创建对应的模型包装器（如需要）

## 使用示例

### 创建模型实例

```python
from app.core.model import create_model_instance, ModelType

# 创建聊天模型
model = create_model_instance(
    provider_name="openaiapicompatible",
    model_name="gpt-4",
    model_type=ModelType.CHAT,
    credentials={
        "api_key": "sk-...",
        "base_url": "https://api.openai.com/v1"
    },
    model_parameters={
        "temperature": 0.7,
        "max_tokens": 2000
    }
)

# 使用模型
response = await model.ainvoke("Hello, world!")
print(response.content)
```

### 获取供应商信息

```python
from app.core.model import get_all_providers

providers = get_all_providers()
for provider in providers:
    print(f"{provider['display_name']}: {provider['supported_model_types']}")
```

### 验证凭据

```python
from app.core.model import validate_provider_credentials

is_valid, error = await validate_provider_credentials(
    provider_name="openaiapicompatible",
    credentials={"api_key": "sk-..."}
)

if is_valid:
    print("凭据有效")
else:
    print(f"凭据无效: {error}")
```

## Schema 设计

### 凭据 Schema

供应商通过 `get_credential_schema()` 返回 JSON Schema 格式的凭据表单规则，前端可以直接使用这些规则渲染表单。

### 配置 Schema

供应商通过 `get_config_schema(model_type)` 返回模型参数的配置规则，定义了每个模型类型支持哪些参数以及参数的验证规则。

## 注意事项

1. **异步操作**: 凭据验证是异步操作，需要使用 `await`
2. **凭据安全**: 凭据在传递和存储时都应该加密
3. **错误处理**: 创建模型实例和验证凭据时应该处理异常
4. **扩展性**: 设计时考虑了横向扩展，新增供应商不需要修改现有代码

## 相关文档

- 详细的供应商扩展指南请参考 `README_CN.md`
- Schema 设计规范请参考 `docs/zh_Hans/schema.md`
