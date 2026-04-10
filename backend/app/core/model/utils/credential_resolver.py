"""
LLM Credential Resolver - Unified credential fetching logic for LLM services.

Provides a generic utility for fetching LLM credentials from the database,
replacing service-specific credential retrieval logic.
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger


def _requires_api_key(provider_name: str) -> bool:
    """Check whether a provider's credential schema includes an api_key field.

    Providers like Ollama only require base_url; they don't need an API key.
    """
    try:
        from app.core.model.factory import get_provider

        provider = get_provider(provider_name)
        if provider:
            schema = provider.get_credential_schema()
            required = schema.get("required", [])
            properties = schema.get("properties", {})
            return "api_key" in required or "api_key" in properties
    except Exception:
        pass
    # Default to True for unknown providers (safer fallback)
    return True


# Placeholder API key used for providers that don't require authentication.
# This satisfies downstream `if not api_key` guards while the provider's
# create_model_instance() will supply its own value (e.g. Ollama uses "ollama").
_NO_KEY_PLACEHOLDER = "no-key-required"


class LLMCredentialResolver:
    """Resolver for fetching LLM credentials from database."""

    @staticmethod
    async def get_credentials(
        db: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get credentials from database if not provided.

        Logic:
        1. If api_key is already provided, return it (with base_url and llm_model if provided)
        2. If llm_model contains provider info (format: provider:model), resolve from that provider
        3. Otherwise, try to get first available valid credential from database

        For providers that don't require an API key (e.g. Ollama), a placeholder
        value is returned so that downstream guards like ``if not api_key`` pass.

        Args:
            db: Database session
            api_key: Optional pre-provided API key
            base_url: Optional pre-provided base URL
            llm_model: Optional pre-provided model name (can be "provider:model" format)
            user_id: Optional user ID

        Returns:
            Tuple of (api_key, base_url, model_name)
        """
        model_name: Optional[str] = None

        # If api_key is already provided, return early with provided values (no DB query needed)
        if api_key:
            return api_key, base_url, llm_model

        # Try to get credentials from database if db is available and api_key is not provided
        if db:
            try:
                from app.services.model_credential_service import ModelCredentialService
                from app.services.model_service import ModelService

                model_service = ModelService(db)
                credential_service = ModelCredentialService(db)

                # If llm_model is in "provider:model" format, resolve from that provider
                if llm_model and ":" in llm_model:
                    provider_name, model_name = llm_model.split(":", 1)
                    credentials = await credential_service.get_decrypted_credentials(provider_name)
                    if credentials:
                        api_key = credentials.get("api_key")
                        base_url = base_url or credentials.get("base_url")
                        if not api_key and not _requires_api_key(provider_name):
                            api_key = _NO_KEY_PLACEHOLDER
                        return api_key, base_url, model_name

                # Fallback: try to get first available valid credential
                all_credentials = await credential_service.list_credentials()
                all_instances = await model_service.repo.list_all()
                for cred in all_credentials:
                    if cred.get("is_valid"):
                        provider_name_from_cred = cred.get("provider_name")
                        if not provider_name_from_cred or not isinstance(provider_name_from_cred, str):
                            continue
                        provider = await model_service.provider_repo.get_by_name(provider_name_from_cred)
                        if provider:
                            provider_instances = [i for i in all_instances if i.provider_id == provider.id]
                        else:
                            provider_instances = []
                        if provider_instances:
                            model_name = provider_instances[0].model_name
                            credentials = await credential_service.get_decrypted_credentials(provider_name_from_cred)
                            if credentials:
                                api_key = credentials.get("api_key")
                                base_url = base_url or credentials.get("base_url")
                                if not api_key and not _requires_api_key(provider_name_from_cred):
                                    api_key = _NO_KEY_PLACEHOLDER
                                break
            except Exception as e:
                logger.warning(f"[LLMCredentialResolver] Failed to get credentials from DB: {e}")

        # Determine final model name
        final_model_name = model_name if model_name else llm_model

        return api_key, base_url, final_model_name

    @staticmethod
    async def get_llm_params(
        db: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get LLM parameters in dict format.

        Returns credentials in the format expected by LLM initialization:
        {
            "llm_model": str,
            "api_key": str,
            "base_url": Optional[str],
            "max_tokens": int
        }
        """
        api_key, base_url, model_name = await LLMCredentialResolver.get_credentials(
            db=db,
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
            user_id=user_id,
        )

        return {
            "llm_model": model_name or llm_model or "",
            "api_key": api_key,
            "base_url": base_url,
            "max_tokens": max_tokens,
        }
