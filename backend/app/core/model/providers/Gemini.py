"""
Google Gemini 供应商实现
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class GeminiProvider(BaseProvider):
    """Google Gemini 供应商"""

    PREDEFINED_CHAT_MODELS = [
        {
            "name": "gemini-3.1-pro-high",
            "display_name": "Gemini 3.1 Pro (High)",
            "description": "Google Gemini 3.1 Pro (High Compute)",
        },
        {
            "name": "gemini-3.1-pro-low",
            "display_name": "Gemini 3.1 Pro (Low)",
            "description": "Google Gemini 3.1 Pro (Low Compute)",
        },
        {
            "name": "gemini-3-flash",
            "display_name": "Gemini 3 Flash",
            "description": "Google Gemini 3 Flash",
        },
        {
            "name": "gemini-2.5-pro",
            "display_name": "Gemini 2.5 Pro",
            "description": "Google 最强推理与复杂任务模型，拥有巨大的上下文窗口",
        },
        {
            "name": "gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "description": "Google 快速、轻量多模态主力模型，专为多频率和通用任务构建",
        },
        {
            "name": "gemini-1.5-pro",
            "display_name": "Gemini 1.5 Pro",
            "description": "Google 上一代旗舰模型",
        },
        {
            "name": "gemini-1.5-flash",
            "display_name": "Gemini 1.5 Flash",
            "description": "Google 上一代快速模型",
        },
    ]

    def __init__(self):
        super().__init__(provider_name="gemini", display_name="Google Gemini")

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
                    "description": "Google Gemini API密钥",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API基础URL (如果使用代理则配置)",
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
                        "description": "控制输出的随机性，范围0-2",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 2,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "title": "Max Tokens",
                        "description": "生成的最大token数",
                        "default": None,
                        "minimum": 1,
                    },
                    "top_p": {
                        "type": "number",
                        "title": "Top P",
                        "description": "核采样参数，范围0-1",
                        "default": 0.95,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "top_k": {
                        "type": "integer",
                        "title": "Top K",
                        "description": "Top-K 采样参数",
                        "default": 40,
                        "minimum": 1,
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
                "model": self.PREDEFINED_CHAT_MODELS[0]["name"],
                "api_key": api_key,
                "max_retries": 1,
                "timeout": 10.0,
            }
            # Custom Transport/Client may be needed for Gemini proxying but kwargs usually support it
            if base_url:
                kwargs["transport"] = "rest"
                kwargs["client_options"] = {"api_endpoint": base_url}

            model = ChatGoogleGenerativeAI(**kwargs)  # type: ignore[misc]

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
            raise ValueError(f"Gemini 供应商不支持模型类型: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API Key不能为空")

        base_url = credentials.get("base_url")

        # 构建模型参数
        model_kwargs: Dict[str, Any] = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,
        }

        if base_url:
            model_kwargs["transport"] = "rest"
            model_kwargs["client_options"] = {"api_endpoint": base_url}

        # 添加模型参数
        if model_parameters:
            if "temperature" in model_parameters:
                model_kwargs["temperature"] = model_parameters["temperature"]
            if "max_tokens" in model_parameters:
                model_kwargs["max_output_tokens"] = model_parameters["max_tokens"]
            if "top_p" in model_parameters:
                model_kwargs["top_p"] = model_parameters["top_p"]
            if "top_k" in model_parameters:
                model_kwargs["top_k"] = model_parameters["top_k"]
            if "timeout" in model_parameters:
                model_kwargs["timeout"] = model_parameters["timeout"]
            if "max_retries" in model_parameters:
                model_kwargs["max_retries"] = model_parameters["max_retries"]

        return ChatGoogleGenerativeAI(**model_kwargs)  # type: ignore[arg-type,misc]
