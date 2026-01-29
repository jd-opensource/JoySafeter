"""
LLM Credential Resolver - Unified credential fetching logic for LLM services.

Provides a generic utility for fetching LLM credentials from the database,
replacing service-specific credential retrieval logic.
"""

from typing import Any, Dict, Optional, Tuple

from loguru import logger


class LLMCredentialResolver:
    """Resolver for fetching LLM credentials from database."""

    @staticmethod
    async def get_credentials(
        db: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Get credentials from database if not provided.

        Logic:
        1. If api_key is already provided, return it (with base_url and llm_model if provided)
        2. If db is available, fetch credentials from database:
           - Try to get default model instance
           - If default model exists, get its provider credentials
           - If no default model, try to get first available valid credential
        3. Return (api_key, base_url, model_name) tuple

        Args:
            db: Database session
            api_key: Optional pre-provided API key
            base_url: Optional pre-provided base URL
            llm_model: Optional pre-provided model name

        Returns:
            Tuple of (api_key, base_url, model_name)
        """
        default_instance = None
        model_name: Optional[str] = None

        # If api_key is already provided, return early with provided values (no DB query needed)
        if api_key:
            return api_key, base_url, llm_model

        # Try to get credentials from database if db is available and api_key is not provided
        if db:
            try:
                from app.core.model import ModelType
                from app.services.model_credential_service import ModelCredentialService
                from app.services.model_service import ModelService

                model_service = ModelService(db)
                credential_service = ModelCredentialService(db)

                # Try to get default model
                default_instance = await model_service.repo.get_default()
                if default_instance:
                    provider_name = default_instance.provider.name
                    model_name = default_instance.model_name
                    model_type = ModelType.CHAT  # Simplified: assume Chat model

                    credentials = await credential_service.get_current_credentials(
                        provider_name=provider_name or "",
                        model_type=model_type,
                        model_name=model_name or "",
                    )
                    if credentials:
                        api_key = credentials.get("api_key")
                        base_url = base_url or credentials.get("base_url")
                else:
                    # If no default model, try to get first available valid credential
                    all_credentials = await credential_service.list_credentials()
                    for cred in all_credentials:
                        if cred.get("is_valid"):
                            provider_name_from_cred = cred.get("provider_name")
                            if not provider_name_from_cred or not isinstance(provider_name_from_cred, str):
                                continue
                            # Try to get first model for this provider
                            provider = await model_service.provider_repo.get_by_name(provider_name_from_cred)
                            if provider:
                                instances = await model_service.repo.list_all()
                                provider_instances = [i for i in instances if i.provider_id == provider.id]
                                if provider_instances:
                                    model_name = provider_instances[0].model_name
                                    model_type = ModelType.CHAT
                                    credentials = await credential_service.get_current_credentials(
                                        provider_name=provider_name or provider_name_from_cred,
                                        model_type=model_type,
                                        model_name=model_name or "",
                                    )
                                    if credentials:
                                        api_key = credentials.get("api_key")
                                        base_url = base_url or credentials.get("base_url")
                                        break
            except Exception as e:
                logger.warning(f"[LLMCredentialResolver] Failed to get credentials from DB: {e}")

        # Determine final model name (prioritize DB-fetched model)
        final_model_name = model_name if model_name else llm_model
        if not final_model_name:
            # If still no model name, get from default instance
            if default_instance:
                final_model_name = default_instance.model_name

        return api_key, base_url, final_model_name

    @staticmethod
    async def get_llm_params(
        db: Any,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_model: Optional[str] = None,
        max_tokens: int = 4096,
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

        Args:
            db: Database session
            api_key: Optional pre-provided API key
            base_url: Optional pre-provided base URL
            llm_model: Optional pre-provided model name
            max_tokens: Maximum tokens for completion

        Returns:
            Dict with llm_model, api_key, base_url, max_tokens
        """
        api_key, base_url, model_name = await LLMCredentialResolver.get_credentials(
            db=db,
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
        )

        return {
            "llm_model": model_name or llm_model or "",
            "api_key": api_key,
            "base_url": base_url,
            "max_tokens": max_tokens,
        }
