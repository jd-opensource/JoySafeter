"""
Ollama local model provider implementation.

Discover locally installed models via Ollama's REST API
and create runtime model instances through the OpenAI-compatible endpoint (/v1).
"""

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType

# Ollama REST API timeout (seconds)
_OLLAMA_API_TIMEOUT = 5.0


def _fetch_ollama_models(base_url: str) -> List[Dict[str, Any]]:
    """Call Ollama GET /api/tags to retrieve the local model list."""
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
                "description": f"Ollama — {', '.join(desc_parts)}" if desc_parts else "Ollama local model",
                "is_available": True,
            }
        )
    return models


class OllamaProvider(BaseProvider):
    """Ollama local model provider."""

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self):
        super().__init__(
            provider_name="ollama",
            display_name="Ollama (Local)",
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
                    "description": "Ollama server URL, default http://localhost:11434",
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
                        "description": "Controls output randomness, range 0-2",
                        "default": 0.7,
                        "minimum": 0,
                        "maximum": 2,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "title": "Max Tokens",
                        "description": "Maximum number of tokens to generate",
                        "default": None,
                        "minimum": 1,
                    },
                    "top_p": {
                        "type": "number",
                        "title": "Top P",
                        "description": "Nucleus sampling parameter, range 0-1",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "timeout": {
                        "type": "number",
                        "title": "Timeout",
                        "description": "Request timeout in seconds",
                        "default": 120.0,
                        "minimum": 1.0,
                    },
                    "max_retries": {
                        "type": "integer",
                        "title": "Max Retries",
                        "description": "Maximum number of retries",
                        "default": 2,
                        "minimum": 0,
                    },
                },
            }
        return None

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate credentials by checking Ollama API reachability."""
        base_url = credentials.get("base_url", self.DEFAULT_BASE_URL)
        try:
            models = _fetch_ollama_models(base_url)
            if models:
                return True, None
            return True, None  # service reachable but no models; still valid
        except httpx.ConnectError:
            return False, f"Cannot connect to Ollama service: {base_url}. Ensure Ollama is running."
        except httpx.TimeoutException:
            return False, f"Connection to Ollama service timed out: {base_url}"
        except Exception as e:
            return False, f"Ollama service validation failed: {e}"

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Dynamically fetch Ollama local model list. Return empty list when no credentials."""
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
            raise ValueError(f"Ollama provider does not support model type: {model_type}")

        base_url = credentials.get("base_url", self.DEFAULT_BASE_URL)
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
