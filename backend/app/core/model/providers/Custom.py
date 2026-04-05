"""
Custom model provider: supports user-selected protocol (OpenAI / Anthropic / Google Gemini) with custom models.
"""

from typing import Any, Dict, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from .base import BaseProvider, ModelType

# temporary model names used during credential validation (connectivity test only)
_VALIDATE_MODEL_OPENAI = "gpt-4o-mini"
_VALIDATE_MODEL_ANTHROPIC = "claude-3-5-haiku-20241022"
_VALIDATE_MODEL_GEMINI = "gemini-1.5-flash"


class CustomProvider(BaseProvider):
    """Custom model provider: user selects a protocol (OpenAI / Anthropic / Google Gemini) and adds model names."""

    PROTOCOL_OPENAI = "openai"
    PROTOCOL_ANTHROPIC = "anthropic"
    PROTOCOL_GEMINI = "gemini"

    def __init__(self):
        super().__init__(provider_name="custom", display_name="Custom Model", is_template=True, provider_type="custom")

    def get_supported_model_types(self) -> List[ModelType]:
        """Return supported model types."""
        return [ModelType.CHAT]

    def get_credential_schema(self) -> Dict[str, Any]:
        """Return credential form schema."""
        return {
            "type": "object",
            "properties": {
                "protocol_type": {
                    "type": "string",
                    "title": "Protocol Type",
                    "description": "Select API protocol",
                    "enum": ["openai", "anthropic", "gemini"],
                    "enumNames": ["OpenAI", "Anthropic (Claude)", "Google Gemini"],
                },
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "API key",
                    "required": True,
                },
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "description": "API base URL (optional; for custom endpoints, OpenAI-compatible URLs should end with /v1)",
                    "required": False,
                },
            },
            "required": ["protocol_type", "api_key"],
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

    async def validate_credentials(
        self, credentials: Dict[str, Any], model_name: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        """Validate credentials using the client for the selected protocol. model_name specifies the model for validation; defaults to each protocol's built-in model."""
        try:
            api_key = credentials.get("api_key")
            if not api_key:
                return False, "API key is required"

            protocol = self._get_protocol(credentials)
            base_url = credentials.get("base_url") or ""
            validate_model = (model_name or "").strip()

            if protocol == self.PROTOCOL_OPENAI:
                effective_model = validate_model or _VALIDATE_MODEL_OPENAI
                model: BaseChatModel = ChatOpenAI(
                    model=effective_model,
                    api_key=api_key,
                    base_url=base_url or None,
                    max_retries=3,
                    timeout=5.0,
                )  # type: ignore[misc]
            elif protocol == self.PROTOCOL_ANTHROPIC:
                effective_model = validate_model or _VALIDATE_MODEL_ANTHROPIC
                kwargs: Dict[str, Any] = {
                    "model": effective_model,
                    "api_key": api_key,
                    "max_retries": 1,
                    "timeout": 10.0,
                }
                if base_url:
                    kwargs["anthropic_api_url"] = base_url
                model = ChatAnthropic(**kwargs)  # type: ignore[misc]
            elif protocol == self.PROTOCOL_GEMINI:
                effective_model = validate_model or _VALIDATE_MODEL_GEMINI
                kwargs = {
                    "model": effective_model,
                    "api_key": api_key,
                    "max_retries": 1,
                    "timeout": 10.0,
                }
                if base_url:
                    kwargs["transport"] = "rest"
                    kwargs["client_options"] = {"api_endpoint": base_url}
                model = ChatGoogleGenerativeAI(**kwargs)  # type: ignore[misc]
            else:
                return False, f"Unsupported protocol type: {protocol}"

            response = await model.ainvoke("Hello")
            if response and response.content:
                return True, None
            return False, "API call failed: no valid response received"
        except Exception as e:
            return False, f"Credential validation failed: {str(e)}"

    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Custom models have no predefined list; users add them dynamically."""
        return []

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """No predefined models."""
        return []

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        """Create a LangChain model instance based on protocol_type."""
        if model_type != ModelType.CHAT:
            raise ValueError(f"Custom provider does not support model type: {model_type}")

        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("API key is required")

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

        raise ValueError(f"Unsupported protocol type: {protocol}")

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        """Test model output."""
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
