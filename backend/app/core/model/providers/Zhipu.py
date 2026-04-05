"""
Zhipu (GLM) model provider implementation.
"""

from typing import Any, Dict, Optional

from langchain_core.language_models import BaseChatModel

from .base import BaseProvider, ModelType
from .OpenaiApiCompatible import OpenAIAPICompatibleProvider


class ZhipuProvider(OpenAIAPICompatibleProvider):
    """Zhipu (GLM) model provider."""

    VALIDATION_MODEL = "glm-4-flash"

    PREDEFINED_CHAT_MODELS = [
        {
            "name": "glm-4.7",
            "display_name": "GLM-4.7",
            "description": "Zhipu's latest flagship model",
        },
        {
            "name": "glm-5",
            "display_name": "GLM-5",
            "description": "Zhipu's next-generation flagship base model, built for Agentic Engineering with reliable productivity on complex system engineering and long-horizon agent tasks",
        },
        {
            "name": "glm-4-0520",
            "display_name": "GLM-4",
            "description": "Zhipu general-purpose model",
        },
        {
            "name": "glm-4-air",
            "display_name": "GLM-4 Air",
            "description": "Cost-effective workhorse model",
        },
        {
            "name": "glm-4-flash",
            "display_name": "GLM-4 Flash",
            "description": "Ultra-fast, ultra-low-cost lightweight model",
        },
    ]

    def __init__(self):
        BaseProvider.__init__(self, provider_name="zhipu", display_name="Zhipu (GLM)")

    def get_credential_schema(self) -> Dict[str, Any]:
        """Return credential form schema."""
        schema = super().get_credential_schema()

        # customize the base URL for Zhipu
        base_url_prop = schema["properties"]["base_url"]
        base_url_prop["description"] = "Zhipu API base URL (leave empty to use default)"
        base_url_prop["default"] = "https://open.bigmodel.cn/api/paas/v4/"
        # remove strict required so the default can take effect
        if "required" in schema and "base_url" in schema["required"]:
            schema["required"].remove("base_url")

        return schema

    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate credentials."""
        creds = credentials.copy()
        if not creds.get("base_url"):
            creds["base_url"] = "https://open.bigmodel.cn/api/paas/v4/"

        return await super().validate_credentials(creds)

    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseChatModel:
        """Create a model instance."""
        creds = credentials.copy()
        if not creds.get("base_url"):
            creds["base_url"] = "https://open.bigmodel.cn/api/paas/v4/"

        return super().create_model_instance(
            model_name=model_name,
            model_type=model_type,
            credentials=creds,
            model_parameters=model_parameters,
        )
