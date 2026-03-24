"""
Route Types - Type definitions for routing in LangGraph workflows.
"""

from typing import Literal, Union

# Common route keys used in conditional routing
RouteKey = Union[
    Literal["true", "false"],
    Literal["continue_loop", "exit_loop"],
    Literal["default"],
    str,  # Allow custom route keys
]
