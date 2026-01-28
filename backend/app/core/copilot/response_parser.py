"""
Response Parser - Parse and extract information from Copilot responses.

Provides functions for parsing streaming JSON responses and extracting
thought steps for real-time UI updates.
"""

import json
import re
from typing import Any, Dict, List, Optional

from app.core.copilot.action_types import (
    CopilotResponse,
    GraphAction,
    GraphActionType,
)


def try_extract_thought_field(json_content: str) -> Optional[str]:
    """
    Try to extract the 'thought' field from partial JSON content during streaming.

    Uses multiple strategies:
    1. Try to parse as complete JSON first
    2. Fall back to regex extraction if JSON parsing fails

    Args:
        json_content: Partial or complete JSON string

    Returns:
        The thought content if found, None otherwise.
    """
    # Strategy 1: Try parsing as complete JSON
    try:
        data = json.loads(json_content)
        if isinstance(data, dict) and "thought" in data:
            thought = data.get("thought", "")
            if thought:
                return str(thought)
    except (json.JSONDecodeError, ValueError):
        # JSON not complete yet, try regex extraction
        pass

    # Strategy 2: Use regex to extract thought field (handles partial JSON)
    # Match "thought": "..." with proper handling of escaped quotes and newlines
    pattern = r'"thought"\s*:\s*"((?:[^"\\]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*)"'

    match = re.search(pattern, json_content, re.DOTALL)
    if match:
        thought_content = match.group(1)
        # Unescape JSON string (handle \n, \", etc.)
        try:
            thought_content = json.loads(f'"{thought_content}"')
            return str(thought_content) if thought_content is not None else None
        except (json.JSONDecodeError, ValueError):
            # If unescaping fails, might be incomplete - return None to wait for more data
            return None

    return None


def parse_thought_to_steps(thought: str) -> List[Dict[str, Any]]:
    """
    Parse the thought field into structured steps.

    Expected format examples:
    1. Numbered list: "1. Step one\n2. Step two\n3. Step three"
    2. Bullet points: "- Step one\n- Step two"
    3. Plain text with line breaks

    Args:
        thought: Raw thought string from AI response

    Returns:
        List of step objects with index and content.
    """
    if not thought or not thought.strip():
        return []

    NUMBERED_PATTERNS = [r"^\d+\.", r"^\d+\)", r"^Step \d+:", r"^步骤\d+："]
    BULLET_PATTERN = r"^[-*•]\s+"

    steps: List[Dict[str, Any]] = []
    lines = thought.strip().split("\n")
    current_step_index = 1
    current_content: List[str] = []

    def finish_current_step() -> None:
        """Helper to finish current step and reset state."""
        nonlocal current_step_index, current_content
        if current_content:
            steps.append({"index": current_step_index, "content": " ".join(current_content).strip()})
            current_step_index += 1
            current_content = []

    for line in lines:
        line = line.strip()
        if not line:
            finish_current_step()
            continue

        # Check for numbered list pattern (1. 2. 3. etc.)
        numbered_match = False
        for pattern in NUMBERED_PATTERNS:
            if re.match(pattern, line, re.IGNORECASE):
                finish_current_step()
                # Extract content after number
                content = re.sub(pattern, "", line, flags=re.IGNORECASE).strip()
                if content:
                    current_content.append(content)
                numbered_match = True
                break

        # Check for bullet points (-, *, •)
        if not numbered_match and re.match(BULLET_PATTERN, line):
            finish_current_step()
            # Extract content after bullet
            content = re.sub(BULLET_PATTERN, "", line).strip()
            if content:
                current_content.append(content)
        elif not numbered_match:
            # Regular line - add to current content
            current_content.append(line)

    # Add final step if there's content
    finish_current_step()

    # If no structured format detected, treat entire thought as one step
    if not steps:
        steps.append({"index": 1, "content": thought.strip()})

    return steps


def parse_copilot_response(response_text: str) -> CopilotResponse:
    """
    Parse a complete Copilot response from JSON text.

    Args:
        response_text: Complete JSON response string

    Returns:
        Parsed CopilotResponse object

    Raises:
        json.JSONDecodeError: If response is not valid JSON
        ValueError: If response structure is invalid
    """
    if not response_text:
        raise ValueError("Empty response text")

    result = json.loads(response_text)

    if not isinstance(result, dict):
        raise ValueError("Response must be a JSON object")

    actions = []
    for action in result.get("actions", []):
        if isinstance(action, dict):
            action_type = action.get("type")
            if action_type and hasattr(GraphActionType, action_type):
                actions.append(
                    GraphAction(
                        type=GraphActionType(action_type),
                        payload=action.get("payload", {}),
                        reasoning=action.get("reasoning", ""),
                    )
                )

    return CopilotResponse(
        message=result.get("message", ""),
        actions=actions,
    )


