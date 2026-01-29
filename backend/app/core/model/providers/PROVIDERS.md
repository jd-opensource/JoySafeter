# Provider 添加指南

本文档说明如何快速添加新的模型 Provider 到系统中。

## 概述

Provider 系统已实现自动发现、自动注册和动态配置。添加新的 Provider 现在只需要：

1. 创建 Provider 类文件
2. 在 `.env` 文件中配置环境变量


## 快速开始

### 步骤 1: 创建 Provider 类

在 `backend/app/core/model/providers/` 目录下创建一个新的 Python 文件，例如 `MyProvider.py`：

```python
"""
MyProvider 供应商实现
"""
from typing import Any, Dict, List, Optional
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI  # 或其他 LangChain 模型类
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class MyProvider(BaseProvider):
    """MyProvider 供应商"""

    # 预定义的 Chat 模型列表
    PREDEFINED_CHAT_MODELS = [
        {
            "name": "model-name-1",
            "display_name": "Model Display Name 1",
            "description": "模型描述",
        },
        {
            "name": "model-name-2",
            "display_name": "Model Display Name 2",
            "description": "模型描述",
        },
    ]

    def __init__(self):
        super().__init__(
            provider_name="myprovider",  # 小写，用于标识
            display_name="My Provider"   # 显示名称
        )

    def get_supported_model_types(self) -> List[ModelType]:
        """获取支持的模型类型"""
        return [ModelType.CHAT]  # 或 ModelType.EMBEDDING 等

    def get_credential_schema(self) -> Dict[str, Any]:
        """获取凭据表单规则（JSON Schema 格式）"""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "API 密钥",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API 基础 URL",
                    "required": True,
                },
                # 可以添加更多字段
                # "region": {
                #     "type": "string",
                #     "title": "Region",
                #     "description": "区域",
                # },
            },
            "required": ["api_key", "base_url"],  # 必需字段列表
        }

    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """获取模型参数配置规则（JSON Schema 格式）"""
        if model_type == ModelType.CHAT:
            return {
                "type": "object",
                "properties": {
                    "temperature": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "控制输出的随机性，范围 0-2",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 2,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "title": "Max Tokens",
                        "description": "生成的最大 token 数",
                        "default": None,
                        "minimum": 1,
                    },
                    # 可以添加更多参数
                },
            }
        return None

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证凭据"""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API Key 不能为空"

            base_url = credentials.get("base_url")
            if not base_url:
                return False, "Base URL 不能为空"

            # 创建一个临时模型实例进行测试
            model = ChatOpenAI(
                model=self.PREDEFINED_CHAT_MODELS[0]["name"],
                api_key=api_key,
                base_url=base_url,
                max_retries=3,
                timeout=5.0,
            )

            # 尝试调用 API
            response = await model.ainvoke("Hello")
            if response and response.content:
                return True, None
            else:
                return False, "API 调用失败：未收到有效响应"
        except Exception as e:
            return False, f"凭据验证失败：{str(e)}"

    def get_model_list(self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """获取模型列表"""
        if model_type == ModelType.CHAT:
            models = []
            for model in self.PREDEFINED_CHAT_MODELS:
                model_info = {
                    "name": model["name"],
                    "display_name": model["display_name"],
                    "description": model["description"],
                    "is_available": True,
                }
                models.append(model_info)
            return models
        return []

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        """创建模型实例"""
        if model_type != ModelType.CHAT:
            raise ValueError(f"MyProvider 不支持模型类型: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API Key 不能为空")

        base_url = credentials.get("base_url")

        # 构建模型参数
        model_kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,
        }

        if base_url:
            model_kwargs["base_url"] = base_url

        # 添加模型参数
        if model_parameters:
            if "temperature" in model_parameters:
                model_kwargs["temperature"] = model_parameters["temperature"]
            if "max_tokens" in model_parameters:
                model_kwargs["max_completion_tokens"] = model_parameters["max_tokens"]
            # 添加其他参数映射

        return ChatOpenAI(**model_kwargs)
```

### 步骤 2: 配置环境变量

在 `backend/.env` 文件中添加环境变量，遵循以下命名约定：

**格式**: `{PROVIDER_NAME_UPPER}_{FIELD_NAME_UPPER}`

例如，对于 `myprovider`，如果 `credential_schema` 中定义了 `api_key` 和 `base_url`：

```env
# MyProvider 配置
MYPROVIDER_API_KEY=your-api-key-here
MYPROVIDER_BASE_URL=https://api.example.com/v1
```

如果还定义了其他字段（如 `region`），则添加：

```env
MYPROVIDER_REGION=us-east-1
```

**注意**：
- Provider 名称会被转换为大写，并替换 `-` 为 `_`
- 字段名也会被转换为大写，并替换 `-` 为 `_`
- 例如：`my-provider` + `api-key` → `MY_PROVIDER_API_KEY`

