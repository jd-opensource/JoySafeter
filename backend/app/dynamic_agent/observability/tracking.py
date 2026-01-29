"""
LangChain Callback Handler for Task Execution Tracking (Queue-based).

This module provides a custom AsyncCallbackHandler that intercepts LangChain
agent execution events and sends them to a queue for database persistence.
This avoids cross-event-loop database access issues.
"""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from loguru import logger

from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.observability.tracking_events import (
    ChatModelEndEvent,
    ChatModelStartEvent,
    LLMEndEvent,
    LLMStartEvent,
    ToolEndEvent,
    ToolErrorEvent,
    ToolStartEvent,
    get_tracking_queue,
)

# Global counter for task iteration counts (task_id -> count)
_task_iteration_counts: Dict[UUID, int] = {}


def get_task_iteration_count(task_id: UUID) -> int:
    """Get the current iteration count for a task_id."""
    return _task_iteration_counts.get(task_id, 0)


def reset_task_iteration_count(task_id: UUID) -> None:
    """Reset the iteration count for a task_id."""
    if task_id in _task_iteration_counts:
        del _task_iteration_counts[task_id]


def _get_current_task_id() -> Optional[UUID]:
    """Get current task_id from MetadataContext."""
    task_id = MetadataContext.get_value("task_id")
    if task_id:
        if isinstance(task_id, UUID):
            logger.debug(f"[Tracking] Got task_id from context (UUID): {task_id}")
            return task_id
        try:
            uuid = UUID(str(task_id))
            logger.debug(f"[Tracking] Got task_id from context (converted): {uuid}")
            return uuid
        except (ValueError, TypeError):
            logger.warning(f"Invalid task_id in context: {task_id}")
    else:
        logger.debug("[Tracking] No task_id in MetadataContext")
    return None


