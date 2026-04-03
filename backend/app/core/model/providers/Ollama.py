"""
Ollama 本地模型供应商实现

通过 Ollama 的 REST API 自动发现本地已安装的模型，
并通过 OpenAI 兼容端点 (/v1) 创建运行时模型实例。
"""

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType

# Ollama REST API 超时（秒）
_OLLAMA_API_TIMEOUT = 5.0


def _fetch_ollama_models(base_url: str) -> List[Dict[str, Any]]:
    """调用 Ollama GET /api/tags 获取本地模型列表。"""
    url = f"{base_url.rstrip('/')}/api/tags"
    with httpx.Client(timeout=_OLLAMA_API_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

    models: List[Dict[str, Any]] = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if not name:
            continue
        details = m.get("details", {})
        family = details.get("family", "")
        param_size = details.get("parameter_size", "")
        desc_parts = [p for p in [family, param_size] if p]
        models.append(
            {
                "name": name,
                "display_name": name,
                "description": f"Ollama — {', '.join(desc_parts)}" if desc_parts else "Ollama 本地模型",
                "is_available": True,
            }
        )
    return models


class OllamaProvider(BaseProvider):
    """Ollama 本地模型供应商"""

    def __init__(self):
        super().__init__(
            provider_name="ollama",
            display_name="Ollama (本地部署)",
            is_template=False,
            provider_type="system",
        )

    def get_supported_model_types(self) -> List[ModelType]:
        return [ModelType.CHAT]

    def get_credential_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "base_url": {
                    "type": "string",
                    "title": "Ollama Server URL",
                    "description": "Ollama 服务地址，默认 http://localhost:11434",
                    "default": "http://localhost:11434",
                    "required": True,
                },
            },
            "required": ["base_url"],
        }

    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        if model_type == ModelType.CHAT:
            return {
                "type": "object",
                "properties": {
                    "temperature": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "控制输出的随机性，范围0-2",
                        "default": 0.7,
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
                    "timeout": {
                        "type": "number",
                        "title": "Timeout",
                        "description": "请求超时时间（秒）",
                        "default": 120.0,
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
        """通过调用 Ollama API 检测服务是否可达。"""
        base_url = credentials.get("base_url", "http://localhost:11434")
        try:
            models = _fetch_ollama_models(base_url)
            if models:
                return True, None
            return True, None  # 服务可达但无模型，仍视为有效
        except httpx.ConnectError:
            return False, f"无法连接到 Ollama 服务：{base_url}，请确认 Ollama 已启动"
        except httpx.TimeoutException:
            return False, f"连接 Ollama 服务超时：{base_url}"
        except Exception as e:
            return False, f"Ollama 服务验证失败：{e}"

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """动态获取 Ollama 本地模型列表。无凭据时返回空列表。"""
        if model_type != ModelType.CHAT:
            return []
        if not credentials or not credentials.get("base_url"):
            return []
        try:
            return _fetch_ollama_models(credentials["base_url"])
        except Exception:
            return []

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        return []

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        if model_type != ModelType.CHAT:
            raise ValueError(f"Ollama 供应商不支持模型类型: {model_type}")

        base_url = credentials.get("base_url", "http://localhost:11434")
        openai_base = f"{base_url.rstrip('/')}/v1"

        model_kwargs: Dict[str, Any] = {
            "model": model_name,
            "api_key": SecretStr("ollama"),
            "base_url": openai_base,
            "streaming": True,
        }

        if model_parameters:
            if "temperature" in model_parameters:
                model_kwargs["temperature"] = model_parameters["temperature"]
            if "max_tokens" in model_parameters:
                model_kwargs["max_completion_tokens"] = model_parameters["max_tokens"]
            if "top_p" in model_parameters:
                model_kwargs["top_p"] = model_parameters["top_p"]
            if "timeout" in model_parameters:
                model_kwargs["timeout"] = model_parameters["timeout"]
            if "max_retries" in model_parameters:
                model_kwargs["max_retries"] = model_parameters["max_retries"]

        return ChatOpenAI(**model_kwargs)  # type: ignore[arg-type,misc]

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        instance = self.create_model_instance(
            model_name=instance_dict["model_name"],
            model_type=instance_dict["model_type"],
            credentials=instance_dict["credentials"],
            model_parameters=instance_dict.get("model_parameters"),
        )
        response = await instance.ainvoke(input)
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                return " ".join(str(item) for item in content)
        return str(response) if response else ""
