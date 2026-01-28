#!/usr/bin/env python
# coding=utf-8
"""
Tool system for CodeAgent.

This module implements the Tool base class and @tool decorator for creating
production-ready tools with parameter validation and schema generation.
"""

from __future__ import annotations

import inspect
import json
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import wraps
from typing import Any, Union, get_args, get_origin, get_type_hints

# Authorized types for tool inputs/outputs
AUTHORIZED_TYPES = [
    "string",
    "boolean",
    "integer",
    "number",
    "image",
    "audio",
    "array",
    "object",
    "any",
    "null",
]

# Python type to JSON schema type conversion
TYPE_CONVERSION = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def python_type_to_json_type(python_type: type) -> str:
    """Convert a Python type to JSON schema type."""
    # Handle None type
    if python_type is type(None):
        return "null"

    # Handle basic types
    if python_type in TYPE_CONVERSION:
        return TYPE_CONVERSION[python_type]

    # Handle Optional types (Union with None)
    origin = get_origin(python_type)
    if origin is Union:
        args = get_args(python_type)
        # Filter out NoneType
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return python_type_to_json_type(non_none_args[0])
        return "any"

    # Handle List, Dict etc
    if origin is list:
        return "array"
    if origin is dict:
        return "object"

    # Default to any for complex types
    return "any"


def get_json_type(value: Any) -> str:
    """Get the JSON schema type of a value."""
    if value is None:
        return "null"
    return python_type_to_json_type(type(value))


def is_valid_name(name: str) -> bool:
    """Check if a name is a valid Python identifier and not a reserved keyword."""
    import keyword

    return name.isidentifier() and not keyword.iskeyword(name)


class BaseTool(ABC):
    """Abstract base class for all tools."""

    name: str

    @abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        pass