class TaskExecutionTrackingHandler(AsyncCallbackHandler):
    """
    AsyncCallbackHandler for tracking task execution steps (Queue-based).

    Intercepts LangChain callbacks and sends events to a queue for database
    persistence. The queue is processed by TrackingEventProcessor in the main
    event loop, avoiding cross-event-loop database access issues.

    Uses MetadataContext to get the current task_id, allowing a single handler
    instance to serve multiple agents with different task contexts.
    """

    def __init__(self):
        """Initialize the tracking handler (queue-based, no DAO needed)."""
        self._skip_run_ids: set[str] = set()
        self._skip_run_ids_max = int(os.getenv("TRACKING_SKIP_RUN_IDS_MAX", "5000"))

    def _increment_task_iteration(self, task_id: UUID) -> int:
        """Increment the iteration count for a task_id and return the new count."""
        global _task_iteration_counts
        if task_id not in _task_iteration_counts:
            _task_iteration_counts[task_id] = 0
        _task_iteration_counts[task_id] += 1
        count = _task_iteration_counts[task_id]
        logger.debug(f"[Tracking] Incremented iteration count for task {task_id}: {count}")
        return count

    def _should_skip_run(self, run_id: str) -> bool:
        return bool(run_id) and run_id in self._skip_run_ids

    def _mark_skip_run(self, run_id: str) -> None:
        if not run_id:
            return
        self._skip_run_ids.add(run_id)
        if len(self._skip_run_ids) > self._skip_run_ids_max:
            self._skip_run_ids.clear()

    def _get_step_key(self, task_id: Optional[UUID], run_id: str) -> str:
        """Generate step key for matching start/end events."""
        return f"{task_id}:{run_id}" if task_id else run_id

    def _send_event(self, event):
        """Send event to the tracking queue (non-blocking)."""
        try:
            queue = get_tracking_queue()
            # Use put_nowait to avoid blocking in callback
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("[Tracking] Event queue full, dropping event")
        except Exception as e:
            logger.error(f"[Tracking] Error sending event to queue: {e}")

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts execution."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping tool_start tracking")
                return

            # Increment iteration count when tool starts
            iteration_count = self._increment_task_iteration(task_id)

            tool_name = serialized.get("name", "unknown_tool")
            logger.info(
                f"[Tracking] on_tool_start: {tool_name}, run_id={run_id}, task_id={task_id}, iteration={iteration_count}"
            )

            # Pre-generate step_id
            pre_generated_step_id = uuid4()

            # Set step_id in MetadataContext for other components to use
            MetadataContext.update(
                {
                    "current_step_id": str(pre_generated_step_id),
                    "current_step_type": "tool",
                    "current_step_name": tool_name,
                }
            )

            # Convert input to serializable format
            input_value = input_str
            if hasattr(input_str, "content"):
                input_value = input_str.content
            elif not isinstance(input_str, str):
                input_value = str(input_str)

            # Parse input to dict if possible
            try:
                input_data = (
                    json.loads(input_value) if isinstance(input_value, str) else {"raw_input": str(input_value)}
                )
            except (json.JSONDecodeError, TypeError):
                input_data = {"raw_input": input_value}

            # Create and send event with pre-generated step_id
            step_key = self._get_step_key(task_id, run_id)
            event = ToolStartEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                tool_name=tool_name,
                input_data=input_data,
                pre_generated_step_id=pre_generated_step_id,
            )
            self._send_event(event)

            logger.debug(
                f"[Tracking] Queued tool_start for {tool_name} (step_key={step_key}, step_id={pre_generated_step_id}, iteration={iteration_count})"
            )

        except Exception as e:
            logger.error(f"Error in on_tool_start: {e}", exc_info=True)

    async def on_tool_end(
        self,
        output: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool finishes execution."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping tool_end tracking")
                return

            logger.info(f"[Tracking] on_tool_end: run_id={run_id}, task_id={task_id}")

            if not run_id:
                logger.warning("[Tracking] No run_id in on_tool_end")
                return

            # Convert output to serializable format
            output_str = output
            if hasattr(output, "content"):
                output_str = output.content
            elif not isinstance(output, str):
                output_str = str(output)

            # Parse output to dict if possible
            try:
                output_data = json.loads(output_str) if isinstance(output_str, str) else {"raw_output": str(output_str)}
            except (json.JSONDecodeError, TypeError):
                output_data = {"raw_output": output_str}

            # Create and send event
            step_key = self._get_step_key(task_id, run_id)
            event = ToolEndEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                output_data=output_data,
            )
            self._send_event(event)

            logger.debug(f"[Tracking] Queued tool_end for step_key={step_key}")

        except Exception as e:
            logger.error(f"Error in on_tool_end: {e}", exc_info=True)

    async def on_tool_error(
        self,
        error: BaseException,  # type: ignore[override]
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a tool call fails."""
        run_id_str = str(run_id) if run_id else ""
        if self._should_skip_run(run_id_str):
            return

        try:
            logger.error(f"Tool error: {error}", exc_info=True)

            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping tool_error tracking")
                return

            if not run_id:
                logger.warning("[Tracking] No run_id in on_tool_error")
                return

            # Create and send event
            step_key = self._get_step_key(task_id, run_id_str)
            event = ToolErrorEvent(
                task_id=task_id,
                run_id=run_id_str,
                step_key=step_key,
                error_message=str(error),
            )
            self._send_event(event)

            logger.debug(f"[Tracking] Queued tool_error for step_key={step_key}")

        except Exception as e:
            logger.error(f"Error in on_tool_error: {e}", exc_info=True)

    async def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        """Called when ChatModel starts generating."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping chat_model_start tracking")
                return

            # Extract model name from serialized data
            model_name = "unknown_model"
            if serialized:
                model_name = serialized.get("name") or serialized.get("id", "unknown_model")

            # Increment iteration count when ChatModel starts
            iteration_count = self._increment_task_iteration(task_id)

            logger.info(
                f"[Tracking] on_chat_model_start: model={model_name}, run_id={run_id}, task_id={task_id}, iteration={iteration_count}"
            )

            # Pre-generate step_id
            pre_generated_step_id = uuid4()

            # Set step_id in MetadataContext for other components to use
            # MetadataContext.update({
            #     "current_step_id": str(pre_generated_step_id),
            #     "current_step_type": "llm",
            #     "current_step_name": f"LLM: {model_name}"
            # })

            # Convert messages to serializable format
            messages_data = []
            for msg_list in messages:
                msg_list_data = []
                for msg in msg_list:
                    if hasattr(msg, "model_dump"):
                        msg_list_data.append(msg.model_dump())
                    elif hasattr(msg, "dict"):
                        msg_list_data.append(msg.dict())
                    else:
                        msg_list_data.append(
                            {
                                "type": msg.__class__.__name__,
                                "content": str(msg.content) if hasattr(msg, "content") else str(msg),
                            }
                        )
                messages_data.append(msg_list_data)

            # Create and send event with pre-generated step_id
            step_key = self._get_step_key(task_id, run_id)
            event = ChatModelStartEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                model_name=model_name,
                messages_data=messages_data,
                pre_generated_step_id=pre_generated_step_id,
            )
            self._send_event(event)

            logger.debug(
                f"[Tracking] Queued chat_model_start for {model_name} (step_key={step_key}, step_id={pre_generated_step_id}, iteration={iteration_count})"
            )

        except Exception as e:
            logger.error(f"Error in on_chat_model_start: {e}", exc_info=True)

    async def on_chat_model_end(
        self,
        message: BaseMessage,
        **kwargs: Any,
    ) -> None:
        """Called when ChatModel finishes generating."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping chat_model_end tracking")
                return

            logger.info(f"[Tracking] on_chat_model_end: run_id={run_id}, task_id={task_id}")

            if not run_id:
                logger.warning("[Tracking] No run_id in on_chat_model_end")
                return

            # Extract response data from BaseMessage
            output_data = {}
            if hasattr(message, "dict"):
                output_data = message.dict()
            elif hasattr(message, "model_dump"):
                output_data = message.model_dump()
            else:
                output_data = {
                    "type": message.__class__.__name__,
                    "content": str(message.content) if hasattr(message, "content") else str(message),
                }

            # Create and send event
            step_key = self._get_step_key(task_id, run_id)
            event = ChatModelEndEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                output_data=output_data,
            )
            self._send_event(event)

            logger.debug(f"[Tracking] Queued chat_model_end for step_key={step_key}")

        except Exception as e:
            logger.error(f"Error in on_chat_model_end: {e}", exc_info=True)

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        **kwargs: Any,
    ) -> None:
        """Called when LLM starts generating."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping llm_start tracking")
                return

            invocation_params = kwargs.get("invocation_params", {})
            model_name = invocation_params.get("model_name", "unknown_model")

            # Increment iteration count when LLM starts
            iteration_count = self._increment_task_iteration(task_id)

            logger.info(
                f"[Tracking] on_llm_start: model={model_name}, run_id={run_id}, task_id={task_id}, iteration={iteration_count}"
            )

            # Pre-generate step_id
            pre_generated_step_id = uuid4()

            # Set step_id in MetadataContext for other components to use
            MetadataContext.update(
                {
                    "current_step_id": str(pre_generated_step_id),
                    "current_step_type": "llm",
                    "current_step_name": f"LLM: {model_name}",
                }
            )

            # Create and send event with pre-generated step_id
            step_key = self._get_step_key(task_id, run_id)
            event = LLMStartEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                model_name=model_name,
                prompts=prompts,
                invocation_params=invocation_params,
                pre_generated_step_id=pre_generated_step_id,
            )
            self._send_event(event)

            logger.debug(
                f"[Tracking] Queued llm_start for {model_name} (step_key={step_key}, step_id={pre_generated_step_id}, iteration={iteration_count})"
            )

        except Exception as e:
            logger.error(f"Error in on_llm_start: {e}", exc_info=True)

    async def on_llm_end(
        self,
        response: Any,
        **kwargs: Any,
    ) -> None:
        """Called when LLM finishes generating."""
        run_id = str(kwargs.get("run_id", ""))
        if self._should_skip_run(run_id):
            return

        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping llm_end tracking")
                return

            logger.info(f"[Tracking] on_llm_end: run_id={run_id}, task_id={task_id}")

            if not run_id:
                logger.warning("[Tracking] No run_id in on_llm_end")
                return

            # Extract response data
            output_data = {}
            if hasattr(response, "generations"):
                generations = response.generations
                generations_data = []
                tool_calls_list = []

                for gen_list in generations:
                    gen_data = []
                    for gen in gen_list:
                        gen_dict = {"text": gen.text, "generation_info": gen.generation_info}

                        if hasattr(gen, "message"):
                            msg = gen.message
                            if hasattr(msg, "tool_calls") and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tool_call_dict = {
                                        "id": getattr(tc, "id", None),
                                        "name": tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None),
                                        "args": tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {}),
                                        "type": getattr(tc, "type", "function"),
                                    }
                                    tool_calls_list.append(tool_call_dict)

                        gen_data.append(gen_dict)
                    generations_data.append(gen_data)

                output_data = {
                    "generations": generations_data,
                    "llm_output": response.llm_output,
                    "generation_count": sum(len(gen_list) for gen_list in generations),
                }

                if tool_calls_list:
                    output_data["tool_calls"] = tool_calls_list
                    output_data["tool_call_count"] = len(tool_calls_list)
            else:
                output_data = {"response": str(response)}

            # Create and send event
            step_key = self._get_step_key(task_id, run_id)
            event = LLMEndEvent(
                task_id=task_id,
                run_id=run_id,
                step_key=step_key,
                output_data=output_data,
            )
            self._send_event(event)

            logger.debug(f"[Tracking] Queued llm_end for step_key={step_key}")

        except Exception as e:
            logger.error(f"Error in on_llm_end: {e}", exc_info=True)

    async def on_llm_error(
        self,
        error: BaseException,  # type: ignore[override]
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when LLM call fails."""
        try:
            logger.error(f"LLM error: {error}", exc_info=True)

            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping llm_error tracking")
                return

            if not run_id:
                logger.warning("[Tracking] No run_id in on_llm_error")
                return

            # For now, log the error but don't send to queue
            # LLM errors are typically handled at higher level
            logger.debug(f"[Tracking] LLM error for run_id={run_id}: {error}")

        except Exception as e:
            logger.error(f"Error in on_llm_error: {e}", exc_info=True)

    async def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Called when a chain starts execution."""
        try:
            task_id = _get_current_task_id()
            if not task_id:
                logger.debug("No task_id in context, skipping chain_start tracking")
                return

            chain_name = "unknown_chain"
            if serialized:
                chain_name = serialized.get("name", "unknown_chain")

            logger.debug(f"Chain started: {chain_name} (task_id={task_id})")

        except Exception as e:
            logger.error(f"Error in on_chain_start: {e}", exc_info=True)

    async def on_chain_end(
        self,
        outputs: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Called when a chain finishes execution."""
        try:
            task_id = _get_current_task_id()
            logger.debug(f"Chain ended for task {task_id}")

        except Exception as e:
            logger.error(f"Error in on_chain_end: {e}", exc_info=True)

    async def on_chain_error(
        self,
        error: BaseException,  # type: ignore[override]
        *,
        run_id: UUID | None = None,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a chain execution fails."""
        try:
            if error is None:
                # This happens when model returns no tool calls when expected
                logger.warning(
                    "Chain error callback triggered but error object is None (likely model returned no tool calls when expected)"
                )
            else:
                # Log error without exc_info to avoid misleading "NoneType: None" output
                # In async callback contexts, sys.exc_info() is often empty/unreliable
                logger.error(f"Chain error: {error}")

        except Exception as e:
            logger.error(f"Error in on_chain_error: {e}")