def extract_actions_from_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[GraphAction]:
    """
    Extract GraphAction objects from agent tool call results.

    When using the Agent with tools mode, each tool call returns
    an action dict that needs to be collected.

    Args:
        tool_calls: List of tool call result dictionaries

    Returns:
        List of GraphAction objects
    """
    actions = []

    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue

        action_type = tool_call.get("type")
        if not action_type:
            continue

        # Validate action type
        try:
            action_type_enum = GraphActionType(action_type)
        except ValueError:
            continue

        actions.append(
            GraphAction(
                type=action_type_enum,
                payload=tool_call.get("payload", {}),
                reasoning=tool_call.get("reasoning", ""),
            )
        )

    return actions


def extract_actions_from_agent_result(
    result: Dict[str, Any],
    filter_non_actions: bool = False,
) -> List[GraphAction]:
    """
    Extract GraphAction objects from agent result messages.

    Looks for tool messages in the result and extracts actions from them.
    Handles various message formats and content types.

    Args:
        result: Agent result dict with 'messages' key
        filter_non_actions: Whether to filter out NON_ACTION_TYPES (default: False)

    Returns:
        List of GraphAction objects
    """
    import json
    import re

    from loguru import logger

    actions = []
    output_messages = result.get("messages", [])

    logger.info(f"[ResponseParser] Extracting actions from {len(output_messages)} messages")

    for idx, msg in enumerate(output_messages):
        logger.debug(
            f"[ResponseParser] Message {idx}: type={getattr(msg, 'type', 'unknown')}, class={msg.__class__.__name__}"
        )

        # Check for tool messages (contain actual results)
        if hasattr(msg, "type") and msg.type == "tool":
            logger.info(f"[ResponseParser] Found tool message: {msg}")
            try:
                content = msg.content
                logger.debug(f"[ResponseParser] Tool message content type: {type(content)}, content: {content}")

                if isinstance(content, str):
                    try:
                        action_data = json.loads(content)
                    except json.JSONDecodeError:
                        # Try to extract JSON from string
                        json_match = re.search(r'\{[^{}]*"type"[^{}]*\}', content)
                        if json_match:
                            action_data = json.loads(json_match.group())
                        else:
                            logger.warning(f"[ResponseParser] Could not parse tool message content as JSON: {content}")
                            continue
                else:
                    action_data = content

                # Use the unified expand_action_payload method
                expanded = expand_action_payload(action_data, filter_non_actions=filter_non_actions)
                if not expanded:
                    logger.warning(f"[ResponseParser] Tool message is not an action payload: {action_data}")
                    continue

                for a in expanded:
                    logger.info(f"[ResponseParser] Extracted action: {a.get('type')}")
                    action_type = GraphActionType(a["type"])
                    actions.append(
                        GraphAction(
                            type=action_type,
                            payload=a.get("payload", {}),
                            reasoning=a.get("reasoning", ""),
                        )
                    )
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.error(f"[ResponseParser] Error extracting action: {e}")
                pass

    logger.info(f"[ResponseParser] Extracted {len(actions)} actions from result")
    return actions


def expand_action_payload(payload: Any, filter_non_actions: bool = True) -> List[Dict[str, Any]]:
    """
    Normalize tool outputs into a list of action dicts.

    Supported shapes:
    - {"type": "...", "payload": {...}, "reasoning": "..."}  -> [action]
    - {"actions": [action, action, ...], ...}                -> actions

    Args:
        payload: Tool output payload (dict, string, or None)
        filter_non_actions: Whether to filter out NON_ACTION_TYPES (default: True)

    Returns:
        List of action dicts
    """
    from loguru import logger

    NON_ACTION_TYPES = {"THINK", "think"}  # Self-reflection tool output

    if payload is None:
        return []
    if isinstance(payload, dict):
        action_type = payload.get("type")
        # Skip non-action types if filtering is enabled
        if filter_non_actions and action_type in NON_ACTION_TYPES:
            logger.debug(f"[ResponseParser] Skipping non-action type: {action_type}")
            return []
        # Single action
        if action_type and isinstance(payload.get("payload", {}), dict):
            return [payload]
        # Batch actions
        actions = payload.get("actions")
        if isinstance(actions, list):
            out: List[Dict[str, Any]] = []
            for item in actions:
                if isinstance(item, dict) and "type" in item:
                    item_type = item.get("type")
                    if not filter_non_actions or item_type not in NON_ACTION_TYPES:
                        out.append(item)
            return out
    return []