class Tool(BaseTool):
    """
    A base class for tools used by the agent.

    Subclass this and implement the `forward` method along with the following
    class attributes:

    - **name** (`str`) -- A unique name for the tool.
    - **description** (`str`) -- A description of what the tool does.
    - **inputs** (`dict`) -- A dictionary describing each input parameter.
    - **output_type** (`str`) -- The type of the output.
    - **output_schema** (`dict`, optional) -- JSON schema for structured output.

    Example:
        >>> class MyTool(Tool):
        ...     name = "my_tool"
        ...     description = "Does something useful"
        ...     inputs = {
        ...         "query": {"type": "string", "description": "The query to process"}
        ...     }
        ...     output_type = "string"
        ...
        ...     def forward(self, query: str) -> str:
        ...         return f"Processed: {query}"
    """

    name: str
    description: str
    inputs: dict[str, dict[str, str | type | bool]]
    output_type: str
    output_schema: dict[str, Any] | None = None

    def __init__(self, *args, **kwargs):
        self.is_initialized = False

    def __init_subclass__(cls, **kwargs):
        """Validate subclass attributes after class definition."""
        super().__init_subclass__(**kwargs)
        # Validation will be done on first instantiation

    def validate_arguments(self) -> None:
        """Validate that the tool has all required attributes."""
        required_attributes = {
            "description": str,
            "name": str,
            "inputs": dict,
            "output_type": str,
        }

        # Check required attributes exist and have correct types
        for attr, expected_type in required_attributes.items():
            attr_value = getattr(self, attr, None)
            if attr_value is None:
                raise TypeError(f"Tool must have attribute '{attr}'.")
            if not isinstance(attr_value, expected_type):
                raise TypeError(
                    f"Attribute '{attr}' should be {expected_type.__name__}, got {type(attr_value).__name__}."
                )

        # Validate name is a valid identifier
        if not is_valid_name(self.name):
            raise ValueError(f"Invalid tool name '{self.name}': must be a valid Python identifier")

        # Validate inputs schema
        for input_name, input_content in self.inputs.items():
            if not isinstance(input_content, dict):
                raise TypeError(f"Input '{input_name}' should be a dictionary.")

            if "type" not in input_content or "description" not in input_content:
                raise ValueError(f"Input '{input_name}' must have 'type' and 'description' keys.")

            # Validate type is authorized
            input_type = input_content["type"]
            if isinstance(input_type, str):
                if input_type not in AUTHORIZED_TYPES:
                    raise ValueError(
                        f"Input '{input_name}' has invalid type '{input_type}'. Must be one of {AUTHORIZED_TYPES}"
                    )
            elif isinstance(input_type, list):
                for t in input_type:
                    if t not in AUTHORIZED_TYPES:
                        raise ValueError(
                            f"Input '{input_name}' has invalid type '{t}'. Must be one of {AUTHORIZED_TYPES}"
                        )

        # Validate output type
        if self.output_type not in AUTHORIZED_TYPES:
            raise ValueError(f"output_type '{self.output_type}' must be one of {AUTHORIZED_TYPES}")

        # Validate forward method signature matches inputs
        if hasattr(self, "forward") and callable(self.forward):
            sig = inspect.signature(self.forward)
            params = [k for k in sig.parameters.keys() if k != "self"]
            expected_params = set(self.inputs.keys())
            actual_params = set(params)

            if actual_params != expected_params:
                raise ValueError(
                    f"Tool '{self.name}' forward() parameters {actual_params} don't match inputs {expected_params}"
                )

    def forward(self, *args, **kwargs) -> Any:
        """
        Execute the tool's main logic. Override this in subclasses.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments matching the inputs schema.

        Returns:
            The tool's output.
        """
        raise NotImplementedError("Implement forward() in your Tool subclass.")

    def setup(self) -> None:
        """
        Optional setup method for expensive operations.

        Override this for operations like loading models that should only
        happen once, on first use.
        """
        self.is_initialized = True

    def __call__(self, *args, **kwargs) -> Any:
        """
        Execute the tool.

        Handles lazy initialization and argument conversion.
        """
        if not self.is_initialized:
            self.setup()

        # Handle case where arguments are passed as a single dict
        if len(args) == 1 and len(kwargs) == 0 and isinstance(args[0], dict):
            potential_kwargs = args[0]
            if all(key in self.inputs for key in potential_kwargs):
                args = ()
                kwargs = potential_kwargs

        return self.forward(*args, **kwargs)

    def to_code_prompt(self) -> str:
        """Generate a code-style prompt for the LLM to understand this tool."""
        # Build signature
        args_parts = []
        for arg_name, arg_schema in self.inputs.items():
            arg_type = arg_schema["type"]
            nullable = arg_schema.get("nullable", False)
            if nullable:
                args_parts.append(f"{arg_name}: {arg_type} | None = None")
            else:
                args_parts.append(f"{arg_name}: {arg_type}")

        args_signature = ", ".join(args_parts)

        # Determine return type
        has_schema = self.output_schema is not None
        output_type = "dict" if has_schema else self.output_type

        tool_signature = f"({args_signature}) -> {output_type}"

        # Build docstring
        tool_doc = self.description

        if has_schema:
            tool_doc += "\n\nNote: This tool returns structured output as a dictionary."

        # Add arguments documentation
        if self.inputs:
            args_descriptions = "\n".join(
                f"{arg_name}: {arg_schema['description']}" for arg_name, arg_schema in self.inputs.items()
            )
            tool_doc += f"\n\nArgs:\n{textwrap.indent(args_descriptions, '    ')}"

        # Add return type documentation
        if has_schema:
            formatted_schema = json.dumps(self.output_schema, indent=4)
            indented_schema = textwrap.indent(formatted_schema, "        ")
            tool_doc += f"\n\nReturns:\n    dict: Structured output following this schema:\n{indented_schema}"

        tool_doc = f'"""{tool_doc}\n"""'
        return f"def {self.name}{tool_signature}:\n{textwrap.indent(tool_doc, '    ')}"

    def to_dict(self) -> dict:
        """Convert the tool to a dictionary representation."""
        result = {
            "name": self.name,
            "description": self.description,
            "inputs": self.inputs,
            "output_type": self.output_type,
        }
        if self.output_schema:
            result["output_schema"] = self.output_schema
        return result

    def __repr__(self) -> str:
        return f"Tool(name='{self.name}')"


