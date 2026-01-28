"""
OpenAI供应商实现
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class OpenAIAPICompatibleProvider(BaseProvider):
    """OpenAI供应商"""

    # 预定义的Chat模型列表
    PREDEFINED_CHAT_MODELS = [
        {
            "name": "DeepSeek-V3.2",
            "display_name": "DeepSeek-Chat",
            "description": "DeepSeek - 最新的对话模型",
        },
        {
            "name": "DeepSeek-R1-0528",
            "display_name": "DeepSeek-R1",
            "description": "DeepSeek - 最新的推理模型",
        },
        {
            "name": "gpt-5",
            "display_name": "GPT-5",
            "description": "OpenAi - 最新的模型",
        },
        {
            "name": "Qwen3-Coder",
            "display_name": "Qwen3-Coder",
            "description": "Qwen 最新的代码模型",
        },
    ]

    def __init__(self):
        super().__init__(provider_name="openaiapicompatible", display_name="OpenAI's API Compatible")

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
                    "description": "OpenAI API密钥",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API基础URL（用于自定义端点）",
                    "required": True,
                },
            },
            "required": ["api_key", "base_url"],
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
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "frequency_penalty": {
                        "type": "number",
                        "title": "Frequency Penalty",
                        "description": "频率惩罚，范围-2.0到2.0",
                        "default": 0.0,
                        "minimum": -2.0,
                        "maximum": 2.0,
                    },
                    "presence_penalty": {
                        "type": "number",
                        "title": "Presence Penalty",
                        "description": "存在惩罚，范围-2.0到2.0",
                        "default": 0.0,
                        "minimum": -2.0,
                        "maximum": 2.0,
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
            model = ChatOpenAI(
                model=self.PREDEFINED_CHAT_MODELS[0]["name"],
                api_key=api_key,
                base_url=base_url,
                max_retries=3,
                timeout=5.0,
            )  # type: ignore[misc]

            # 尝试调用API
            response = await model.ainvoke("Hello, how are you?")
            if response and response.content:
                return True, None
            else:
                return False, "API调用失败：未收到有效响应"
        except Exception as e:
            return False, f"凭据验证失败：{str(e)}"

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
                    "is_available": True,  # 预定义模型总是可用
                }
                models.append(model_info)
            return models
        return []

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """获取预定义模型列表"""
        if model_type == ModelType.CHAT:
            return self.PREDEFINED_CHAT_MODELS.copy()
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
            raise ValueError(f"OpenAI供应商不支持模型类型: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API Key不能为空")

        base_url = credentials.get("base_url")

        # 构建模型参数
        model_kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,  # 默认启用流式输出
        }

        if base_url:
            model_kwargs["base_url"] = base_url

        # 添加模型参数
        if model_parameters:
            if "temperature" in model_parameters:
                model_kwargs["temperature"] = model_parameters["temperature"]
            if "max_tokens" in model_parameters:
                model_kwargs["max_completion_tokens"] = model_parameters["max_tokens"]
            if "top_p" in model_parameters:
                model_kwargs["top_p"] = model_parameters["top_p"]
            if "frequency_penalty" in model_parameters:
                model_kwargs["frequency_penalty"] = model_parameters["frequency_penalty"]
            if "presence_penalty" in model_parameters:
                model_kwargs["presence_penalty"] = model_parameters["presence_penalty"]
            if "timeout" in model_parameters:
                model_kwargs["timeout"] = model_parameters["timeout"]
            if "max_retries" in model_parameters:
                model_kwargs["max_retries"] = model_parameters["max_retries"]

        return ChatOpenAI(**model_kwargs)  # type: ignore[arg-type,misc]

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        """测试模型输出"""

        instance = self.create_model_instance(
            model_name=instance_dict["model_name"],
            model_type=instance_dict["model_type"],
            credentials=instance_dict["credentials"],
            model_parameters=instance_dict["model_parameters"],
        )
        response = await instance.ainvoke(input)
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                return " ".join(str(item) for item in content)
        return str(response) if response else ""
