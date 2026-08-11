"""
MiniMax model provider implementation.

MiniMax exposes both an OpenAI-compatible endpoint and an Anthropic-compatible
endpoint. The China region (api.minimaxi.com) and the global region
(api.minimax.io) share the same API shape, so this provider rides on the
OpenAI-compatible base by default; a protocol_type credential field lets users
switch to the Anthropic-compatible base URL when they prefer that protocol.
"""

from typing import Any, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType
from .OpenaiApiCompatible import OpenAIAPICompatibleProvider, _format_validation_error

# region-specific OpenAI-compatible base URLs (path ends with /v1)
_REGION_BASE_URLS = {
    "global_en": "https://api.minimax.io/v1",
    "cn_zh": "https://api.minimaxi.com/v1",
}

# region-specific Anthropic-compatible base URLs
_REGION_ANTHROPIC_BASE_URLS = {
    "global_en": "https://api.minimax.io/anthropic",
    "cn_zh": "https://api.minimaxi.com/anthropic",
}

DEFAULT_REGION = "global_en"


class MiniMaxProvider(OpenAIAPICompatibleProvider):
    """MiniMax model provider (global and China regions)."""

    PROTOCOL_OPENAI = "openai"
    PROTOCOL_ANTHROPIC = "anthropic"

    # low-cost model used for credential validation
    VALIDATION_MODEL = "MiniMax-M2.7"

    PREDEFINED_CHAT_MODELS: List[Dict[str, Any]] = [
        {
            "name": "MiniMax-M3",
            "display_name": "MiniMax M3",
            "description": "MiniMax flagship multimodal model with a 1M context window, adaptive thinking, and prompt caching",
            "context_window": 1_000_000,
            "pricing_usd_per_million_tokens": {
                "input": 0.6,
                "output": 2.4,
                "cache_read": 0.12,
                "cache_write": None,
            },
            "input_modalities": ["text", "image", "video"],
            "thinking": ["adaptive", "disabled"],
        },
        {
            "name": "MiniMax-M2.7",
            "display_name": "MiniMax M2.7",
            "description": "MiniMax text model with always-on thinking and a 204K context window",
            "context_window": 204_800,
            "pricing_usd_per_million_tokens": {
                "input": 0.3,
                "output": 1.2,
                "cache_read": 0.06,
                "cache_write": 0.375,
            },
            "input_modalities": ["text"],
            "thinking": ["always_on"],
        },
    ]

    def __init__(self):
        BaseProvider.__init__(self, provider_name="minimax", display_name="MiniMax")

    def get_supported_model_types(self) -> List[ModelType]:
        """Return supported model types."""
        return [ModelType.CHAT]

    def _resolve_region(self, credentials: Dict[str, Any]) -> str:
        """Resolve the region from credentials, defaulting to the global region."""
        region = (credentials.get("region") or DEFAULT_REGION).strip().lower()
        if region not in _REGION_BASE_URLS:
            region = DEFAULT_REGION
        return region

    def _resolve_openai_base_url(self, credentials: Dict[str, Any]) -> str:
        """Return the OpenAI-compatible base URL, honoring an explicit override then the region."""
        explicit = (credentials.get("base_url") or "").strip()
        if explicit:
            return explicit
        return _REGION_BASE_URLS[self._resolve_region(credentials)]

    def _resolve_anthropic_base_url(self, credentials: Dict[str, Any]) -> str:
        """Return the Anthropic-compatible base URL, honoring an explicit override then the region."""
        explicit = (credentials.get("base_url") or "").strip()
        if explicit:
            return explicit
        return _REGION_ANTHROPIC_BASE_URLS[self._resolve_region(credentials)]

    def get_credential_schema(self) -> Dict[str, Any]:
        """Return credential form schema."""
        return {
            "type": "object",
            "properties": {
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "MiniMax API key (Bearer token)",
                    "required": True,
                },
                "region": {
                    "type": "string",
                    "title": "Region",
                    "description": "MiniMax API region",
                    "enum": ["global_en", "cn_zh"],
                    "enumNames": ["Global (api.minimax.io)", "China (api.minimaxi.com)"],
                    "default": DEFAULT_REGION,
                },
                "protocol_type": {
                    "type": "string",
                    "title": "Protocol Type",
                    "description": "Select API protocol (OpenAI-compatible or Anthropic-compatible)",
                    "enum": ["openai", "anthropic"],
                    "enumNames": ["OpenAI-compatible", "Anthropic-compatible"],
                    "default": "openai",
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "Optional API base URL override; leave empty to derive from the region",
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

    def _get_protocol(self, credentials: Dict[str, Any]) -> str:
        """Extract protocol type from credentials, default to openai."""
        return (credentials.get("protocol_type") or self.PROTOCOL_OPENAI).lower()

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate credentials."""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API key is required"

            protocol = self._get_protocol(credentials)

            model: BaseChatModel
            if protocol == self.PROTOCOL_ANTHROPIC:
                base_url = self._resolve_anthropic_base_url(credentials)
                kwargs: Dict[str, Any] = {
                    "model_name": self.VALIDATION_MODEL,
                    "api_key": api_key,
                    "max_tokens": 10,
                    "max_retries": 1,
                    "timeout": 10.0,
                    "anthropic_api_url": base_url,
                }
                model = ChatAnthropic(**kwargs)  # type: ignore[misc]
            else:
                base_url = self._resolve_openai_base_url(credentials)
                model = ChatOpenAI(
                    model=self.VALIDATION_MODEL,
                    api_key=api_key,
                    base_url=base_url,
                    max_retries=3,
                    timeout=5.0,
                )  # type: ignore[misc]

            response = await model.ainvoke("Hello, how are you?")
            if response and response.content:
                return True, None
            return False, "API call failed: no valid response received"
        except Exception as e:
            return False, _format_validation_error(e)

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Return the model list."""
        if model_type == ModelType.CHAT:
            return [{**model, "is_available": True} for model in self.PREDEFINED_CHAT_MODELS]
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
            raise ValueError(f"MiniMax provider does not support model type: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API key is required")

        protocol = self._get_protocol(credentials)
        model_parameters = model_parameters or {}

        if protocol == self.PROTOCOL_ANTHROPIC:
            base_url = self._resolve_anthropic_base_url(credentials)
            model_kwargs: Dict[str, Any] = {
                "model_name": model_name,
                "api_key": SecretStr(api_key),
                "streaming": True,
                "anthropic_api_url": base_url,
            }
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

        # default: OpenAI-compatible
        base_url = self._resolve_openai_base_url(credentials)
        model_kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key),
            "base_url": base_url,
            "streaming": True,
        }

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
