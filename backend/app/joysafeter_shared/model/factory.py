"""
Model factory layer.
"""

from typing import Any, Dict, List, Optional

from langchain_core.language_models.base import BaseLanguageModel

# backward-compatible imports (kept to avoid breaking existing code)
from .providers import (
    BaseProvider,
    ModelType,
    get_all_provider_instances,
)


class ModelFactory:
    """Model factory.

    Manage all providers and expose a unified model creation interface.
    """

    def __init__(self):
        """Initialize the factory."""
        self._providers: Dict[str, BaseProvider] = {}
        self._register_default_providers()

    def _register_default_providers(self):
        """Register default providers (auto-discover and register all providers)."""
        # auto-discover and register all provider classes
        provider_instances = get_all_provider_instances()
        for provider in provider_instances:
            self.register_provider(provider)

    def register_provider(self, provider: BaseProvider):
        """
        Register a provider.

        Args:
            provider: provider instance
        """
        self._providers[provider.provider_name] = provider

    def get_provider(self, provider_name: str) -> Optional[BaseProvider]:
        """
        Return a provider instance.

        Args:
            provider_name: provider identifier

        Returns:
            Provider instance, or None if not found.
        """
        return self._providers.get(provider_name)

    def get_all_providers(self) -> List[Dict[str, Any]]:
        """
        Return information for all providers.

        Returns:
            List of provider info dicts, each containing:
            - provider_name: provider identifier
            - display_name: display name
            - supported_model_types: list of supported model types
            - credential_schema: credential form schema
            - config_schema: config schema (per model type)
        """
        providers = []
        for provider_name, provider in self._providers.items():
            model_count = 0
            for model_type in provider.get_supported_model_types():
                models = provider.get_model_list(model_type, None)
                model_count += len(models)

            provider_info = {
                "provider_name": provider_name,
                "display_name": provider.display_name,
                "supported_model_types": [mt.value for mt in provider.get_supported_model_types()],
                "credential_schema": provider.get_credential_schema(),
                "model_count": model_count,
                "is_template": provider.is_template,
                "provider_type": provider.provider_type,
            }

            # add config schema for each model type
            config_schemas = {}
            for model_type in provider.get_supported_model_types():
                config_schema = provider.get_config_schema(model_type)
                if config_schema:
                    config_schemas[model_type.value] = config_schema

            if config_schemas:
                provider_info["config_schemas"] = config_schemas

            providers.append(provider_info)

        return providers

    def get_all_models(
        self,
        model_type: ModelType,
        credentials: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return all available models.

        Args:
            model_type: model type
            credentials: optional credential dict, format {provider_name: credentials}

        Returns:
            List of model dicts, each containing:
            - provider_name: provider identifier
            - display_name: provider display name
            - name: model name
            - display_name: display name
            - description: description
            - is_available: availability flag
        """
        all_models = []

        for provider_name, provider in self._providers.items():
            if model_type not in provider.get_supported_model_types():
                continue

            # get credentials for this provider (if any)
            provider_credentials = credentials.get(provider_name) if credentials else None

            # get model list
            models = provider.get_model_list(model_type, provider_credentials)

            for model in models:
                model_info = {
                    "provider_name": provider_name,
                    "provider_display_name": provider.display_name,
                    "name": model["name"],
                    "display_name": model.get("display_name", model["name"]),
                    "description": model.get("description", ""),
                    "is_available": model.get("is_available", True),
                }
                all_models.append(model_info)

        return all_models

    async def validate_provider_credentials(
        self,
        provider_name: str,
        credentials: Dict[str, Any],
        model_name: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Validate provider credentials.

        Args:
            provider_name: provider identifier
            credentials: credential dict
            model_name: optional model name, used by CustomProvider to specify the validation model

        Returns:
            (is_valid, error_message)
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return False, f"Provider not found: {provider_name}"

        # CustomProvider supports specifying a validation model; other providers use a predefined model
        from .providers.Custom import CustomProvider

        if isinstance(provider, CustomProvider) and model_name:
            return await provider.validate_credentials(credentials, model_name=model_name)
        return await provider.validate_credentials(credentials)

    async def validate_model_credentials(
        self,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate model credentials by attempting to create a model instance.

        Args:
            provider_name: provider identifier
            model_name: model name
            model_type: model type
            credentials: credential dict

        Returns:
            (is_valid, error_message)
        """
        provider = self.get_provider(provider_name)
        if not provider:
            return False, f"Provider not found: {provider_name}"

        try:
            # validate credentials first
            from .providers.Custom import CustomProvider

            if isinstance(provider, CustomProvider):
                is_valid, error = await provider.validate_credentials(credentials, model_name=model_name)
            else:
                is_valid, error = await provider.validate_credentials(credentials)
            if not is_valid:
                return False, error

            # attempt to create a model instance
            model = provider.create_model_instance(model_name, model_type, credentials)
            if model:
                return True, None
            else:
                return False, "Failed to create model instance"
        except Exception as e:
            return False, f"Validation failed: {str(e)}"

    def create_model_instance(
        self,
        provider_name: str,
        model_name: str,
        model_type: ModelType,
        credentials: Dict[str, Any],
        model_parameters: Optional[Dict[str, Any]] = None,
    ) -> BaseLanguageModel:
        """
        Create a model instance.

        Args:
            provider_name: provider identifier
            model_name: model name
            model_type: model type
            credentials: credential dict
            model_parameters: model parameters

        Returns:
            LangChain model instance.
        """
        provider = self.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Provider not found: {provider_name}")

        model = provider.create_model_instance(model_name, model_type, credentials, model_parameters)
        return model


# global factory instance
_factory = ModelFactory()


def get_factory() -> ModelFactory:
    """Return the global factory instance."""
    return _factory


def get_all_providers() -> List[Dict[str, Any]]:
    """Return information for all providers."""
    return _factory.get_all_providers()


def get_provider(provider_name: str) -> Optional[BaseProvider]:
    """Return a provider instance."""
    return _factory.get_provider(provider_name)


async def validate_provider_credentials(
    provider_name: str,
    credentials: Dict[str, Any],
    model_name: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Validate provider credentials."""
    return await _factory.validate_provider_credentials(provider_name, credentials, model_name=model_name)


def create_model_instance(
    provider_name: str,
    model_name: str,
    model_type: ModelType,
    credentials: Dict[str, Any],
    model_parameters: Optional[Dict[str, Any]] = None,
) -> BaseLanguageModel:
    """Create a model instance."""
    return _factory.create_model_instance(provider_name, model_name, model_type, credentials, model_parameters)
