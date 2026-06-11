"""
Provider base class.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from langchain_core.language_models.base import BaseLanguageModel


class ModelType(str, Enum):
    """Model type enumeration."""

    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    MODERATION = "moderation"


class BaseProvider(ABC):
    """Provider base class.

    All providers should inherit from this class and implement:
    - validate_credentials: validate credentials
    - get_model_list: list available models
    - create_model_instance: create a model instance
    """

    def __init__(self, provider_name: str, display_name: str, is_template: bool = False, provider_type: str = "system"):
        """
        Initialize the provider.

        Args:
            provider_name: unique provider identifier (e.g. 'openai')
            display_name: human-readable name (e.g. 'OpenAI')
            is_template: whether this is a template for creating custom providers
            provider_type: provider category: system, custom
        """
        self.provider_name = provider_name
        self.display_name = display_name
        self.is_template = is_template
        self.provider_type = provider_type

    @abstractmethod
    def get_supported_model_types(self) -> List[ModelType]:
        """
        Return the list of supported model types.

        Returns:
            List of supported model types.
        """
        pass

    @abstractmethod
    def get_credential_schema(self) -> Dict[str, Any]:
        """
        Return the credential form schema (JSON Schema format).

        Returns:
            Credential form schema dict.
        """
        pass

    @abstractmethod
    def get_config_schema(self, model_type: ModelType) -> Optional[Dict[str, Any]]:
        """
        Return the model parameter config schema (JSON Schema format).

        Args:
            model_type: model type

        Returns:
            Config schema dict, or None if the model type has no configurable parameters.
        """
        pass

    @abstractmethod
    async def validate_credentials(self, credentials: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate provider credentials.

        Args:
            credentials: credential dict

        Returns:
            (is_valid, error_message)
        """
        pass

    @abstractmethod
    def get_model_list(
        self, model_type: ModelType, credentials: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Return the list of available models.

        Args:
            model_type: model type
            credentials: optional credentials for fetching remote model lists

        Returns:
            List of model dicts, each containing:
            - name: model name
            - display_name: display name
            - description: description
            - is_available: availability (may require credentials)
        """
        pass

    @abstractmethod
    def create_model_instance(
        self,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseLanguageModel:
        """
        Create a model instance.

        Args:
            model_name: model name
            model_type: model type
            credentials: credential dict
            model_parameters: model parameters (e.g. temperature, max_tokens)

        Returns:
            LangChain model instance (BaseChatModel, BaseLLM, etc.)
        """
        pass

    def get_predefined_models(self, model_type: ModelType) -> List[Dict[str, Any]]:
        """
        Return predefined models (no credentials required).

        Args:
            model_type: model type

        Returns:
            List of predefined model dicts.
        """
        return []

    async def test_output(self, instance_dict: Dict[str, Any], input: str) -> str:
        """
        Test model output.

        Args:
            instance_dict: model instance dict
            input: input text

        Returns:
            Test output string.
        """
        return ""
