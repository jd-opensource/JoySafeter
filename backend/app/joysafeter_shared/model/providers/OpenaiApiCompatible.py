"""
OpenAI API-compatible provider implementation.
"""

import ast
import json
from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType


def _format_validation_error(exc: Exception) -> str:
    """Parse message/cause from upstream exception and return a user-friendly error."""
    raw = str(exc)
    # e.g. "Error code: 400 - {'error': {'message': '...', 'cause': '...'}, ...}}"
    if " - " in raw:
        payload = raw.split(" - ", 1)[1].strip()
        try:
            # upstream may return single-quoted dicts; try JSON first
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                # single-quoted dict fallback via ast
                data = ast.literal_eval(payload) if payload.startswith("{") else {}
            err = data.get("error") if isinstance(data, dict) else None
            if isinstance(err, dict):
                msg = err.get("message") or err.get("cause")
                cause = err.get("cause") if err.get("message") else None
                parts: List[str] = []
                if msg is not None:
                    parts.append(str(msg))
                if cause and cause != msg:
                    parts.append(f"（{cause}）")
                if parts:
                    return "Credential validation failed: " + " ".join(parts)
        except Exception:
            pass
    return f"Credential validation failed: {raw}"


class OpenAIAPICompatibleProvider(BaseProvider):
    """OpenAI API-compatible provider."""

    # low-cost model used for credential validation
    VALIDATION_MODEL = "gpt-4o-mini"

    # predefined chat models (OpenAI official standard models)
    PREDEFINED_CHAT_MODELS = [
        {
            "name": "o3",
            "display_name": "o3",
            "description": "OpenAI's strongest reasoning model for complex multi-step tasks",
        },
        {
            "name": "o4-mini",
            "display_name": "o4-mini",
            "description": "OpenAI's cost-effective reasoning model, fast and affordable",
        },
        {
            "name": "gpt-4.1",
            "display_name": "GPT-4.1",
            "description": "OpenAI flagship model, strong at coding and instruction following",
        },
        {
            "name": "gpt-4.1-mini",
            "display_name": "GPT-4.1 Mini",
            "description": "Lightweight GPT-4.1 variant balancing performance and cost",
        },
        {
            "name": "gpt-4.1-nano",
            "display_name": "GPT-4.1 Nano",
            "description": "Fastest and most economical GPT-4.1 variant for simple tasks",
        },
        {
            "name": "gpt-4o",
            "display_name": "GPT-4o",
            "description": "OpenAI multimodal model supporting text, image, and audio",
        },
        {
            "name": "gpt-4o-mini",
            "display_name": "GPT-4o Mini",
            "description": "Lightweight GPT-4o variant, fast and economical",
        },
        {
            "name": "gpt-4.5-preview",
            "display_name": "GPT-4.5 Preview",
            "description": "OpenAI's largest model preview, excels at creative writing and conversation",
        },
        {
            "name": "o3-mini",
            "display_name": "o3-mini",
            "description": "OpenAI's small reasoning model, strong in STEM domains",
        },
        {
            "name": "o1",
            "display_name": "o1",
            "description": "OpenAI reasoning model, excels at science, math, and coding",
        },
        {
            "name": "o1-mini",
            "display_name": "o1-mini",
            "description": "Lightweight o1 variant with faster reasoning",
        },
    ]

    def __init__(self):
        super().__init__(
            provider_name="openaiapicompatible",
            display_name="OpenAI",
            is_template=False,
            provider_type="system",
        )

    def get_supported_model_types(self) -> List[ModelType]:
        """Return supported model types."""
        return [ModelType.CHAT]

    def get_credential_schema(self) -> Dict[str, Any]:
        """Return credential form schema."""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "OpenAI API key",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API base URL (for custom endpoints), path should end with /v1",
                    "required": True,
                },
            },
            "required": ["api_key", "base_url"],
        }

    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """Return model parameter config schema."""
        if model_type == ModelType.CHAT:
            return {
                "type": "object",
                "properties": {
                    "temperature": {
                        "type": "number",
                        "title": "Temperature",
                        "description": "Controls output randomness, range 0-2",
                        "default": 1.0,
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
                    "frequency_penalty": {
                        "type": "number",
                        "title": "Frequency Penalty",
                        "description": "Frequency penalty, range -2.0 to 2.0",
                        "default": 0.0,
                        "minimum": -2.0,
                        "maximum": 2.0,
                    },
                    "presence_penalty": {
                        "type": "number",
                        "title": "Presence Penalty",
                        "description": "Presence penalty, range -2.0 to 2.0",
                        "default": 0.0,
                        "minimum": -2.0,
                        "maximum": 2.0,
                    },
                    "timeout": {
                        "type": "number",
                        "title": "Timeout",
                        "description": "Request timeout in seconds",
                        "default": 60.0,
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
        """Validate credentials."""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API key is required"

            base_url = credentials.get("base_url")

            # create a temporary model instance for testing
            model = ChatOpenAI(
                model=self.VALIDATION_MODEL,
                api_key=api_key,
                base_url=base_url,
                max_retries=3,
                timeout=5.0,
            )  # type: ignore[misc]

            # attempt an API call
            response = await model.ainvoke("Hello, how are you?")
            if response and response.content:
                return True, None
            else:
                return False, "API call failed: no valid response received"
        except Exception as e:
            return False, _format_validation_error(e)

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Return the model list."""
        if model_type == ModelType.CHAT:
            models = []
            for model in self.PREDEFINED_CHAT_MODELS:
                model_info = {
                    "name": model["name"],
                    "display_name": model["display_name"],
                    "description": model["description"],
                    "is_available": True,  # predefined models are always available
                }
                models.append(model_info)
            return models
        return []

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """Return predefined model list."""
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
        """Create a model instance."""
        if model_type != ModelType.CHAT:
            raise ValueError(f"OpenAI provider does not support model type: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API key is required")

        base_url = credentials.get("base_url")

        # build model kwargs
        model_kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,  # streaming enabled by default
        }

        if base_url:
            model_kwargs["base_url"] = base_url

        # apply model parameters
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
        """Test model output."""

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
