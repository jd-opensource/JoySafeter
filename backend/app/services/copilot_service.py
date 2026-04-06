"""
Copilot Service - Business logic for the Copilot feature.

Provides both streaming and non-streaming interfaces for generating
graph actions based on user requests.
"""

import uuid as uuid_lib
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from app.core.copilot.action_applier import apply_actions_to_graph_state
from app.core.copilot.action_types import (
    CopilotResponse,
    GraphAction,
    GraphActionType,
)
from app.core.copilot.action_validator import (
    extract_existing_node_ids,
    filter_invalid_actions,
    validate_actions,
)
from app.core.copilot.agent import get_copilot_agent
from app.core.copilot.exceptions import (
    CopilotAgentError,
    CopilotCredentialError,
    CopilotLLMError,
    CopilotValidationError,
)
from app.core.copilot.message_builder import build_langchain_messages
from app.core.copilot.response_parser import (
    expand_action_payload,
    extract_actions_from_agent_result,
    parse_thought_to_steps,
    try_extract_thought_field,
)
from app.core.copilot.tool_output_parser import parse_tool_output
from app.core.copilot.tools import reset_node_registry
from app.core.model.utils.credential_resolver import LLMCredentialResolver
from app.repositories.auth_user import AuthUserRepository
from app.services.graph_service import GraphService