def tool(func: Callable) -> Tool:
    """
    Decorator to convert a function into a Tool instance.

    The function should have:
    - Type hints for all parameters
    - A return type hint
    - A docstring with description and Args section

    Example:
        >>> @tool
        ... def web_search(query: str) -> str:
        ...     '''Search the web for information.
        ...
        ...     Args:
        ...         query: The search query
        ...     '''
        ...     return search_engine.search(query)

        >>> web_search.name
        'web_search'
        >>> web_search.inputs
        {'query': {'type': 'string', 'description': 'The search query'}}

    Args:
        func: The function to convert.

    Returns:
        A Tool instance wrapping the function.
    """
    # Get function name
    func_name = func.__name__

    # Get docstring
    docstring = inspect.getdoc(func) or ""

    # Parse docstring to get description and argument descriptions
    description, arg_descriptions = _parse_docstring(docstring)

    # Get type hints
    try:
        type_hints = get_type_hints(func)
    except Exception:
        type_hints = {}

    # Get signature
    sig = inspect.signature(func)

    # Build inputs schema
    inputs: dict[str, dict[str, str | bool]] = {}
    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue

        # Get type
        if param_name in type_hints:
            param_type = python_type_to_json_type(type_hints[param_name])
        else:
            param_type = "any"

        # Get description
        param_desc = arg_descriptions.get(param_name, f"The {param_name} parameter")

        # Check if nullable (has default of None)
        nullable = param.default is None and param.default is not inspect.Parameter.empty

        input_schema: dict[str, str | bool] = {
            "type": param_type,
            "description": param_desc,
        }
        if nullable or param.default is not inspect.Parameter.empty:
            input_schema["nullable"] = True

        inputs[param_name] = input_schema

    # Get output type
    if "return" in type_hints:
        output_type = python_type_to_json_type(type_hints["return"])
    else:
        output_type = "any"

    # Create dynamic Tool subclass
    class SimpleTool(Tool):
        def __init__(self):
            self.is_initialized = True

    # Set class attributes
    SimpleTool.name = func_name
    SimpleTool.description = description
    SimpleTool.inputs = inputs  # type: ignore[assignment]
    SimpleTool.output_type = output_type

    # Bind the function to forward
    @wraps(func)
    def forward_method(self, *args, **kwargs):
        return func(*args, **kwargs)

    SimpleTool.forward = forward_method  # type: ignore[method-assign]

    # Create instance
    tool_instance = SimpleTool()

    # Copy function attributes
    tool_instance.__doc__ = func.__doc__
    tool_instance.__module__ = func.__module__

    return tool_instance


