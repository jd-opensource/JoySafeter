"""
Anthropic Claude provider implementation.
"""

from typing import Any, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class AnthropicProvider(BaseProvider):
    """Anthropic provider."""

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
            "description": "Anthropic's latest and most intelligent model, excels at advanced reasoning and coding",
        },
        {
            "name": "claude-3-5-sonnet-20241022",
            "display_name": "Claude 3.5 Sonnet",
            "description": "Smart and fast model, well-suited for a wide range of tasks",
        },
        {
            "name": "claude-3-5-haiku-20241022",
            "display_name": "Claude 3.5 Haiku",
            "description": "Fastest model in its class, ideal for latency-sensitive applications",
        },
        {
            "name": "claude-3-opus-20240229",
            "display_name": "Claude 3 Opus",
            "description": "Previous-generation flagship model, strong at highly complex tasks",
        },
    ]

    def __init__(self):
        super().__init__(provider_name="anthropic", display_name="Anthropic (Claude)")

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
                    "description": "Anthropic API key",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API base URL (only needed for custom proxies)",
                    "required": False,
                },
            },
            "required": ["api_key"],
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
                        "description": "Controls output randomness, range 0-1",
                        "default": 1.0,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "max_tokens": {
                        "type": "integer",
                        "title": "Max Tokens",
                        "description": "Maximum number of tokens to generate",
                        "default": 4096,
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

            # attempt an API call
            response = await model.ainvoke("Hello")
            if response and response.content:
                return True, None
            else:
                return False, "API call failed: no valid response received"
        except Exception as e:
            msg = str(e)
            return False, f"Credential validation failed: {msg}"

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
        """Create a model instance."""
        if model_type != ModelType.CHAT:
            raise ValueError(f"Anthropic provider does not support model type: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API key is required")

        base_url = credentials.get("base_url")

        # build model kwargs
        model_kwargs: Dict[str, Any] = {
            "model_name": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,
        }

        if base_url:
            model_kwargs["anthropic_api_url"] = base_url

        # apply model parameters
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
