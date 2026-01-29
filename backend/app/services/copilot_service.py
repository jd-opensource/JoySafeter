"""
Copilot Service - Business logic for the Copilot feature.

Provides both streaming and non-streaming interfaces for generating
graph actions based on user requests.
"""

import copy
import uuid as uuid_lib
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger
from sqlalchemy import select

from app.core.copilot.action_applier import apply_actions_to_graph_state
from app.core.copilot.action_types import (
    CopilotHistoryResponse,
    CopilotMessage,
    CopilotResponse,
    CopilotThoughtStep,
    CopilotToolCall,
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
from app.models.chat import CopilotChat
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
        # llm_model 将在实际使用时从数据库获取（如果有节点配置则使用节点配置，否则使用默认模型）
        # 这里只保存传入的值，如果为 None，将在 generate_actions 中从数据库获取默认模型
        self.llm_model = llm_model  # 不再使用 settings.openai_model
        self.api_key = api_key
        self.base_url = base_url

    async def generate_actions(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
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

            # Create the Copilot agent (with db for model preloading)
            try:
                agent = await get_copilot_agent(
                    graph_context=graph_context,
                    user_id=self.user_id,
                    llm_model=final_model_name,  # 使用从数据库获取的模型名称
                    api_key=api_key,
                    base_url=base_url,
                    db=self.db,  # Pass db for preloading available models
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
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Generate graph actions with streaming (SSE events).

        Yields SSE event dicts with the following types:
        - status: Progress updates (stage, message)
        - content: Streaming AI response content
        - thought_step: Single thinking step
        - tool_call: Tool invocation event
        - tool_result: Tool execution result
        - result: Final result with message and actions
        - done: Stream finished
        - error: Error occurred

        Args:
            prompt: User's request
            graph_context: Current graph state with nodes and edges
            conversation_history: Optional previous conversation messages

        Yields:
            Dict with event type and data
        """
        logger.info(f"[CopilotService] generate_actions_stream start user_id={self.user_id}")

        # Reset node registry for fresh semantic ID tracking
        reset_node_registry()

        try:
            # Single status: Thinking
            yield {"type": "status", "stage": "thinking", "message": "正在思考..."}

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
                # Re-raise as error event
                yield {
                    "type": "error",
                    "message": "Credential error: No API key found. Please configure your LLM credentials.",
                    "code": "CREDENTIAL_ERROR",
                }
                return
            except Exception as e:
                logger.error(f"[CopilotService] Credential error: {e}")
                yield {
                    "type": "error",
                    "message": f"Failed to retrieve credentials: {str(e)}",
                    "code": "CREDENTIAL_ERROR",
                }
                return

            # Create the Copilot agent (with db for model preloading)
            try:
                agent = await get_copilot_agent(
                    graph_context=graph_context,
                    user_id=self.user_id,
                    llm_model=final_model_name,  # 使用从数据库获取的模型名称
                    api_key=api_key,
                    base_url=base_url,
                    db=self.db,  # Pass db for preloading available models
                )
            except Exception as e:
                logger.error(f"[CopilotService] Agent creation error: {e}")
                yield {"type": "error", "message": f"Failed to create Copilot agent: {str(e)}", "code": "AGENT_ERROR"}
                return

            # Build messages
            messages = self._build_messages(prompt, conversation_history)

            # Track state for streaming
            accumulated_content = ""
            last_streamed_thought = None
            last_streamed_steps_count = 0
            collected_actions: List[Dict[str, Any]] = []
            final_message = ""

            # Use the unified _expand_action_payload method

            # Stream events from the agent with explicit recursion limit
            async for event in agent.astream_events(
                {"messages": messages}, version="v2", config={"recursion_limit": 300}
            ):
                if isinstance(event, dict):
                    current_event_dict: Dict[str, Any] = event  # type: ignore[assignment]
                else:
                    current_event_dict = {}
                event_kind = current_event_dict.get("event", "")

                # Handle different event types
                if event_kind == "on_chat_model_stream":
                    # Streaming content from the LLM - use extracted method
                    data = current_event_dict.get("data", {})
                    chunk = data.get("chunk") if isinstance(data, dict) else None
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        content = chunk.content
                        yield {"type": "content", "content": content}

                    # Handle thought step extraction
                    accumulated_content, last_streamed_thought, last_streamed_steps_count, thought_step_event = (
                        self._handle_chat_model_stream_event(
                            current_event_dict, accumulated_content, last_streamed_thought, last_streamed_steps_count
                        )
                    )

                    # Yield thought step event if extracted
                    if thought_step_event:
                        yield thought_step_event
                        # Note: _handle_chat_model_stream_event returns only the first new step
                        # If multiple steps are detected, we may need to yield all of them
                        # This could be enhanced in the future

                elif event_kind == "on_tool_start":
                    # Tool invocation started
                    tool_name = current_event_dict.get("name", "")
                    data = current_event_dict.get("data", {})
                    tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                    logger.info(f"[CopilotService] Tool started: {tool_name}, input: {tool_input}")
                    yield {
                        "type": "tool_call",
                        "tool": tool_name,
                        "input": tool_input,
                    }

                elif event_kind == "on_tool_end":
                    # Tool execution completed
                    tool_name = current_event_dict.get("name", "")
                    data = current_event_dict.get("data", {})
                    tool_output_raw = data.get("output") if isinstance(data, dict) else None
                    logger.info(f"[CopilotService] Tool ended: {tool_name}, output type: {type(tool_output_raw)}")

                    # Parse tool output to extract action data
                    action_data = self._parse_tool_output(tool_output_raw, tool_name)

                    if action_data:
                        # Extract actions (single or batch) using unified method
                        expanded = expand_action_payload(action_data, filter_non_actions=True)
                        if expanded:
                            for a in expanded:
                                logger.info(f"[CopilotService] Extracted action: {a.get('type')}")
                                collected_actions.append(a)
                                yield {"type": "tool_result", "action": a}
                        else:
                            # Not an action payload; still useful for debugging but don't treat as action
                            logger.warning(
                                f"[CopilotService] Tool output is not an action payload. tool={tool_name} "
                                f"keys={list(action_data.keys()) if isinstance(action_data, dict) else type(action_data)}"
                            )

                elif event_kind == "on_chat_model_end":
                    # LLM finished generating
                    event_data = (
                        current_event_dict.get("data", {}) if isinstance(current_event_dict.get("data"), dict) else {}
                    )
                    output = event_data.get("output") if isinstance(event_data, dict) else None
                    if output and hasattr(output, "content"):
                        final_message = output.content

            # Stage 6: Processing results
            yield {"type": "status", "stage": "processing", "message": "处理结果..."}

            # Convert collected actions to GraphAction format and validate
            actions = self._convert_and_validate_actions(collected_actions, graph_context)

            # Send final result
            yield {
                "type": "result",
                "message": final_message,
                "actions": [
                    {
                        "type": action.type.value,
                        "payload": action.payload,
                        "reasoning": action.reasoning,
                    }
                    for action in actions
                ],
            }

            # Done
            yield {"type": "done"}
            logger.info(f"[CopilotService] generate_actions_stream success actions_count={len(actions)}")

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
                    pass

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
                pass

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
                        pass

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

    def _process_actions(
        self, actions: List[Dict[str, Any]], initial_nodes: List[Dict[str, Any]], initial_edges: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process graph actions to compute final nodes and edges.

        Similar to frontend ActionProcessor.processActions.
        This method applies actions to initial graph state and returns the final state.

        Args:
            actions: List of action dictionaries with 'type' and 'payload' keys
            initial_nodes: Initial nodes in the graph
            initial_edges: Initial edges in the graph

        Returns:
            Tuple of (final_nodes, final_edges) after processing all actions
        """
        processed_nodes = [copy.deepcopy(node) for node in initial_nodes]
        processed_edges = [copy.deepcopy(edge) for edge in initial_edges]

        # Create node index for O(1) lookups when updating/deleting nodes
        node_index: Dict[str, int] = {
            str(node.get("id")): i for i, node in enumerate(processed_nodes) if node.get("id") is not None
        }

        for action in actions:
            action_type = action.get("type")
            payload = action.get("payload", {})

            if action_type == "CREATE_NODE":
                node_id = payload.get("id") or f"ai_{int(datetime.utcnow().timestamp() * 1000)}"
                new_node = {
                    "id": node_id,
                    "type": "custom",
                    "position": payload.get("position") or {"x": 0, "y": 0},
                    "data": {
                        "label": payload.get("label") or "Node",
                        "type": payload.get("type"),
                        "config": payload.get("config") or {},
                    },
                }
                processed_nodes.append(new_node)
                node_index[node_id] = len(processed_nodes) - 1

            elif action_type == "CONNECT_NODES":
                source = payload.get("source")
                target = payload.get("target")
                if source and target:
                    # Check if edge already exists
                    if not any(e.get("source") == source and e.get("target") == target for e in processed_edges):
                        processed_edges.append(
                            {
                                "id": f"e-{source}-{target}",
                                "source": source,
                                "target": target,
                            }
                        )

            elif action_type == "DELETE_NODE":
                node_id = payload.get("id")
                if node_id:
                    processed_nodes = [n for n in processed_nodes if n.get("id") != node_id]
                    processed_edges = [
                        e for e in processed_edges if e.get("source") != node_id and e.get("target") != node_id
                    ]
                    # Rebuild index after deletion
                    node_index = {
                        str(node.get("id")): i for i, node in enumerate(processed_nodes) if node.get("id") is not None
                    }

            elif action_type == "UPDATE_CONFIG":
                node_id = payload.get("id")
                config = payload.get("config", {})
                if node_id and config:
                    # Use index for O(1) lookup instead of linear search
                    if node_id in node_index:
                        node_idx = node_index[node_id]
                        node_data = processed_nodes[node_idx].get("data", {})
                        existing_config = node_data.get("config", {})
                        node_data["config"] = {**existing_config, **config}
                    else:
                        logger.warning(f"[CopilotService] Node {node_id} not found for UPDATE_CONFIG action")

            elif action_type == "UPDATE_POSITION":
                node_id = payload.get("id")
                position = payload.get("position")
                if node_id and position:
                    # Use index for O(1) lookup instead of linear search
                    if node_id in node_index:
                        node_idx = node_index[node_id]
                        processed_nodes[node_idx]["position"] = position
                    else:
                        logger.warning(f"[CopilotService] Node {node_id} not found for UPDATE_POSITION action")

            else:
                # Unknown action type - log warning but don't fail
                logger.warning(f"[CopilotService] Unknown action type: {action_type}")

        return processed_nodes, processed_edges

    # ==================== History Persistence Methods ====================

    async def get_history(self, graph_id: str) -> Optional[CopilotHistoryResponse]:
        """
        Get Copilot conversation history for a specific graph.

        Args:
            graph_id: The graph ID to get history for

        Returns:
            CopilotHistoryResponse with messages, or None if no history exists
        """
        if not self.db:
            logger.warning("[CopilotService] No database session, cannot get history")
            return None

        try:
            graph_uuid = uuid_lib.UUID(graph_id)

            # Query for existing CopilotChat by graph_id and user_id
            stmt = select(CopilotChat).where(
                CopilotChat.agent_graph_id == graph_uuid,
                CopilotChat.user_id == self.user_id,
            )
            result = await self.db.execute(stmt)
            chat = result.scalar_one_or_none()

            if not chat:
                logger.debug(f"[CopilotService] No history found for graph_id={graph_id}")
                return None

            # Convert stored messages to CopilotMessage objects
            messages = []
            for msg_data in chat.messages or []:
                try:
                    # Parse thought_steps if present
                    thought_steps = None
                    if msg_data.get("thought_steps"):
                        thought_steps = [
                            CopilotThoughtStep(index=s.get("index", 0), content=s.get("content", ""))
                            for s in msg_data["thought_steps"]
                        ]

                    # Parse tool_calls if present
                    tool_calls = None
                    if msg_data.get("tool_calls"):
                        tool_calls = [
                            CopilotToolCall(
                                tool=tc.get("tool", ""),
                                input=tc.get("input", {}),
                                output=tc.get("output"),
                            )
                            for tc in msg_data["tool_calls"]
                        ]

                    # Parse created_at
                    created_at = datetime.utcnow()
                    if msg_data.get("created_at"):
                        try:
                            created_at = datetime.fromisoformat(msg_data["created_at"].replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass

                    messages.append(
                        CopilotMessage(
                            id=msg_data.get("id", f"msg_{uuid_lib.uuid4().hex[:12]}"),
                            role=msg_data.get("role", "user"),
                            content=msg_data.get("content", ""),
                            created_at=created_at,
                            actions=msg_data.get("actions"),
                            thought_steps=thought_steps,
                            tool_calls=tool_calls,
                        )
                    )
                except Exception as e:
                    logger.warning(f"[CopilotService] Failed to parse message: {e}")
                    continue

            logger.info(f"[CopilotService] Retrieved {len(messages)} messages for graph_id={graph_id}")

            return CopilotHistoryResponse(
                graph_id=graph_id,
                messages=messages,
                created_at=chat.created_at,
                updated_at=chat.updated_at,
            )

        except Exception as e:
            logger.error(f"[CopilotService] get_history failed: {e}")
            return None

    async def save_conversation_from_stream(
        self,
        graph_id: str,
        prompt: str,
        final_message: str,
        collected_thought_steps: List[Dict[str, Any]],
        collected_tool_calls: List[Dict[str, Any]],
        final_actions: List[Dict[str, Any]],
    ) -> bool:
        """
        Save conversation messages from streaming data.

        This is a convenience method that creates CopilotMessage objects
        from streaming data and saves them. Use this instead of manually
        creating messages in API endpoints.

        Args:
            graph_id: The graph ID to save messages for
            prompt: User's prompt
            final_message: Assistant's final message
            collected_thought_steps: List of thought step dicts
            collected_tool_calls: List of tool call dicts
            final_actions: List of action dicts

        Returns:
            True if save was successful, False otherwise
        """
        if not self.db:
            logger.warning("[CopilotService] No database session, cannot save messages")
            return False

        try:
            # Create user message
            user_msg = CopilotMessage(
                role="user",
                content=prompt,
                created_at=datetime.utcnow(),
            )

            # Create assistant message with all collected data
            assistant_msg = CopilotMessage(
                role="assistant",
                content=final_message,
                created_at=datetime.utcnow(),
                actions=final_actions if final_actions else None,
                thought_steps=[
                    CopilotThoughtStep(index=s.get("index", 0), content=s.get("content", ""))
                    for s in collected_thought_steps
                ]
                if collected_thought_steps
                else None,
                tool_calls=[
                    CopilotToolCall(tool=tc.get("tool", ""), input=tc.get("input", {})) for tc in collected_tool_calls
                ]
                if collected_tool_calls
                else None,
            )

            # Save using the existing save_messages method
            return await self.save_messages(graph_id, user_msg, assistant_msg)

        except Exception as e:
            logger.error(f"[CopilotService] save_conversation_from_stream failed: {e}")
            return False

    async def save_messages(
        self,
        graph_id: str,
        user_message: CopilotMessage,
        assistant_message: CopilotMessage,
    ) -> bool:
        """
        Save user and assistant messages to the conversation history.

        This method either creates a new CopilotChat record or appends to existing one.

        Args:
            graph_id: The graph ID to save messages for
            user_message: The user's message
            assistant_message: The assistant's response with actions, thought_steps, etc.

        Returns:
            True if save was successful, False otherwise
        """
        if not self.db:
            logger.warning("[CopilotService] No database session, cannot save messages")
            return False

        try:
            graph_uuid = uuid_lib.UUID(graph_id)

            # Query for existing CopilotChat
            stmt = select(CopilotChat).where(
                CopilotChat.agent_graph_id == graph_uuid,
                CopilotChat.user_id == self.user_id,
            )
            result = await self.db.execute(stmt)
            chat = result.scalar_one_or_none()

            # Serialize messages to dict
            def message_to_dict(msg: CopilotMessage) -> Dict[str, Any]:
                data: Dict[str, Any] = {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat() if msg.created_at else datetime.utcnow().isoformat(),
                }
                if msg.actions:
                    data["actions"] = msg.actions
                if msg.thought_steps:
                    data["thought_steps"] = [{"index": s.index, "content": s.content} for s in msg.thought_steps]
                if msg.tool_calls:
                    data["tool_calls"] = [
                        {"tool": tc.tool, "input": tc.input, "output": tc.output} for tc in msg.tool_calls
                    ]
                return data

            user_msg_dict = message_to_dict(user_message)
            assistant_msg_dict = message_to_dict(assistant_message)

            if chat:
                # Append to existing messages
                existing_messages = list(chat.messages or [])
                existing_messages.append(user_msg_dict)
                existing_messages.append(assistant_msg_dict)
                chat.messages = existing_messages
                chat.updated_at = datetime.utcnow()
                logger.info(f"[CopilotService] Appended messages to existing chat for graph_id={graph_id}")
            else:
                # Create new CopilotChat
                chat = CopilotChat(
                    user_id=self.user_id,
                    agent_graph_id=graph_uuid,
                    title=user_message.content[:100] if user_message.content else "Copilot Chat",
                    messages=[user_msg_dict, assistant_msg_dict],
                    model="default",
                )
                self.db.add(chat)
                logger.info(f"[CopilotService] Created new chat for graph_id={graph_id}")

            await self.db.commit()
            return True

        except Exception as e:
            logger.error(f"[CopilotService] save_messages failed: {e}")
            await self.db.rollback()
            return False

    async def clear_history(self, graph_id: str) -> bool:
        """
        Clear Copilot conversation history for a specific graph.

        Args:
            graph_id: The graph ID to clear history for

        Returns:
            True if successful, False otherwise
        """
        if not self.db:
            logger.warning("[CopilotService] No database session, cannot clear history")
            return False

        try:
            graph_uuid = uuid_lib.UUID(graph_id)

            # Query and delete
            stmt = select(CopilotChat).where(
                CopilotChat.agent_graph_id == graph_uuid,
                CopilotChat.user_id == self.user_id,
            )
            result = await self.db.execute(stmt)
            chat = result.scalar_one_or_none()

            if chat:
                await self.db.delete(chat)
                await self.db.commit()
                logger.info(f"[CopilotService] Cleared history for graph_id={graph_id}")

            return True

        except Exception as e:
            logger.error(f"[CopilotService] clear_history failed: {e}")
            await self.db.rollback()
            return False

    # ==================== Async Task Generation ====================

    async def generate_actions_async(
        self,
        session_id: str,
        graph_id: Optional[str],
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        """
        Generate graph actions asynchronously and store results in Redis.

        This method runs as a background task:
        1. Calls generate_actions_stream to get events
        2. Writes each event to Redis (content and Pub/Sub)
        3. Saves final result to database when complete
        4. Cleans up Redis temporary data

        Args:
            session_id: Unique session ID for this generation task
            graph_id: Optional graph ID for saving to database
            prompt: User's request
            graph_context: Current graph state
            conversation_history: Optional previous conversation messages
        """
        import time

        from app.core.redis import RedisClient

        # Record task start time
        start_time = time.time()

        # Log task start
        logger.info(
            f"[CopilotService] Async task started session_id={session_id} "
            f"graph_id={graph_id} user_id={self.user_id} "
            f"prompt_length={len(prompt) if prompt else 0}"
        )

        if not RedisClient.is_available():
            logger.error(f"[CopilotService] Redis not available for async task session_id={session_id}")
            await RedisClient.set_copilot_status(session_id, "failed")
            await RedisClient.publish_copilot_event(session_id, {"type": "error", "message": "Redis not available"})
            return

        try:
            # Set initial status
            await RedisClient.set_copilot_status(session_id, "generating")
            await RedisClient.publish_copilot_event(
                session_id, {"type": "status", "stage": "thinking", "message": "正在思考..."}
            )

            # Collect data for persistence
            collected_thought_steps: List[Dict[str, Any]] = []
            collected_tool_calls: List[Dict[str, Any]] = []
            final_message = ""
            final_actions: List[Dict[str, Any]] = []

            # Stream events and publish to Redis
            async for event in self.generate_actions_stream(
                prompt=prompt,
                graph_context=graph_context,
                conversation_history=conversation_history,
            ):
                event_type = event.get("type")

                # Publish event to Pub/Sub
                await RedisClient.publish_copilot_event(session_id, event)

                # Accumulate content for Redis storage
                if event_type == "content":
                    content = event.get("content", "")
                    if content:
                        await RedisClient.append_copilot_content(session_id, content)

                # Collect data for database persistence
                if event_type == "thought_step":
                    step = event.get("step", {})
                    collected_thought_steps.append(step)
                elif event_type == "tool_call":
                    collected_tool_calls.append(
                        {
                            "tool": event.get("tool", ""),
                            "input": event.get("input", {}),
                        }
                    )
                elif event_type == "result":
                    final_message = event.get("message", "")
                    final_actions = event.get("actions", [])

            # Save to database if graph_id is provided
            logger.info(
                f"[CopilotService] generate_actions_async: graph_id={graph_id}, final_actions_count={len(final_actions) if final_actions else 0}, graph_context={'present' if graph_context else 'missing'}"
            )

            if graph_id:
                # Create new database session for background task (original session may be closed)
                from app.core.database import async_session_factory

                logger.info("[CopilotService] Entering graph_id save block, creating new DB session")

                # 事务 1: 保存对话历史（独立事务）
                async with async_session_factory() as new_db:
                    try:
                        # Save conversation history
                        service_with_db = CopilotService(user_id=self.user_id, db=new_db)
                        saved = await service_with_db.save_conversation_from_stream(
                            graph_id=graph_id,
                            prompt=prompt,
                            final_message=final_message,
                            collected_thought_steps=collected_thought_steps,
                            collected_tool_calls=collected_tool_calls,
                            final_actions=final_actions,
                        )
                        if saved:
                            logger.info(
                                f"[CopilotService] Async task saved messages for session_id={session_id}, graph_id={graph_id}"
                            )
                        else:
                            logger.warning(
                                f"[CopilotService] Async task failed to save messages for session_id={session_id}, graph_id={graph_id}"
                            )
                        # save_messages 内部会调用 commit()，事务自动结束
                    except Exception as e:
                        # 如果 save_messages 内部已 commit，这里可能不在事务中
                        if new_db.in_transaction():
                            await new_db.rollback()
                        logger.error(
                            f"[CopilotService] Failed to save conversation for session_id={session_id}, "
                            f"graph_id={graph_id}: {e}",
                            exc_info=True,
                        )

                # 事务 2: 保存图状态（独立事务，使用新的 session）
                if final_actions and len(final_actions) > 0:
                    async with async_session_factory() as new_db2:
                        try:
                            # Load current user for permission check
                            current_user = None
                            if self.user_id:
                                user_repo = AuthUserRepository(new_db2)
                                current_user = await user_repo.get_by(id=self.user_id)

                            # Load current graph state
                            graph_service = GraphService(new_db2)
                            graph_uuid = uuid_lib.UUID(graph_id)
                            current_state = await graph_service.load_graph_state(
                                graph_id=graph_uuid,
                                current_user=current_user,
                            )

                            current_nodes = current_state.get("nodes", [])
                            current_edges = current_state.get("edges", [])

                            # Apply actions to graph state
                            updated_nodes, updated_edges = apply_actions_to_graph_state(
                                current_nodes=current_nodes,
                                current_edges=current_edges,
                                actions=final_actions,
                            )

                            # Save updated graph state
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

                            # 显式提交事务，确保 graph state 保存到数据库
                            await new_db2.commit()

                            logger.info(
                                f"[CopilotService] Async task saved graph state for session_id={session_id}, "
                                f"graph_id={graph_id}, nodes={len(updated_nodes)}, edges={len(updated_edges)}"
                            )
                        except Exception as e:
                            # 异常时回滚事务
                            if new_db2.in_transaction():
                                await new_db2.rollback()
                            # Log error but don't fail the entire task
                            logger.error(
                                f"[CopilotService] Failed to save graph state for session_id={session_id}, "
                                f"graph_id={graph_id}: {e}",
                                exc_info=True,
                            )
            # logger.info(f"[CopilotService] Async task completed successfully for session_id={session_id}, graph_id={graph_id}， actions={json.dumps(final_actions) if final_actions else 0}")

            # Calculate execution time
            execution_time = time.time() - start_time
            execution_time_ms = int(execution_time * 1000)

            # Update status to completed
            await RedisClient.set_copilot_status(session_id, "completed")
            await RedisClient.publish_copilot_event(session_id, {"type": "done"})

            # Enhanced completion log with detailed information
            logger.info(
                f"[CopilotService] Async task completed successfully "
                f"session_id={session_id} graph_id={graph_id} "
                f"actions_count={len(final_actions) if final_actions else 0} "
                f"thought_steps_count={len(collected_thought_steps)} "
                f"tool_calls_count={len(collected_tool_calls)} "
                f"execution_time_ms={execution_time_ms} "
                f"user_id={self.user_id}"
            )

        except Exception as e:
            # Calculate execution time even on failure
            execution_time = time.time() - start_time
            execution_time_ms = int(execution_time * 1000)

            # Enhanced error log with stack trace and context
            logger.error(
                f"[CopilotService] Async task failed "
                f"session_id={session_id} graph_id={graph_id} "
                f"user_id={self.user_id} execution_time_ms={execution_time_ms} "
                f"error_type={type(e).__name__} error={e}",
                exc_info=True,
            )
            await RedisClient.set_copilot_status(session_id, "failed")
            await RedisClient.publish_copilot_event(session_id, {"type": "error", "message": str(e)})
