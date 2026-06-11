"""
Google Gemini provider implementation.
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType


class GeminiProvider(BaseProvider):
    """Google Gemini provider."""

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
            "description": "Google's strongest reasoning model with a massive context window",
        },
        {
            "name": "gemini-2.5-flash",
            "display_name": "Gemini 2.5 Flash",
            "description": "Google's fast, lightweight multimodal workhorse for high-frequency and general tasks",
        },
        {
            "name": "gemini-1.5-pro",
            "display_name": "Gemini 1.5 Pro",
            "description": "Google's previous-generation flagship model",
        },
        {
            "name": "gemini-1.5-flash",
            "display_name": "Gemini 1.5 Flash",
            "description": "Google's previous-generation fast model",
        },
    ]

    def __init__(self):
        super().__init__(provider_name="gemini", display_name="Google Gemini")

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
                    "description": "Google Gemini API key",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API base URL (configure if using a proxy)",
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
                        "default": 0.95,
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "top_k": {
                        "type": "integer",
                        "title": "Top K",
                        "description": "Top-K sampling parameter",
                        "default": 40,
                        "minimum": 1,
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
            raise ValueError(f"Gemini provider does not support model type: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API key is required")

        base_url = credentials.get("base_url")

        # build model kwargs
        model_kwargs: Dict[str, Any] = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "streaming": True,
        }

        if base_url:
            model_kwargs["transport"] = "rest"
            model_kwargs["client_options"] = {"api_endpoint": base_url}

        # apply model parameters
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
