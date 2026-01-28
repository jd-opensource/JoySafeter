"""
Tool Output Parser - Unified parser for extracting action data from tool outputs.

Handles various tool output formats:
- ToolMessage objects with content attribute
- Direct dict output
- JSON string output
- Plain string with embedded JSON
"""

import json
from typing import Any, Dict, Optional

from loguru import logger


def parse_tool_output(tool_output_raw: Any, tool_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Parse tool output to extract action data.

    Handles various output formats:
    - ToolMessage objects with content attribute
    - Direct dict output
    - JSON string output
    - Plain string with embedded JSON

    Args:
        tool_output_raw: Raw tool output (any type)
        tool_name: Optional name of the tool (for logging)

    Returns:
        Parsed action data dict, or None if parsing fails
    """
    if not tool_output_raw:
        return None

    tool_output = None

    # Extract actual content from tool output
    if hasattr(tool_output_raw, "content"):
        # Object with content attribute (like ToolMessage)
        tool_output = tool_output_raw.content
        logger.debug(f"[ToolOutputParser] Extracted content from tool output object: {type(tool_output)}")
    elif isinstance(tool_output_raw, dict):
        # Dict - check if it has content key or is the action directly
        if "content" in tool_output_raw:
            tool_output = tool_output_raw["content"]
        elif "type" in tool_output_raw:
            # Already the action dict
            tool_output = tool_output_raw
        else:
            tool_output = tool_output_raw
    else:
        # Direct output (string or other)
        tool_output = tool_output_raw

    # Try to parse tool output to get action
    if isinstance(tool_output, dict):
        return tool_output
    elif isinstance(tool_output, str):
        # String output - try to parse as JSON
        try:
            parsed = json.loads(tool_output)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Try to extract JSON from string using regex
            try:
                start_idx = tool_output.find('{"type"')
                if start_idx == -1:
                    start_idx = tool_output.find("{'type'")
                if start_idx != -1:
                    # Find matching closing brace
                    brace_count = 0
                    end_idx = start_idx
                    for i in range(start_idx, len(tool_output)):
                        if tool_output[i] == "{":
                            brace_count += 1
                        elif tool_output[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i + 1
                                break

                    if end_idx > start_idx:
                        json_str = tool_output[start_idx:end_idx]
                        # Replace single quotes with double quotes if needed
                        if json_str.startswith("{'") or "'type'" in json_str:
                            json_str = json_str.replace("'", '"')
                        parsed = json.loads(json_str)
                        if isinstance(parsed, dict):
                            return parsed
            except Exception as e:
                logger.debug(f"[ToolOutputParser] Failed to extract JSON from string: {e}")

    if tool_name:
        logger.warning(f"[ToolOutputParser] Could not parse tool output. tool={tool_name}, type={type(tool_output)}")
    return None
