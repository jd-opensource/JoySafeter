"""
Model Reference Parsing Utilities.

Provides unified parsing for model references in format:
- Combined: "provider:model_name"
- Split fields: provider_name/provider + model_name/model
"""

from typing import Any, Optional, Tuple


def parse_model_ref(
    model: Any,
    provider: Any = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse model reference into (provider_name, model_name).

    Supports multiple input formats:
    - Combined string: "provider:model_name" -> ("provider", "model_name")
    - Plain model name: "model_name" -> (None, "model_name") or (provider, "model_name") if provider given
    - None/empty -> (None, None)

    Args:
        model: Model reference - can be "provider:name", plain name, or None
        provider: Optional explicit provider name (takes precedence if model doesn't contain ':')

    Returns:
        Tuple of (provider_name, model_name). Either or both can be None if not resolvable.

    Examples:
        >>> parse_model_ref("aisafety:Qwen3-30B")
        ("aisafety", "Qwen3-30B")

        >>> parse_model_ref("Qwen3-30B", "aisafety")
        ("aisafety", "Qwen3-30B")

        >>> parse_model_ref("Qwen3-30B")
        (None, "Qwen3-30B")

        >>> parse_model_ref(None)
        (None, None)
    """
    # Normalize provider to string or None
    provider_name: Optional[str] = str(provider).strip() if provider else None
    if provider_name == "":
        provider_name = None

    # Handle None/empty model
    if model is None:
        return (provider_name, None)

    model_str = str(model).strip()
    if not model_str:
        return (provider_name, None)

    # Check for combined format "provider:model_name"
    if ":" in model_str:
        parts = model_str.split(":", 1)
        combined_provider = parts[0].strip()
        combined_model = parts[1].strip() if len(parts) > 1 else ""

        # Use combined provider if explicit provider not given
        if not provider_name and combined_provider:
            provider_name = combined_provider

        # Model name is always the part after ':'
        model_name = combined_model if combined_model else None
        return (provider_name, model_name)

    # Plain model name (no ':')
    return (provider_name, model_str)


def format_model_ref(provider_name: Optional[str], model_name: Optional[str]) -> Optional[str]:
    """
    Format provider and model name back into combined reference.

    Args:
        provider_name: Provider name (optional)
        model_name: Model name (required for non-None output)

    Returns:
        Combined reference "provider:model" if both present,
        just "model" if only model_name,
        None if model_name is None.

    Examples:
        >>> format_model_ref("aisafety", "Qwen3-30B")
        "aisafety:Qwen3-30B"

        >>> format_model_ref(None, "Qwen3-30B")
        "Qwen3-30B"

        >>> format_model_ref("aisafety", None)
        None
    """
    if not model_name:
        return None

    if provider_name:
        return f"{provider_name}:{model_name}"

    return model_name


def parse_model_ref_from_config(
    config: dict,
    model_key: str = "model",
    provider_key: str = "provider_name",
    fallback_model_keys: Optional[list] = None,
    fallback_provider_keys: Optional[list] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse model reference from a config dict with fallback keys.

    This is a convenience wrapper that tries multiple config keys.

    Args:
        config: Configuration dictionary
        model_key: Primary key for model (default: "model")
        provider_key: Primary key for provider (default: "provider_name")
        fallback_model_keys: Additional keys to try for model (default: ["model_name", "name"])
        fallback_provider_keys: Additional keys to try for provider (default: ["provider"])

    Returns:
        Tuple of (provider_name, model_name)
    """
    if fallback_model_keys is None:
        fallback_model_keys = ["model_name", "name"]
    if fallback_provider_keys is None:
        fallback_provider_keys = ["provider"]

    # Get provider from config
    provider = config.get(provider_key)
    if not provider:
        for key in fallback_provider_keys:
            provider = config.get(key)
            if provider:
                break

    # Get model from config
    model = config.get(model_key)
    if not model:
        for key in fallback_model_keys:
            model = config.get(key)
            if model:
                break

    return parse_model_ref(model, provider)