### 步骤 3: 完成！

系统会自动：
- ✅ 发现新的 Provider 类
- ✅ 注册到 Factory
- ✅ 从环境变量读取凭据
- ✅ 同步到数据库

无需任何其他配置！

## 环境变量命名约定

### 基本规则

1. Provider 名称（`provider_name`）会被转换为大写
2. 字段名（来自 `credential_schema.properties`）会被转换为大写
3. 两者之间用下划线 `_` 连接
4. 连字符 `-` 会被替换为下划线 `_`

### 示例

| Provider Name | 字段名 | 环境变量名 |
|--------------|--------|-----------|
| `myprovider` | `api_key` | `MYPROVIDER_API_KEY` |
| `my-provider` | `api_key` | `MY_PROVIDER_API_KEY` |
| `openai` | `base_url` | `OPENAI_BASE_URL` |
| `myprovider` | `api-key` | `MYPROVIDER_API_KEY` |

## Provider 类要求

### 必须实现的方法

所有 Provider 类必须继承自 `BaseProvider` 并实现以下抽象方法：

1. **`get_supported_model_types()`**: 返回支持的模型类型列表
2. **`get_credential_schema()`**: 返回凭据表单规则（JSON Schema）
3. **`get_config_schema()`**: 返回模型参数配置规则（JSON Schema）
4. **`validate_credentials()`**: 验证凭据是否有效
5. **`get_model_list()`**: 获取模型列表
6. **`create_model_instance()`**: 创建模型实例

### Provider 名称约定

- 使用小写字母
- 可以使用连字符 `-`（会自动转换为下划线）
- 建议使用简洁、描述性的名称
- 示例：`openaiapicompatible`, `aisafety`, `anthropic`

## 示例：完整的新 Provider

参考以下现有实现作为示例：

- **OpenAI API Compatible**: `OpenaiApiCompatible.py`
- **AiSafety**: `AiSafety.py`

这些文件展示了完整的实现模式。

## 自动发现机制

系统使用以下机制自动发现 Provider：

1. **扫描目录**: 自动扫描 `providers/` 目录下的所有 `.py` 文件
2. **导入模块**: 动态导入所有模块
3. **识别类**: 查找所有继承自 `BaseProvider` 的类
4. **注册实例**: 自动实例化并注册到 Factory

**注意**：
- 跳过 `__init__.py` 和 `base.py` 文件
- 如果模块导入失败，会记录警告但不中断程序
- Provider 类必须在模块顶层定义（不能嵌套在其他类中）

## 向后兼容

现有的硬编码配置仍然有效：

- `openaiapicompatible`: 优先使用 `openai_api_key` 和 `openai_base_url`
- `aisafety`: 优先使用 `aisafety_api_key` 和 `aisafety_base_url`

如果硬编码字段不存在，系统会自动尝试从环境变量读取（使用动态命名约定）。

## 调试技巧

### 检查 Provider 是否被发现

```python
from app.core.model.providers import get_all_provider_classes

classes = get_all_provider_classes()
for cls in classes:
    print(f"Found: {cls.__name__}")
```

### 检查 Provider 是否已注册

```python
from app.core.model.factory import get_factory

factory = get_factory()
providers = factory.get_all_providers()
for p in providers:
    print(f"Registered: {p['provider_name']} - {p['display_name']}")
```

### 检查凭据读取

```python
from app.core.settings import settings

creds = settings.get_provider_credentials("myprovider")
print(f"Credentials: {creds}")
```

### 检查环境变量名

```python
from app.core.settings import settings

env_var = settings.get_provider_env_var_name("my-provider", "api_key")
print(f"Environment variable: {env_var}")  # 输出: MY_PROVIDER_API_KEY
```

## 常见问题

### Q: Provider 没有被自动发现？

**A**: 检查以下几点：
1. 文件是否在 `providers/` 目录下？
2. 类名是否继承自 `BaseProvider`？
3. 类是否在模块顶层定义？
4. 是否有语法错误导致导入失败？

### Q: 环境变量没有被读取？

**A**: 检查以下几点：
1. 环境变量名是否符合命名约定？
2. 字段名是否与 `credential_schema.properties` 中的定义一致？
3. Provider 名称是否正确（大小写会被转换）？

### Q: 如何添加自定义字段？

**A**: 在 `get_credential_schema()` 的 `properties` 中添加字段定义，然后在 `.env` 中按照命名约定添加环境变量即可。

### Q: 支持哪些模型类型？

**A**: 当前支持的类型定义在 `ModelType` 枚举中：
- `CHAT`: 聊天模型
- `EMBEDDING`: 嵌入模型
- `RERANK`: 重排序模型
- `SPEECH_TO_TEXT`: 语音转文本
- `TEXT_TO_SPEECH`: 文本转语音
- `MODERATION`: 内容审核
