"""
Model Tools - Query available models.

Provides list_models tool for querying available LLM models.
"""

import json

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.copilot.tools.context import get_preloaded_models


class ListModelsInput(BaseModel):
    """Input schema for list_models tool."""

    model_type: str = Field(
        default="chat", description="Model type to query: 'chat', 'embedding', etc. Currently only 'chat' is preloaded."
    )


@tool(
    args_schema=ListModelsInput,
    description="Query available LLM models for agent nodes. Returns model list with capabilities and availability.",
)
def list_models(model_type: str = "chat") -> str:
    """
    Query available models for agent nodes.

    Args:
        model_type: Model type to query (default: 'chat')

    Returns:
        JSON with model list containing name, display_name, provider, is_available, is_default.

    Note: Use before creating agent nodes to verify model names. Prefer 'claude'/'gpt-4' for complex tasks, 'mini'/'fast' for simple tasks.
    """
    preloaded_models = get_preloaded_models()

    if not preloaded_models:
        return json.dumps(
            {
                "error": "No models preloaded. Models should be loaded during agent initialization.",
                "suggestion": "Check system configuration or contact administrator.",
            },
            ensure_ascii=False,
        )

    # Filter by model type if needed (currently all preloaded are chat models)
    filtered_models = [
        {
            "name": m.get("name"),
            "display_name": m.get("display_name"),
            "provider_name": m.get("provider_name"),
            "description": m.get("description", ""),
            "is_available": m.get("is_available", False),
            "is_default": m.get("is_default", False),
        }
        for m in preloaded_models
        if m.get("is_available", False)  # Only return available models
    ]

    return json.dumps(
        {
            "model_type": model_type,
            "total_count": len(filtered_models),
            "models": filtered_models,
        },
        ensure_ascii=False,
        indent=2,
    )
