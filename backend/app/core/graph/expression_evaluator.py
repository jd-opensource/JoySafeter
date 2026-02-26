"""
Expression Evaluator - Safe evaluation of Python expressions in the graph.

This module provides utilities to:
1. Validate Python expressions for safety (AST analysis).
2. Wrap state objects to support dot-notation access in expressions.
3. Safe execution context for conditions and custom functions.
"""

import ast
import re
from typing import Any, Dict, Set

from loguru import logger


def validate_condition_expression(expr: str) -> bool:
    """
    Pre-validate condition expression syntax and safety.

    Enhanced validation with better error handling and more permissive safe operations.

    Args:
        expr: Python expression string to validate

    Returns:
        True if expression is safe and syntactically valid, False otherwise
    """
    if not expr or not expr.strip():
        return False

    try:
        # Parse the expression to AST
        tree = ast.parse(expr, mode="eval")

        # Walk through all nodes and check for dangerous constructs
        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    # Allow specific safe builtin functions
                    safe_functions = {
                        "len",
                        "str",
                        "int",
                        "float",
                        "bool",
                        "abs",
                        "min",
                        "max",
                        "sum",
                        "any",
                        "all",
                        "sorted",
                        "reversed",
                        "enumerate",
                        "range",
                        "list",
                        "dict",
                        "set",
                        "tuple",
                    }
                    if node.func.id not in safe_functions:
                        logger.warning(f"[ConditionValidator] Disallowed function call: {node.func.id}")
                        return False
                elif isinstance(node.func, ast.Attribute):
                    # Allow method calls on specific safe objects
                    if isinstance(node.func.value, ast.Name):
                        obj_name = node.func.value.id
                        method_name = node.func.attr

                        # Allow comprehensive methods on safe objects
                        safe_object_methods: Dict[str, Set[str]] = {
                            "state": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "context": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "messages": {
                                "get",
                                "keys",
                                "values",
                                "items",
                                "__contains__",
                                "__getitem__",
                                "__len__",
                                "__iter__",
                            },
                            "loop_state": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "loop_count": set(),  # Allow direct access to loop_count variable
                            "current_node": set(),  # Allow direct access to current_node variable
                        }

                        # Check if object is in safe list
                        if obj_name in safe_object_methods:
                            allowed_methods = safe_object_methods[obj_name]
                            # Allow all methods if set is empty (for variables), or specific methods
                            if not allowed_methods or method_name in allowed_methods:
                                continue

                        # Allow some safe operations on lists/dicts/strings
                        safe_container_methods = {
                            "append",
                            "extend",
                            "insert",
                            "remove",
                            "pop",
                            "clear",
                            "index",
                            "count",
                            "keys",
                            "values",
                            "items",
                            "get",
                            "__getitem__",
                            "__contains__",
                            "__len__",
                            "startswith",
                            "endswith",
                            "strip",
                            "split",
                            "join",
                            "upper",
                            "lower",
                            "replace",
                        }
                        if method_name in safe_container_methods:
                            continue

                        logger.warning(f"[ConditionValidator] Disallowed method call: {obj_name}.{method_name}")
                        return False
                    else:
                        # Allow chained calls like state.get('key', {}).get('subkey')
                        # This is more permissive but still safe
                        continue
                else:
                    logger.warning("[ConditionValidator] Unsupported call type")
                    return False

            # Disallow dangerous constructs
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                logger.warning(f"[ConditionValidator] Disallowed construct: {type(node).__name__}")
                return False

            # Disallow assignments and mutations
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
                logger.warning(f"[ConditionValidator] Disallowed mutation: {type(node).__name__}")
                return False

            # Disallow function definitions
            elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
                logger.warning(f"[ConditionValidator] Disallowed function definition: {type(node).__name__}")
                return False

        return True
    except SyntaxError as e:
        logger.warning(f"[ConditionValidator] Syntax error in expression '{expr}': {e}")
        return False
    except Exception as e:
        logger.warning(f"[ConditionValidator] Unexpected error validating expression '{expr}': {e}")
        return False


class StateWrapper:
    """Wrapper that allows both dot notation and dict access to state.

    This class enables expressions like 'state.loop_count>1' to work,
    while still supporting dict-style access like 'state.get("loop_count")'.
    """

    def __init__(self, state_dict: Dict[str, Any]):
        self._state = state_dict
        # Set attributes for direct dot notation access
        for key, value in state_dict.items():
            if isinstance(value, dict):
                # Recursively wrap nested dictionaries
                setattr(self, key, StateWrapper(value))
            else:
                setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        """Handle attribute access for keys that may not exist in the dict.

        This allows accessing optional fields like loop_count even if they
        weren't in the original dict when StateWrapper was created.
        """
        if name.startswith("_"):
            # Don't interfere with private attributes
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Try to get from the underlying dict
        if name in self._state:
            value = self._state[name]
            # If it's a dict, wrap it (in case it was added after initialization)
            if isinstance(value, dict):
                return StateWrapper(value)
            return value

        # Return None for missing attributes (allows expressions like state.loop_count > 1)
        # This is safer than raising AttributeError for optional fields
        return None

    def get(self, key: str, default: Any = None) -> Any:
        """Support dict.get() method for backward compatibility."""
        return self._state.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Support dict[] access for backward compatibility."""
        return self._state[key]

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator."""
        return key in self._state

    def keys(self):
        """Support dict.keys() method."""
        return self._state.keys()

    def values(self):
        """Support dict.values() method."""
        return self._state.values()

    def items(self):
        """Support dict.items() method."""
        return self._state.items()

    def __len__(self) -> int:
        """Support len() function."""
        return len(self._state)


