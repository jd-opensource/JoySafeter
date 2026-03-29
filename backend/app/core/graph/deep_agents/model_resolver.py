"""Unified model resolver — resolves LLM model instances from config.

Single entry point for both node models and memory models.
Resolution strategy: ModelService exact match → ModelService default → fallback.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.core.model.utils.model_ref import parse_model_ref


class ModelResolver:
    """Resolves LLM model instances from provider/model name pairs."""

    def __init__(
        self,
        model_service: Any,
        user_id: Optional[str] = None,
        default_model_name: Optional[str] = None,
        default_api_key: Optional[str] = None,
        default_base_url: Optional[str] = None,
    ):
        self._model_service = model_service
        self._user_id = user_id
        self._default_model_name = default_model_name
        self._default_api_key = default_api_key
        self._default_base_url = default_base_url
        self._cache: dict[str, Any] = {}

    async def resolve(
        self,
        model_name: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> Any:
        """Resolve a model instance. Results are cached by (provider, model) key."""
        provider, model = parse_model_ref(
            model_name or self._default_model_name,
            provider_name,
        )

        cache_key = f"{provider}:{model}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolved = await self._resolve_uncached(provider, model)
        if resolved:
            self._cache[cache_key] = resolved
        return resolved

    async def _resolve_uncached(
        self,
        provider_name: Optional[str],
        model_name: Optional[str],
    ) -> Any:
        """Try each resolution strategy in order."""
        # Strategy 1: ModelService exact match
        if self._model_service and model_name:
            model = await self._try_model_service(provider_name, model_name)
            if model:
                return model

        # Strategy 2: ModelService default
        if self._model_service:
            model = await self._try_default_model()
            if model:
                return model

        # Strategy 3: Hardcoded fallback
        return self._fallback(model_name)

    async def _try_model_service(
        self,
        provider_name: Optional[str],
        model_name: str,
    ) -> Any:
        """Try to resolve via ModelService."""
        try:
            uid = str(self._user_id) if self._user_id else "system"
            if provider_name and model_name:
                model = await self._model_service.get_model_instance(
                    user_id=uid,
                    provider_name=provider_name,
                    model_name=model_name,
                    use_default=False,
                )
            else:
                model = await self._model_service.get_runtime_model_by_name(
                    model_name=model_name,
                    user_id=uid,
                )
            logger.info(f"[ModelResolver] Resolved via ModelService | provider={provider_name} | model={model_name}")
            return model
        except Exception as e:
            logger.warning(
                f"[ModelResolver] ModelService failed | provider={provider_name} | model={model_name} | error={e}"
            )
            return None

    async def _try_default_model(self) -> Any:
        """Try to get the default model from ModelService."""
        try:
            uid = str(self._user_id) if self._user_id else "system"
            model = await self._model_service.get_model_instance(
                user_id=uid,
                use_default=True,
            )
            logger.info("[ModelResolver] Using database default model")
            return model
        except Exception as e:
            logger.warning(f"[ModelResolver] Default model failed | error={e}")
            return None

    @staticmethod
    def _fallback(model_name: Optional[str]) -> Any:
        """Last resort: use get_default_model."""
        from app.core.agent.sample_agent import get_default_model

        logger.info(f"[ModelResolver] Using hardcoded fallback | model={model_name}")
        return get_default_model(model_name)

    def extract_credentials(self, resolved_model: Any) -> dict[str, Any]:
        """Extract API credentials from a resolved model instance."""
        api_key = self._default_api_key
        base_url = self._default_base_url
        model_name = self._default_model_name

        try:
            if hasattr(resolved_model, "openai_api_key"):
                api_key = resolved_model.openai_api_key
            if hasattr(resolved_model, "openai_api_base"):
                base_url = resolved_model.openai_api_base
            if hasattr(resolved_model, "model_name"):
                model_name = resolved_model.model_name
            elif hasattr(resolved_model, "model"):
                model_name = resolved_model.model
        except Exception:
            pass

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name,
        }
