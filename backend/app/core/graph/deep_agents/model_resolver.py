"""Unified model resolver — resolves LLM model instances from config.

Single entry point for both node models and memory models.
Resolution strategy: ModelService exact match → precise error.
"""

from __future__ import annotations

from typing import Any, List, Optional

from loguru import logger

from app.common.exceptions import ModelConfigError
from app.core.graph.deep_agents import format_node_ctx
from app.core.model.utils.model_ref import parse_model_ref
from app.services.model_service import MODEL_NOT_FOUND


class ModelResolver:
    """Resolves LLM model instances from provider/model name pairs."""

    def __init__(
        self,
        model_service: Any,
        user_id: Optional[str] = None,
    ):
        self._model_service = model_service
        self._user_id = user_id
        self._cache: dict[str, Any] = {}

    async def resolve(
        self,
        model_name: Optional[str] = None,
        provider_name: Optional[str] = None,
        *,
        node_label: Optional[str] = None,
        graph_name: Optional[str] = None,
    ) -> Any:
        """Resolve a model instance. Results are cached by (provider, model) key."""
        if not model_name:
            ctx = format_node_ctx(node_label, graph_name)
            raise ModelConfigError(
                ModelConfigError.MODEL_NAME_REQUIRED,
                f'{ctx} has no model configured.',
                params={
                    "node": node_label or "unknown",
                    "graph": graph_name or "unknown",
                },
            )

        provider, model = parse_model_ref(model_name, provider_name)

        cache_key = f"{provider}:{model}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        resolved = await self._resolve_uncached(
            provider, model, node_label=node_label, graph_name=graph_name,
        )
        if resolved:
            self._cache[cache_key] = resolved
        return resolved

    async def _resolve_uncached(
        self,
        provider_name: Optional[str],
        model_name: Optional[str],
        *,
        node_label: Optional[str] = None,
        graph_name: Optional[str] = None,
    ) -> Any:
        """Try ModelService resolution, raise precise error on failure."""
        if self._model_service and model_name:
            model = await self._try_model_service(provider_name, model_name)
            if model:
                return model

        available = await self._list_available_model_names()
        ctx = format_node_ctx(node_label, graph_name)
        raise ModelConfigError(
            MODEL_NOT_FOUND,
            f'Model "{model_name}" is not available ({ctx}).',
            params={
                "model": model_name or "",
                "provider": provider_name or "",
                "node": node_label or "unknown",
                "graph": graph_name or "unknown",
                "available": ", ".join(available[:5]),
            },
        )

    async def _try_model_service(
        self,
        provider_name: Optional[str],
        model_name: str,
    ) -> Any:
        """Try to resolve via ModelService. Returns model or None.

        ModelConfigError is re-raised so the frontend gets structured error info.
        """
        try:
            uid = str(self._user_id) if self._user_id else "system"
            if provider_name and model_name:
                model = await self._model_service.get_model_instance(
                    user_id=uid,
                    provider_name=provider_name,
                    model_name=model_name,
                )
            else:
                model = await self._model_service.get_runtime_model_by_name(
                    model_name=model_name,
                    user_id=uid,
                )
            logger.info(f"[ModelResolver] Resolved via ModelService | provider={provider_name} | model={model_name}")
            return model
        except ModelConfigError:
            raise
        except Exception as e:
            logger.warning(
                f"[ModelResolver] ModelService failed | provider={provider_name} | model={model_name} | error={e}"
            )
            return None

    async def _list_available_model_names(self) -> List[str]:
        """Query available model names from ModelService for error diagnostics."""
        try:
            if self._model_service and hasattr(self._model_service, "repo"):
                all_instances = await self._model_service.repo.list_all()
                return [inst.model_name for inst in all_instances]
        except Exception:
            logger.debug("Failed to list available model names from ModelService", exc_info=True)
        return []