# ---------------------------------------------------------------------------
# Variable Interpolation Engine
# ---------------------------------------------------------------------------

# Patterns that match "Data Pill" variable expressions from the frontend:
# 1. state.get('variable_name') or state.get("variable_name")
_STATE_GET_PATTERN = re.compile(r"state\.get\(['\"](\w+)['\"]\)")
# 2. state.variable_name (dot notation)
_STATE_DOT_PATTERN = re.compile(r"state\.(\w+)")
# 3. result.variable_name (references to the immediately previous node result)
_RESULT_DOT_PATTERN = re.compile(r"result\.(\w+)")
# 4. {NodeLabel.output} style (curly-brace variable references from auto-wiring)
_CURLY_REF_PATTERN = re.compile(r"\{(\w+)\.(\w+)\}")


def resolve_variable_expressions(
    value: Any,
    state: Dict[str, Any],
    upstream_result: Any = None,
) -> Any:
    """Recursively resolve Data Pill variable expressions in config values.

    This function is the backend counterpart to the frontend "Data Pills" UI.
    It walks through config dicts/lists and replaces expression strings with
    actual runtime values from the graph state.

    Supported expression patterns:
    - ``state.get('variable_name')``  → ``state["variable_name"]``
    - ``state.variable_name``        → ``state["variable_name"]``
    - ``result.field``               → ``upstream_result["field"]``
    - ``{NodeLabel.output}``         → ``state["node_outputs"]["NodeLabel"]["output"]``

    Parameters
    ----------
    value : Any
        The config value to resolve. Can be a string, dict, list, or primitive.
    state : Dict[str, Any]
        The current graph state (contains ``node_outputs``, etc).
    upstream_result : Any, optional
        The result from the immediately upstream node execution.

    Returns
    -------
    Any
        The resolved value with all expressions replaced by actual values.
    """
    if isinstance(value, str):
        return _resolve_string_expression(value, state, upstream_result)
    elif isinstance(value, dict):
        return {k: resolve_variable_expressions(v, state, upstream_result) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_variable_expressions(item, state, upstream_result) for item in value]
    else:
        # Primitives (int, float, bool, None) pass through unchanged
        return value


def _resolve_string_expression(
    expr: str,
    state: Dict[str, Any],
    upstream_result: Any = None,
) -> Any:
    """Resolve a single string expression.

    If the entire string is a single expression (e.g. "state.get('count')"),
    return the raw value (preserving type). If the string contains embedded
    expressions mixed with text, perform string interpolation.
    """
    stripped = expr.strip()

    # --- Whole-string match (preserve original type) ---

    # state.get('var')
    m = _STATE_GET_PATTERN.fullmatch(stripped)
    if m:
        key = m.group(1)
        return state.get(key)

    # state.var
    m = _STATE_DOT_PATTERN.fullmatch(stripped)
    if m:
        key = m.group(1)
        return state.get(key)

    # result.field
    m = _RESULT_DOT_PATTERN.fullmatch(stripped)
    if m and upstream_result is not None:
        field = m.group(1)
        if isinstance(upstream_result, dict):
            return upstream_result.get(field)
        return getattr(upstream_result, field, None)

    # {NodeLabel.output}
    m = _CURLY_REF_PATTERN.fullmatch(stripped)
    if m:
        node_label = m.group(1)
        output_key = m.group(2)
        node_outputs = state.get("node_outputs", {})
        if isinstance(node_outputs, dict):
            node_data = node_outputs.get(node_label, {})
            if isinstance(node_data, dict):
                return node_data.get(output_key)
        return None

    # --- Inline interpolation (embedded expressions within text) ---
    # Only do this if there are potential expression markers in the string
    has_expressions = "state.get(" in expr or "state." in expr or "result." in expr or ("{" in expr and "}" in expr)
    if not has_expressions:
        return expr

    result = expr

    # Replace state.get('var') with value as string
    def _replace_state_get(m: re.Match) -> str:
        val = state.get(m.group(1), "")
        return str(val) if val is not None else ""

    result = _STATE_GET_PATTERN.sub(_replace_state_get, result)

    # Replace {NodeLabel.output} with value as string
    def _replace_curly_ref(m: re.Match) -> str:
        node_label = m.group(1)
        output_key = m.group(2)
        node_outputs = state.get("node_outputs", {})
        if isinstance(node_outputs, dict):
            node_data = node_outputs.get(node_label, {})
            if isinstance(node_data, dict):
                val = node_data.get(output_key, "")
                return str(val) if val is not None else ""
        return ""

    result = _CURLY_REF_PATTERN.sub(_replace_curly_ref, result)

    # Replace result.field with value (only if upstream_result is available)
    if upstream_result is not None:

        def _replace_result_dot(m: re.Match) -> str:
            field = m.group(1)
            if isinstance(upstream_result, dict):
                val = upstream_result.get(field, "")
            else:
                val = getattr(upstream_result, field, "")
            return str(val) if val is not None else ""

        result = _RESULT_DOT_PATTERN.sub(_replace_result_dot, result)

    # Replace state.var with value (do this LAST to avoid partial matches with state.get)
    def _replace_state_dot(m: re.Match) -> str:
        key = m.group(1)
        # Avoid replacing 'state.get' as it was already handled
        if key == "get":
            return str(m.group(0))
        val = state.get(key, "")
        return str(val) if val is not None else ""

    result = _STATE_DOT_PATTERN.sub(_replace_state_dot, result)

    return result
