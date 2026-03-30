"""
Anthropic Claude 供应商实现
"""

from typing import Any, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class AnthropicProvider(BaseProvider):
    """Anthropic 供应商"""

    PREDEFINED_CHAT_MODELS = [
        {
            "name": "claude-4-6-sonnet-thinking",
            "display_name": "Claude Sonnet 4.6 (Thinking)",
            "description": "Claude Sonnet 4.6 with enhanced thinking and reasoning capabilities",
        },
        {
            "name": "claude-4-6-opus-thinking",
            "display_name": "Claude Opus 4.6 (Thinking)",
            "description": "Claude Opus 4.6 with enhanced thinking and reasoning capabilities",
        },
        {
            "name": "claude-3-7-sonnet-20250219",
            "display_name": "Claude 3.7 Sonnet",
            "description": "Anthropic最新且最智能的模型，擅长高级推理和编程",
        },
        {
            "name": "claude-3-5-sonnet-20241022",
            "display_name": "Claude 3.5 Sonnet",
            "description": "智能且快速的模型，非常适合各种任务",
        },
        {
            "name": "claude-3-5-haiku-20241022",
            "display_name": "Claude 3.5 Haiku",
            "description": "同类中最快的模型，适合需要速度的应用",
        },
        {
            "name": "claude-3-opus-20240229",
            "display_name": "Claude 3 Opus",
            "description": "在处理高度复杂的任务时表现强大的旧版旗舰模型",
        },
    ]

    def __init__(self):
        super().__init__(provider_name="anthropic", display_name="Anthropic (Claude)")

    def get_supported_model_types(self) -> List[ModelType]:
        """获取支持的模型类型"""
        return [ModelType.CHAT]

    def get_credential_schema(self) -> Dict[str, Any]:
        """获取凭据表单规则"""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "Anthropic API密钥",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API基础URL (仅自定义代理时需要设置)",
                    "required": False,
                },
            },
            "required": ["api_key"],
        }

    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """获取模型参数配置规则"""
        if model_type == ModelType.CHAT:
            return {
                "type": "object",
                "properties": {
                    "temperature": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "控制输出的随机性，范围0-1",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "title": "Max Tokens",
                        "description": "生成的最大token数",
                        "default": 4096,
                        "minimum": 1,
                    },
                    "top_p": {
                        "type": "number",
                        "title": "Top P",
                        "description": "核采样参数，范围0-1",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "timeout": {
                        "type": "number",
                        "title": "Timeout",
                        "description": "请求超时时间（秒）",
                        "default": 60.0,
                        "minimum": 1.0,
                    },
                    "max_retries": {
                        "type": "integer",
                        "title": "Max Retries",
                        "description": "最大重试次数",
                        "default": 2,
                        "minimum": 0,
                    },
                },
            }
        return None

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证凭据"""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API Key不能为空"

            base_url = credentials.get("base_url")

            # 创建一个临时模型实例进行测试
            kwargs: Dict[str, Any] = {
                "model_name": self.PREDEFINED_CHAT_MODELS[0]["name"],
                "api_key": api_key,
                "max_tokens": 10,
                "max_retries": 1,
                "timeout": 10.0,
            }
            if base_url:
                kwargs["anthropic_api_url"] = base_url

            model = ChatAnthropic(**kwargs)  # type: ignore[misc]

            # 尝试调用API
            response = await model.ainvoke("Hello")
            if response and response.content:
                return True, None
            else:
                return False, "API调用失败：未收到有效响应"
        except Exception as e:
            msg = str(e)
            return False, f"凭据验证失败：{msg}"

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
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
            raise ValueError(f"Anthropic 供应商不支持模型类型: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API Key不能为空")

        base_url = credentials.get("base_url")

        # 构建模型参数
        model_kwargs: Dict[str, Any] = {
            "model_name": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,
        }

        if base_url:
            model_kwargs["anthropic_api_url"] = base_url

        # 添加模型参数
        if model_parameters:
            if "temperature" in model_parameters:
                model_kwargs["temperature"] = model_parameters["temperature"]
            if "max_tokens" in model_parameters:
                model_kwargs["max_tokens"] = model_parameters["max_tokens"]
            if "top_p" in model_parameters:
                model_kwargs["top_p"] = model_parameters["top_p"]
            if "timeout" in model_parameters:
                model_kwargs["default_request_timeout"] = model_parameters["timeout"]
            if "max_retries" in model_parameters:
                model_kwargs["max_retries"] = model_parameters["max_retries"]

        return ChatAnthropic(**model_kwargs)  # type: ignore[arg-type,misc]
