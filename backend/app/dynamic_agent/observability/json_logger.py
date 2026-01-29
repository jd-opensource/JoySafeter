"""
JSON File Logging Callback for Agent Execution.

This module provides a dedicated callback handler for persisting agent execution
events to JSONL files. This centralizes all file logging logic to prevent
duplicate writes from multiple UI handlers.
"""

import logging
from typing import Any, Dict, List

from langchain_core.callbacks import BaseCallbackHandler

from app.dynamic_agent.observability.langfuse import write_json_log

logger = logging.getLogger(__name__)


class JsonFileLoggingCallback(BaseCallbackHandler):
    """
    Dedicated callback handler for persisting events to JSONL files.

    This handler is the ONLY place where write_json_log should be called
    for LLM and tool events. UI handlers (RichConsoleCallback, ChainDebugCallback)
    should focus only on display logic.
    """

    def __init__(self):
        """Initialize the JSON file logging callback."""
        self.depth = 0

    def _convert_messages_to_log_format(self, messages: List) -> List[Dict]:
        """
        Convert LangChain messages to log format.
        """
        ROLE_MAP = {"human": "user", "ai": "assistant"}
        result = []

        for msg in messages:
            if hasattr(msg, "type"):
                role = ROLE_MAP.get(msg.type, msg.type)
                content = getattr(msg, "content", "") or ""
            elif hasattr(msg, "role"):
                role = ROLE_MAP.get(msg.role, msg.role)
                content = getattr(msg, "content", "") or ""
            elif isinstance(msg, dict):
                role = ROLE_MAP.get(msg.get("role", ""), msg.get("role", "unknown"))
                content = msg.get("content", "")
            else:
                continue

            entry = {"role": role, "content": content}

            # Extract tool_calls (for assistant messages)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                        "name": tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
                        "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
                    }
                    for tc in msg.tool_calls
                ]
            elif isinstance(msg, dict) and msg.get("tool_calls"):
                entry["tool_calls"] = msg["tool_calls"]

            # Extract tool_call_id (for tool messages)
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            elif isinstance(msg, dict) and msg.get("tool_call_id"):
                entry["tool_call_id"] = msg["tool_call_id"]

            result.append(entry)

        return result

    # =========================================================================
    # LLM Callbacks
    # =========================================================================
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Called when LLM starts processing."""
        invocation_params = kwargs.get("invocation_params", {})
        messages = kwargs.get("messages", [])
        name = (
            serialized.get("id", ["unknown"])[-1]
            if isinstance(serialized.get("id"), list)
            else serialized.get("id", "<llm>")
        )

        all_messages = self._convert_messages_to_log_format(messages)

        system_prompt = None
        for msg in all_messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content")
                break

        write_json_log(
            "LLM_CALL",
            {
                "model": invocation_params.get("model", name),
                "system_prompt": system_prompt,
                "messages": all_messages,
                "temperature": invocation_params.get("temperature"),
                "max_tokens": invocation_params.get("max_tokens"),
            },
        )
        self.depth += 1

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: List, **kwargs) -> None:
        """Called when chat model starts - captures full message list."""
        invocation_params = kwargs.get("invocation_params", {})
        name = (
            serialized.get("id", ["unknown"])[-1]
            if serialized and isinstance(serialized.get("id"), list)
            else (serialized.get("id", "<chat>") if serialized else "<chat>")
        )

        all_messages = messages[0] if messages else []
        formatted_messages = self._convert_messages_to_log_format(all_messages)

        system_prompt = None
        non_system_messages = []
        for msg in formatted_messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content")
            else:
                non_system_messages.append(msg)

        write_json_log(
            "LLM_INPUT",
            {
                "model": invocation_params.get("model", name),
                "system_prompt": system_prompt,
                "messages": non_system_messages,
                "message_count": len(non_system_messages),
                "temperature": invocation_params.get("temperature"),
                "max_tokens": invocation_params.get("max_tokens"),
            },
        )
        self.depth += 1

    def on_llm_end(self, response, **kwargs) -> None:
        """Called when LLM completes processing."""
        self.depth = max(0, self.depth - 1)

        try:
            content = None
            tool_calls = []
            usage = {}
            finish_reason = None

            if hasattr(response, "generations") and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "message"):
                            msg = gen.message
                            content = msg.content if hasattr(msg, "content") else str(msg)
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                tool_calls = [
                                    {
                                        "name": tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
                                        "arguments": tc.get("args", {})
                                        if isinstance(tc, dict)
                                        else getattr(tc, "args", {}),
                                    }
                                    for tc in msg.tool_calls
                                ]
                        elif hasattr(gen, "text"):
                            content = gen.text

                        if hasattr(gen, "generation_info") and gen.generation_info:
                            finish_reason = gen.generation_info.get("finish_reason")

            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                usage = {
                    "prompt_tokens": token_usage.get("prompt_tokens"),
                    "completion_tokens": token_usage.get("completion_tokens"),
                    "total_tokens": token_usage.get("total_tokens"),
                }

            write_json_log(
                "LLM_RESPONSE",
                {
                    "content": content,
                    "tool_calls": tool_calls,
                    "usage": usage,
                    "finish_reason": finish_reason,
                },
            )
        except Exception as e:
            logger.debug(f"Failed to log LLM response: {e}")

    def on_llm_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when LLM encounters an error."""
        self.depth = max(0, self.depth - 1)
        import traceback

        write_json_log(
            "ERROR",
            {
                "error_type": "LLM_ERROR",
                "message": str(error),
                "stacktrace": traceback.format_exc(),
            },
        )

    # =========================================================================
    # Tool Callbacks
    # =========================================================================
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Called when a tool starts executing."""
        run_id = str(kwargs.get("run_id", ""))
        name = serialized.get("name", serialized.get("id", "<tool>"))

        try:
            input_obj = eval(input_str) if isinstance(input_str, str) else input_str
        except (SyntaxError, ValueError, NameError):
            input_obj = {"raw": input_str}

        write_json_log(
            "TOOL_CALL",
            {
                "phase": "start",
                "tool_name": name,
                "run_id": run_id,
                "input": input_obj,
            },
        )
        self.depth += 1

    def on_tool_end(self, output: Any, **kwargs) -> None:
        """Called when a tool completes."""
        self.depth = max(0, self.depth - 1)
        run_id = str(kwargs.get("run_id", ""))
        name = kwargs.get("name", "<tool>")

        # Get output content
        if hasattr(output, "content"):
            content = output.content
        else:
            content = output

        # Convert non-string content to string
        import json

        if isinstance(content, (list, dict)):
            try:
                content = json.dumps(content, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                content = str(content)
        elif not isinstance(content, str):
            content = str(content)

        content_len = len(content) if isinstance(content, str) else 0
        write_json_log(
            "TOOL_CALL",
            {
                "phase": "end",
                "tool_name": name,
                "run_id": run_id,
                "output": content if content_len < 10000 else content[:10000] + "...[truncated]",
                "success": True,
            },
        )

    def on_tool_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when a tool encounters an error."""
        self.depth = max(0, self.depth - 1)
        name = kwargs.get("name", "<tool>")
        run_id = str(kwargs.get("run_id", ""))
        import traceback

        write_json_log(
            "ERROR",
            {
                "error_type": "TOOL_ERROR",
                "tool_name": name,
                "run_id": run_id,
                "message": str(error),
                "stacktrace": traceback.format_exc(),
            },
        )

    # =========================================================================
    # Chain Callbacks
    # =========================================================================
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain starts."""
        pass  # No logging for chain start

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Called when a chain completes."""
        pass  # No logging for chain end

    def on_chain_error(self, error: BaseException, *, run_id=None, parent_run_id=None, **kwargs) -> None:  # type: ignore[override]
        """Called when a chain encounters an error."""
        import traceback

        write_json_log(
            "ERROR",
            {
                "error_type": "CHAIN_ERROR",
                "message": str(error),
                "stacktrace": traceback.format_exc(),
            },
        )
