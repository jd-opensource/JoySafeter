"""
自定义模型供应商实现：支持用户选择协议类型（OpenAI / Anthropic / Google Gemini）并添加自定义模型。
"""

from typing import Any, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType

# 凭据验证时使用的临时模型名（仅用于测试连通性）
_VALIDATE_MODEL_OPENAI = "gpt-4o-mini"
_VALIDATE_MODEL_ANTHROPIC = "claude-3-5-haiku-20241022"
_VALIDATE_MODEL_GEMINI = "gemini-1.5-flash"


class CustomProvider(BaseProvider):
    """自定义模型供应商：用户可选协议（OpenAI / Anthropic / Google Gemini）并添加具体模型名。"""

    PROTOCOL_OPENAI = "openai"
    PROTOCOL_ANTHROPIC = "anthropic"
    PROTOCOL_GEMINI = "gemini"

    def __init__(self):
        super().__init__(provider_name="custom", display_name="自定义模型", is_template=True, provider_type="custom")

    def get_supported_model_types(self) -> List[ModelType]:
        """获取支持的模型类型"""
        return [ModelType.CHAT]

    def get_credential_schema(self) -> Dict[str, Any]:
        """获取凭据表单规则"""
        return {
            "type": "object",
            "properties": {
                "protocol_type": {
                    "type": "string",
                    "title": "协议类型",
                    "description": "选择 API 协议",
                    "enum": ["openai", "anthropic", "gemini"],
                    "enumNames": ["OpenAI", "Anthropic (Claude)", "Google Gemini"],
                },
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "API 密钥",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API 基础 URL（可选，自定义端点时填写，OpenAI 兼容请以 /v1 结尾）",
                    "required": False,
                },
            },
            "required": ["protocol_type", "api_key"],
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

    def _get_protocol(self, credentials: Dict[str, Any]) -> str:
        """从凭据中取协议类型，缺省为 openai"""
        return (credentials.get("protocol_type") or self.PROTOCOL_OPENAI).lower()

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """根据协议类型使用对应客户端验证凭据。若凭据中含 _validate_model，则用该模型名做验证（一步添加自定义模型时传入）。"""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API Key 不能为空"

            protocol = self._get_protocol(credentials)
            base_url = credentials.get("base_url") or ""

            # 一步添加自定义模型时传入待验证的模型名，用该模型做连通性测试，避免固定模型在部分端点不可用导致误报「验证未通过」
            validate_model = credentials.get("_validate_model") or ""
            validate_model = validate_model.strip() if isinstance(validate_model, str) else ""

            if protocol == self.PROTOCOL_OPENAI:
                model_name = validate_model or _VALIDATE_MODEL_OPENAI
                model = ChatOpenAI(
                    model=model_name,
                    api_key=api_key,
                    base_url=base_url or None,
                    max_retries=3,
                    timeout=5.0,
                )  # type: ignore[misc]
            elif protocol == self.PROTOCOL_ANTHROPIC:
                model_name = validate_model or _VALIDATE_MODEL_ANTHROPIC
                kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "api_key": api_key,
                    "max_retries": 1,
                    "timeout": 10.0,
                }
                if base_url:
                    kwargs["anthropic_api_url"] = base_url
                model = ChatAnthropic(**kwargs)  # type: ignore[misc]
            elif protocol == self.PROTOCOL_GEMINI:
                model_name = validate_model or _VALIDATE_MODEL_GEMINI
                kwargs = {
                    "model": model_name,
                    "api_key": api_key,
                    "max_retries": 1,
                    "timeout": 10.0,
                }
                if base_url:
                    kwargs["transport"] = "rest"
                    kwargs["client_options"] = {"api_endpoint": base_url}
                model = ChatGoogleGenerativeAI(**kwargs)  # type: ignore[misc]
            else:
                return False, f"不支持的协议类型: {protocol}"

            response = await model.ainvoke("Hello")
            if response and response.content:
                return True, None
            return False, "API 调用失败：未收到有效响应"
        except Exception as e:
            return False, f"凭据验证失败：{str(e)}"

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """自定义模型无预定义列表，由用户通过「添加自定义模型」动态添加"""
        return []

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """无预定义模型"""
        return []

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        """根据 protocol_type 创建对应协议的 LangChain 模型实例"""
        if model_type != ModelType.CHAT:
            raise ValueError(f"自定义模型供应商不支持模型类型: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API Key 不能为空")

        protocol = self._get_protocol(credentials)
        base_url = credentials.get("base_url")
        model_parameters = model_parameters or {}

        if protocol == self.PROTOCOL_OPENAI:
            model_kwargs: Dict[str, Any] = {
                "model": model_name,
                "api_key": SecretStr(api_key),
                "streaming": True,
            }
            if base_url:
                model_kwargs["base_url"] = base_url
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
            return ChatOpenAI(**model_kwargs)  # type: ignore[arg-type,call-overload,misc]

        if protocol == self.PROTOCOL_ANTHROPIC:
            model_kwargs = {
                "model_name": model_name,
                "api_key": SecretStr(api_key),
                "streaming": True,
            }
            if base_url:
                model_kwargs["anthropic_api_url"] = base_url
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

        if protocol == self.PROTOCOL_GEMINI:
            model_kwargs = {
                "model": model_name,
                "api_key": SecretStr(api_key),
                "streaming": True,
            }
            if base_url:
                model_kwargs["transport"] = "rest"
                model_kwargs["client_options"] = {"api_endpoint": base_url}
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

        raise ValueError(f"不支持的协议类型: {protocol}")

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        """测试模型输出"""
        model_type = instance_dict.get("model_type", ModelType.CHAT)
        if isinstance(model_type, str):
            model_type = ModelType(model_type)
        instance = self.create_model_instance(
            model_name=instance_dict["model_name"],
            model_type=model_type,
            credentials=instance_dict["credentials"],
            model_parameters=instance_dict.get("model_parameters"),
        )
        response = await instance.ainvoke(input)
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(str(item) for item in content)
        return str(response) if response else ""
