"""Base provider interface and utilities."""

from typing import Dict


def calculate_cost(
    usage: Dict[str, int],
    input_cost_per_m: float,
    output_cost_per_m: float,
    cache_write_cost_per_m: float = 0.0,
    cache_read_cost_per_m: float = 0.0,
) -> float:
    """
    Calculate cost in USD based on token usage.

    Args:
        usage: Token usage dict with keys like input_tokens, output_tokens, etc.
        input_cost_per_m: Cost per million input tokens
        output_cost_per_m: Cost per million output tokens
        cache_write_cost_per_m: Cost per million cache write tokens
        cache_read_cost_per_m: Cost per million cache read tokens

    Returns:
        Total cost in USD
    """
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)

    cost = (
        (input_tokens / 1_000_000) * input_cost_per_m
        + (output_tokens / 1_000_000) * output_cost_per_m
        + (cache_creation / 1_000_000) * cache_write_cost_per_m
        + (cache_read / 1_000_000) * cache_read_cost_per_m
    )

    return cost