def _parse_docstring(docstring: str) -> tuple[str, dict[str, str]]:
    """
    Parse a docstring to extract description and argument descriptions.

    Args:
        docstring: The docstring to parse.

    Returns:
        Tuple of (description, {arg_name: arg_description})
    """
    if not docstring:
        return "", {}

    lines = docstring.strip().split("\n")

    description_lines = []
    arg_descriptions = {}

    current_section = "description"
    current_arg = None
    current_arg_desc = []

    for line in lines:
        stripped = line.strip()

        # Check for Args section
        if stripped.lower() in ("args:", "arguments:", "parameters:"):
            current_section = "args"
            continue

        # Check for Returns section (end of args)
        if stripped.lower() in ("returns:", "return:", "yields:", "raises:", "examples:"):
            # Save last arg if any
            if current_arg and current_arg_desc:
                arg_descriptions[current_arg] = " ".join(current_arg_desc).strip()
            current_section = "other"
            continue

        if current_section == "description":
            if stripped:
                description_lines.append(stripped)

        elif current_section == "args":
            # Check if this is a new argument line (name: description)
            if ":" in stripped and not stripped.startswith(" "):
                # Save previous arg if any
                if current_arg and current_arg_desc:
                    arg_descriptions[current_arg] = " ".join(current_arg_desc).strip()

                # Parse new arg
                parts = stripped.split(":", 1)
                arg_name = parts[0].strip()
                # Handle type annotations in docstring like "query (str): description"
                if "(" in arg_name:
                    arg_name = arg_name.split("(")[0].strip()
                current_arg = arg_name
                current_arg_desc = [parts[1].strip()] if len(parts) > 1 else []

            elif current_arg and stripped:
                # Continuation of previous arg description
                current_arg_desc.append(stripped)

    # Save last arg if any
    if current_arg and current_arg_desc:
        arg_descriptions[current_arg] = " ".join(current_arg_desc).strip()

    description = " ".join(description_lines)

    return description, arg_descriptions


def validate_tool_arguments(tool: Tool, arguments: Any) -> None:
    """
    Validate tool arguments against the tool's input schema.

    Args:
        tool: The tool to validate against.
        arguments: The arguments to validate (dict or single value).

    Raises:
        ValueError: If an argument is missing or invalid.
        TypeError: If an argument has the wrong type.
    """
    if isinstance(arguments, dict):
        # Check for unknown arguments
        for key in arguments:
            if key not in tool.inputs:
                raise ValueError(f"Unknown argument '{key}' for tool '{tool.name}'")

        # Check each argument
        for key, value in arguments.items():
            expected_type = tool.inputs[key]["type"]
            actual_type = get_json_type(value)
            nullable = tool.inputs[key].get("nullable", False)

            # Allow null for nullable parameters
            if actual_type == "null" and nullable:
                continue

            # Allow integer for number type
            if actual_type == "integer" and expected_type == "number":
                continue

            # Allow any type if expected is "any"
            if expected_type == "any":
                continue

            # Handle list of types
            if isinstance(expected_type, list):
                if actual_type not in expected_type:
                    raise TypeError(f"Argument '{key}' has type '{actual_type}' but expected one of {expected_type}")
            elif actual_type != expected_type:
                raise TypeError(f"Argument '{key}' has type '{actual_type}' but expected '{expected_type}'")

        # Check required arguments are present
        for key, schema in tool.inputs.items():
            if key not in arguments and not schema.get("nullable", False):
                raise ValueError(f"Missing required argument '{key}' for tool '{tool.name}'")

    else:
        # Single value - check against first input
        if len(tool.inputs) != 1:
            raise ValueError(f"Tool '{tool.name}' expects {len(tool.inputs)} arguments, but received a single value")

        expected_type = list(tool.inputs.values())[0]["type"]
        actual_type = get_json_type(arguments)

        if expected_type != "any" and actual_type != expected_type:
            # Allow integer for number
            if not (actual_type == "integer" and expected_type == "number"):
                raise TypeError(f"Argument has type '{actual_type}' but expected '{expected_type}'")


class FinalAnswerTool(Tool):
    """Built-in tool for returning the final answer."""

    name = "final_answer"
    description = "Return the final answer to the user's task."
    inputs = {"answer": {"type": "any", "description": "The final answer to return."}}
    output_type = "any"

    def forward(self, answer: Any) -> Any:
        """Return the final answer."""
        return answer


def create_final_answer_tool() -> FinalAnswerTool:
    """Create a final_answer tool instance."""
    return FinalAnswerTool()


__all__ = [
    "AUTHORIZED_TYPES",
    "Tool",
    "tool",
    "validate_tool_arguments",
    "FinalAnswerTool",
    "create_final_answer_tool",
    "python_type_to_json_type",
    "get_json_type",
]