class CopilotService:
    """
    Service for Copilot graph action generation.

    Supports both streaming (SSE) and non-streaming modes.
    Uses the Agent-based approach with tools for structured output.
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        db: Optional[Any] = None,
    ):
        """
        Initialize the Copilot service.

        Args:
            user_id: User ID for workspace isolation
            llm_model: Optional LLM model name override
            api_key: Optional API key override
            base_url: Optional API base URL override
            db: Optional database session for fetching credentials
        """
        self.user_id = user_id
        self.db = db
        # llm_model is resolved at runtime from the DB (node config takes precedence, then default model)
        # only store the passed-in value here; if None, generate_actions will fetch the default model
        self.llm_model = llm_model  # no longer uses settings.openai_model
        self.api_key = api_key
        self.base_url = base_url

    async def _get_copilot_stream(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]],
        mode: str,
        graph_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Single engine entry: returns a unified event stream for the given mode.
        Callers (generate_actions_stream, generate_actions_async) only consume this stream.
        """
        reset_node_registry()

        # Resolve credentials once for both engines
        try:
            api_key, base_url, final_model_name = await LLMCredentialResolver.get_credentials(
                db=self.db,
                api_key=self.api_key,
                base_url=self.base_url,
                llm_model=self.llm_model,
            )
            if not api_key:
                raise CopilotCredentialError(
                    "No API key found. Please configure your LLM credentials in settings.",
                    data={"has_db": self.db is not None},
                )
        except CopilotCredentialError:
            raise
        except Exception as e:
            logger.error(f"[CopilotService] Credential error: {e}")
            raise CopilotCredentialError("Failed to retrieve credentials", original_error=e)  # type: ignore[call-arg]

        if mode == "deepagents":
            async for event in self._stream_deepagents(
                prompt=prompt,
                graph_context=graph_context,
                graph_id=graph_id,
                conversation_history=conversation_history,
                api_key=api_key,
                base_url=base_url,
                final_model_name=final_model_name,
            ):
                yield event
            return

        # Standard engine
        yield {"type": "status", "stage": "thinking", "message": "Thinking..."}
        try:
            agent = await get_copilot_agent(
                graph_context=graph_context,
                user_id=self.user_id,
                llm_model=final_model_name,
                api_key=api_key,
                base_url=base_url,
                db=self.db,
            )
        except Exception as e:
            logger.error(f"[CopilotService] Agent creation error: {e}")
            yield {"type": "error", "message": f"Failed to create Copilot agent: {str(e)}", "code": "AGENT_ERROR"}
            return

        messages = self._build_messages(prompt, conversation_history)
        async for event in self._stream_standard_events(agent, messages, graph_context):
            yield event
        logger.info("[CopilotService] generate_actions_stream (standard) finished")

    async def _stream_deepagents(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        graph_id: Optional[str],
        conversation_history: Optional[List[Dict[str, str]]],
        api_key: str,
        base_url: Optional[str],
        final_model_name: Optional[str],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield events from the DeepAgents engine."""
        from app.core.copilot_deepagents.streaming import stream_deepagents_actions

        async for event in stream_deepagents_actions(
            prompt=prompt,
            graph_context=graph_context,
            graph_id=graph_id,
            user_id=self.user_id,
            api_key=api_key,
            base_url=base_url,
            llm_model=final_model_name,
            conversation_history=conversation_history,
        ):
            yield event

    async def _stream_standard_events(
        self,
        agent: Any,
        messages: List[Any],
        graph_context: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Yield unified events from the standard Copilot agent stream."""
        accumulated_content = ""
        last_streamed_thought: Optional[str] = None
        last_streamed_steps_count = 0
        collected_actions: List[Dict[str, Any]] = []
        final_message = ""

        async for event in agent.astream_events({"messages": messages}, version="v2", config={"recursion_limit": 300}):
            if not isinstance(event, dict):
                continue
            current_event_dict: Dict[str, Any] = event
            event_kind = current_event_dict.get("event", "")

            if event_kind == "on_chat_model_stream":
                data = current_event_dict.get("data", {})
                chunk = data.get("chunk") if isinstance(data, dict) else None
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"type": "content", "content": chunk.content}
                accumulated_content, last_streamed_thought, last_streamed_steps_count, thought_step_event = (
                    self._handle_chat_model_stream_event(
                        current_event_dict,
                        accumulated_content,
                        last_streamed_thought,
                        last_streamed_steps_count,
                    )
                )
                if thought_step_event:
                    yield thought_step_event

            elif event_kind == "on_tool_start":
                tool_name = current_event_dict.get("name", "")
                data = current_event_dict.get("data", {})
                tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                logger.info(f"[CopilotService] Tool started: {tool_name}, input: {tool_input}")
                yield {"type": "tool_call", "tool": tool_name, "input": tool_input}

            elif event_kind == "on_tool_end":
                tool_name = current_event_dict.get("name", "")
                data = current_event_dict.get("data", {})
                tool_output_raw = data.get("output") if isinstance(data, dict) else None
                logger.info(f"[CopilotService] Tool ended: {tool_name}, output type: {type(tool_output_raw)}")
                action_data = self._parse_tool_output(tool_output_raw, tool_name)
                if action_data:
                    expanded = expand_action_payload(action_data, filter_non_actions=True)
                    if expanded:
                        for a in expanded:
                            logger.info(f"[CopilotService] Extracted action: {a.get('type')}")
                            collected_actions.append(a)
                            yield {"type": "tool_result", "action": a}
                    else:
                        logger.warning(
                            f"[CopilotService] Tool output is not an action payload. tool={tool_name} "
                            f"keys={list(action_data.keys()) if isinstance(action_data, dict) else type(action_data)}"
                        )

            elif event_kind == "on_chat_model_end":
                event_data = (
                    current_event_dict.get("data", {}) if isinstance(current_event_dict.get("data"), dict) else {}
                )
                output = event_data.get("output") if isinstance(event_data, dict) else None
                if output and hasattr(output, "content"):
                    final_message = output.content

        yield {"type": "status", "stage": "processing", "message": "Processing..."}
        actions = self._convert_and_validate_actions(collected_actions, graph_context)
        yield {
            "type": "result",
            "message": final_message,
            "actions": [
                {"type": action.type.value, "payload": action.payload, "reasoning": action.reasoning}
                for action in actions
            ],
        }
        # done is NOT yielded here; generate_actions_async publishes it
        # AFTER persistence completes.
        logger.info(f"[CopilotService] generate_actions_stream success actions_count={len(actions)}")

    async def generate_actions(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        mode: str = "deepagents",
    ) -> CopilotResponse:
        """
        Generate graph actions (non-streaming).

        Creates an agent, invokes it with the user prompt, and collects
        all tool call results as actions.

        Args:
            prompt: User's request
            graph_context: Current graph state with nodes and edges
            conversation_history: Optional previous conversation messages

        Returns:
            CopilotResponse with message and actions
        """
        logger.info(f"[CopilotService] generate_actions start user_id={self.user_id}")

        # Reset node registry for fresh semantic ID tracking
        reset_node_registry()

        try:
            # Get credentials using unified CredentialManager
            try:
                api_key, base_url, final_model_name = await LLMCredentialResolver.get_credentials(
                    db=self.db,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    llm_model=self.llm_model,
                )
                if not api_key:
                    raise CopilotCredentialError(
                        "No API key found. Please configure your LLM credentials in settings.",
                        data={"has_db": self.db is not None},
                    )
            except CopilotCredentialError:
                raise
            except Exception as e:
                logger.error(f"[CopilotService] Credential error: {e}")
                raise CopilotCredentialError("Failed to retrieve credentials", original_error=e)  # type: ignore[call-arg]

            # Determine which engine to use
            if mode == "deepagents":
                from app.core.copilot_deepagents.runner import run_copilot_manager

                result_data = await run_copilot_manager(
                    user_prompt=prompt,
                    graph_context=graph_context,
                    graph_id=None,  # Non-streaming doesn't usually need graph_id for persistence here
                    user_id=self.user_id,
                    api_key=api_key,
                    base_url=base_url,
                    llm_model=final_model_name,
                    conversation_history=conversation_history,
                )
                return CopilotResponse(
                    message=result_data.get("message", ""),
                    actions=result_data.get("actions", []),
                )

            # Standard Engine (Standard Mode)
            # Create the Copilot agent (with db for model preloading)
            try:
                agent = await get_copilot_agent(
                    graph_context=graph_context,
                    user_id=self.user_id,
                    llm_model=final_model_name,
                    api_key=api_key,
                    base_url=base_url,
                    db=self.db,
                )
            except Exception as e:
                logger.error(f"[CopilotService] Agent creation error: {e}")
                raise CopilotAgentError("Failed to create Copilot agent", original_error=e)

            # Build messages
            messages = self._build_messages(prompt, conversation_history)

            # Invoke the agent with explicit recursion limit
            try:
                result = await agent.ainvoke({"messages": messages}, config={"recursion_limit": 300})
            except Exception as e:
                logger.error(f"[CopilotService] Agent invocation error: {e}")
                raise CopilotLLMError("Failed to process request with LLM", original_error=e)

            # Extract actions from result
            try:
                actions = self._extract_actions_from_result(result)
                final_message = self._extract_final_message(result)
            except Exception as e:
                logger.error(f"[CopilotService] Action extraction error: {e}")
                raise CopilotAgentError("Failed to extract actions from agent result", original_error=e)

            logger.info(f"[CopilotService] generate_actions success actions_count={len(actions)}")

            return CopilotResponse(
                message=final_message,
                actions=actions,
            )

        except (CopilotCredentialError, CopilotLLMError, CopilotAgentError, CopilotValidationError):
            # Re-raise known exceptions
            raise
        except Exception as e:
            logger.exception(f"[CopilotService] generate_actions failed: {e}")
            raise CopilotAgentError("An unexpected error occurred while processing your request", original_error=e)

    async def generate_actions_stream(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        mode: str = "deepagents",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generate graph actions with streaming (SSE events).
        Consumes the unified _get_copilot_stream and yields events; handles top-level errors with code.
        """
        logger.info(f"[CopilotService] generate_actions_stream start user_id={self.user_id}")
        try:
            async for event in self._get_copilot_stream(
                prompt=prompt,
                graph_context=graph_context,
                conversation_history=conversation_history,
                mode=mode,
                graph_id=None,
            ):
                yield event
        except CopilotCredentialError as e:
            yield {"type": "error", "message": str(e), "code": "CREDENTIAL_ERROR"}
        except KeyboardInterrupt:
            logger.warning("[CopilotService] Stream interrupted by user")
            yield {"type": "error", "message": "Request cancelled by user", "code": "CANCELLED"}
        except (CopilotLLMError, CopilotAgentError) as e:
            logger.error(f"[CopilotService] Stream failed: {e}")
            yield {"type": "error", "message": str(e), "code": type(e).__name__}
        except Exception as e:
            logger.exception(f"[CopilotService] generate_actions_stream failed: {e}")
            yield {"type": "error", "message": f"An unexpected error occurred: {str(e)}", "code": "UNKNOWN_ERROR"}

    def _handle_chat_model_stream_event(
        self,
        event: Dict[str, Any],
        accumulated_content: str,
        last_streamed_thought: Optional[str],
        last_streamed_steps_count: int,
    ) -> tuple[str, Optional[str], int, Optional[Dict[str, Any]]]:
        """
        Handle streaming content event from chat model.

        Args:
            event: Event dict from agent.astream_events
            accumulated_content: Previously accumulated content
            last_streamed_thought: Last thought content that was streamed
            last_streamed_steps_count: Count of thought steps already streamed

        Returns:
            Tuple of (new_accumulated_content, new_last_streamed_thought,
                     new_last_streamed_steps_count, optional_thought_step_event)
        """
        chunk = event.get("data", {}).get("chunk")
        if not chunk or not hasattr(chunk, "content") or not chunk.content:
            return accumulated_content, last_streamed_thought, last_streamed_steps_count, None

        content = chunk.content
        new_accumulated_content = accumulated_content + content

        # Try to extract and stream thought steps
        thought_step_event = None
        new_last_streamed_thought = last_streamed_thought
        new_last_streamed_steps_count = last_streamed_steps_count

        thought_content = try_extract_thought_field(new_accumulated_content)
        if thought_content and thought_content != last_streamed_thought:
            if len(thought_content) > 20:
                try:
                    steps = parse_thought_to_steps(thought_content)
                    if steps and len(steps) > last_streamed_steps_count:
                        new_steps = steps[last_streamed_steps_count:]
                        if new_steps:
                            # Return the first new step, caller should handle multiple steps
                            thought_step_event = {"type": "thought_step", "step": new_steps[0]}
                            new_last_streamed_steps_count = len(steps)
                            new_last_streamed_thought = thought_content
                except Exception:
                    logger.debug("Failed to parse thought steps from stream content", exc_info=True)

        return new_accumulated_content, new_last_streamed_thought, new_last_streamed_steps_count, thought_step_event

    def _convert_and_validate_actions(
        self,
        collected_actions: List[Dict[str, Any]],
        graph_context: Dict[str, Any],
    ) -> List[GraphAction]:
        """
        Convert action dicts to GraphAction objects and validate them.

        Args:
            collected_actions: List of action dicts collected from tool outputs
            graph_context: Current graph state for validation

        Returns:
            List of validated GraphAction objects
        """
        # Convert to GraphAction format
        actions = []
        for action_data in collected_actions:
            try:
                action_type = GraphActionType(action_data.get("type"))
                actions.append(
                    GraphAction(
                        type=action_type,
                        payload=action_data.get("payload", {}),
                        reasoning=action_data.get("reasoning", ""),
                    )
                )
            except (ValueError, KeyError):
                logger.warning("Failed to parse copilot action: %s", action_data, exc_info=True)

        # Validate actions before returning
        if actions:
            existing_ids = extract_existing_node_ids(graph_context)
            action_dicts = [{"type": a.type.value, "payload": a.payload, "reasoning": a.reasoning} for a in actions]
            validation_result = validate_actions(action_dicts, existing_ids)

            # Log validation results
            if validation_result.errors:
                logger.warning(f"[CopilotService] Action validation errors: {validation_result.errors}")
            if validation_result.warnings:
                logger.info(f"[CopilotService] Action validation warnings: {validation_result.warnings}")

            # Filter out invalid actions if there are errors
            if not validation_result.is_valid:
                valid_actions, removed = filter_invalid_actions(action_dicts, existing_ids)
                logger.warning(f"[CopilotService] Removed {len(removed)} invalid actions")
                # Rebuild actions list from filtered results
                actions = []
                for action_data in valid_actions:
                    try:
                        action_type = GraphActionType(action_data.get("type"))
                        actions.append(
                            GraphAction(
                                type=action_type,
                                payload=action_data.get("payload", {}),
                                reasoning=action_data.get("reasoning", ""),
                            )
                        )
                    except (ValueError, KeyError):
                        logger.warning("Failed to rebuild copilot action: %s", action_data, exc_info=True)

        return actions

    def _parse_tool_output(self, tool_output_raw: Any, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Parse tool output to extract action data.

        Delegates to unified parse_tool_output function.

        Args:
            tool_output_raw: Raw tool output (any type)
            tool_name: Name of the tool (for logging)

        Returns:
            Parsed action data dict, or None if parsing fails
        """
        return parse_tool_output(tool_output_raw, tool_name)

    def _build_messages(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List:
        """
        Build messages list for agent invocation.

        Delegates to unified build_langchain_messages function.
        """
        return build_langchain_messages(prompt, conversation_history)

    def _extract_actions_from_result(self, result: Dict[str, Any]) -> List[GraphAction]:
        """
        Extract GraphAction objects from agent result.

        Delegates to unified extract_actions_from_agent_result function.
        """
        return extract_actions_from_agent_result(result, filter_non_actions=False)

    def _extract_final_message(self, result: Dict[str, Any]) -> str:
        """Extract the final AI message from agent result."""
        output_messages = result.get("messages", [])

        # Get the last AI message
        for msg in reversed(output_messages):
            if hasattr(msg, "content") and isinstance(msg.content, str):
                if hasattr(msg, "type") and msg.type == "ai":
                    return msg.content
                # Check for AIMessage
                if msg.__class__.__name__ == "AIMessage":
                    return msg.content

        return ""


    async def _persist_graph_from_actions(self, graph_id: str, final_actions: List[Dict[str, Any]]) -> bool:
        """Apply actions to graph state and persist in a dedicated transaction. Returns True if saved successfully."""
        from app.core.database import async_session_factory

        async with async_session_factory() as new_db2:
            try:
                current_user = None
                if self.user_id:
                    user_repo = AuthUserRepository(new_db2)
                    current_user = await user_repo.get_by(id=self.user_id)

                graph_service = GraphService(new_db2)
                graph_uuid = uuid_lib.UUID(graph_id)
                current_state = await graph_service.load_graph_state(
                    graph_id=graph_uuid,
                    current_user=current_user,
                )

                current_nodes = current_state.get("nodes", [])
                current_edges = current_state.get("edges", [])

                updated_nodes, updated_edges = apply_actions_to_graph_state(
                    current_nodes=current_nodes,
                    current_edges=current_edges,
                    actions=final_actions,
                )

                viewport = current_state.get("viewport")
                variables = current_state.get("variables")

                await graph_service.save_graph_state(
                    graph_id=graph_uuid,
                    nodes=updated_nodes,
                    edges=updated_edges,
                    viewport=viewport,
                    variables=variables,
                    current_user=current_user,
                )

                await new_db2.commit()
                logger.info(
                    f"[CopilotService] Async task saved graph state for graph_id={graph_id}, "
                    f"nodes={len(updated_nodes)}, edges={len(updated_edges)}"
                )
                return True
            except Exception as e:
                if new_db2.in_transaction():
                    await new_db2.rollback()
                logger.error(
                    f"[CopilotService] Failed to save graph state for graph_id={graph_id}: {e}",
                    exc_info=True,
                )
                return False
