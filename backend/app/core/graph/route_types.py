"""
Route Types - Type definitions for routing in LangGraph workflows.

Provides type-safe route key definitions and validation utilities.
"""

from typing import Literal, Set, Union

from typing_extensions import TypedDict

# Common route keys used in conditional routing
RouteKey = Union[
    Literal["true", "false"],
    Literal["continue_loop", "exit_loop"],
    Literal["default"],
    str,  # Allow custom route keys
]


class RouteConfig(TypedDict, total=False):
    """Configuration for a route in conditional edges.

    Attributes:
        route_key: The route key identifier
        target_node: The target node name
        label: Optional label for display/debugging
    """

    route_key: str
    target_node: str
    label: str


def validate_route_key(route_key: str, allowed_keys: Set[str]) -> bool:
    """Validate that a route key is in the allowed set.

    Args:
        route_key: The route key to validate
        allowed_keys: Set of allowed route keys

    Returns:
        True if route_key is valid, False otherwise
    """
    return route_key in allowed_keys


def get_standard_route_keys() -> Set[str]:
    """Get the set of standard route keys used in the system.

    Returns:
        Set of standard route key strings
    """
    return {
        "true",
        "false",
        "continue_loop",
        "exit_loop",
        "default",
    }
