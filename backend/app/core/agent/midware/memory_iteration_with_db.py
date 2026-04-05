"""MemoryManager-driven memory middleware.

Before model call:
- Retrieve relevant long-term memories for the current user input (supports last_n / first_n / agentic)
- Inject retrieved memories as structured fragments into the system prompt to enrich context

After model call:
- Submit the current user input to MemoryManager, which decides whether to add/update/delete memories based on capture rules
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, List, Literal, Optional

from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from typing_extensions import NotRequired

from app.core.agent.memory.manager import MemoryManager
from app.schemas.memory import UserMemory

if TYPE_CHECKING:
    pass


class AgenticMemoryState(AgentState):
    """Extended state for the Agentic Memory middleware."""

    user_id: NotRequired[str | None]  # type: ignore[valid-type]
    agent_memory_context: NotRequired[str | None]  # type: ignore[valid-type]


class AgentMemoryIterationMiddleware(AgentMiddleware):
    """Agent memory middleware using MemoryManager.

    - before: retrieve user-related memories from MemoryManager and inject into system prompt
    - after: pass user input to MemoryManager for memory write/update

    Args:
        memory_manager: Pre-configured MemoryManager instance (must have model/db).
        retrieval_method: Retrieval method — "last_n" | "first_n" | "agentic".
        retrieval_limit: Maximum number of memories to retrieve.
        context_header: Header for the memory fragment injected into the system prompt.
        enable_writeback: Whether to write memories after the model call.
        capture_source: Source for memory capture — "user" or "assistant" (default "user").
    """

    priority = 50  # medium priority, runs alongside skill middleware
    state_schema = AgenticMemoryState

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        retrieval_method: str = "last_n",
        retrieval_limit: int = 5,
        context_header: str = "## Relevant User Memories",
        enable_writeback: bool = True,
        capture_source: str = "user",
        user_id: Optional[str] = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.retrieval_method = retrieval_method
        self.retrieval_limit = retrieval_limit
        self.context_header = context_header
        self.enable_writeback = enable_writeback
        self.capture_source = capture_source
        self.user_id = user_id

        if self.memory_manager is None:
            raise ValueError("AgentMemoryManagerMiddleware requires a MemoryManager instance")

        logger.info(
            f"AgentMemoryIterationMiddleware initialized: "
            f"retrieval_method={retrieval_method}, retrieval_limit={retrieval_limit}, "
            f"enable_writeback={enable_writeback}, capture_source={capture_source}, "
            f"user_id={user_id}"
        )

    # ---------------------------
    # Helpers
    # ---------------------------
    def _get_user_id(self) -> Optional[str]:
        """Get the current user's user_id.

        Returns:
            user_id string, or None if not available.
        """
        if not self.user_id:
            logger.warning("No user_id configured in middleware instance")
        return self.user_id

    def _extract_user_input(self, request: ModelRequest) -> Optional[str]:
        """Extract user input text from the request (LangGraph ModelRequest format)."""
        # get the last HumanMessage from the message list
        if hasattr(request, "messages") and request.messages:
            try:
                # iterate messages in reverse to find the last HumanMessage
                for msg in reversed(request.messages):
                    # check if it is a HumanMessage type
                    if isinstance(msg, HumanMessage):
                        content = getattr(msg, "content", None)
                        if content:
                            # handle different content types
                            if isinstance(content, str):
                                extracted = content
                            elif isinstance(content, list):
                                # handle content_blocks format
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                    elif isinstance(block, str):
                                        text_parts.append(block)
                                extracted = " ".join(text_parts) if text_parts else str(content)
                            else:
                                extracted = str(content)

                            if extracted and extracted.strip():
                                logger.debug(f"Extracted user input from HumanMessage: {extracted[:100]}...")
                                return extracted

                    # compatibility: check the message's type attribute (LangChain message types)
                    elif hasattr(msg, "type"):
                        if msg.type == "human":
                            content = getattr(msg, "content", None)
                            if content:
                                extracted = content if isinstance(content, str) else str(content)
                                if extracted and extracted.strip():
                                    logger.debug(
                                        f"Extracted user input from message type 'human': {extracted[:100]}..."
                                    )
                                    return extracted

                    # compatibility: check dict-format messages
                    elif isinstance(msg, dict):
                        msg_type = msg.get("type") or msg.get("role")
                        if msg_type in ("human", "user"):
                            content = msg.get("content")
                            if content:
                                extracted = content if isinstance(content, str) else str(content)
                                if extracted and extracted.strip():
                                    logger.debug(f"Extracted user input from dict message: {extracted[:100]}...")
                                    return extracted
            except Exception as e:
                logger.warning(f"Failed to extract user input from messages: {e}", exc_info=True)

        logger.debug("No user input found in request messages")
        return None

    def _extract_assistant_response(self, response: ModelResponse) -> Optional[str]:
        """Extract assistant response text from ModelResponse (LangGraph ModelResponse format)."""
        # prefer response.content if it is a string
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                if content.strip():
                    logger.debug(f"Extracted assistant response from response.content: {content[:100]}...")
                    return content

        # get the last AIMessage from the message list
        if hasattr(response, "messages") and response.messages:
            try:
                # iterate messages in reverse to find the last AIMessage
                for msg in reversed(response.messages):
                    # check if it is an AIMessage type
                    if isinstance(msg, AIMessage):
                        content = getattr(msg, "content", None)
                        if content:
                            # handle different content types
                            if isinstance(content, str):
                                extracted = content
                            elif isinstance(content, list):
                                # handle content_blocks format
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                    elif isinstance(block, str):
                                        text_parts.append(block)
                                extracted = " ".join(text_parts) if text_parts else str(content)
                            else:
                                extracted = str(content)

                            if extracted and extracted.strip():
                                logger.debug(f"Extracted assistant response from AIMessage: {extracted[:100]}...")
                                return extracted

                    # compatibility: check the message's type attribute (LangChain message types)
                    elif hasattr(msg, "type"):
                        if msg.type == "ai":
                            content = getattr(msg, "content", None)
                            if content:
                                extracted = content if isinstance(content, str) else str(content)
                                if extracted and extracted.strip():
                                    logger.debug(
                                        f"Extracted assistant response from message type 'ai': {extracted[:100]}..."
                                    )
                                    return extracted

                    # compatibility: check dict-format messages
                    elif isinstance(msg, dict):
                        msg_type = msg.get("type") or msg.get("role")
                        if msg_type in ("ai", "assistant"):
                            content = msg.get("content")
                            if content:
                                extracted = content if isinstance(content, str) else str(content)
                                if extracted and extracted.strip():
                                    logger.debug(
                                        f"Extracted assistant response from dict message: {extracted[:100]}..."
                                    )
                                    return extracted
            except Exception as e:
                logger.warning(f"Failed to extract assistant response from messages: {e}", exc_info=True)

        logger.debug("No assistant response found in response")
        return None

    def _format_memories(self, memories: List[UserMemory]) -> str:
        """Format a list of UserMemory objects into a system prompt fragment."""
        if not memories:
            return ""

        lines: List[str] = [self.context_header]
        for i, mem in enumerate(memories, 1):
            bullet = f"- {mem.memory}" if isinstance(mem.memory, str) else f"- {mem.memory!r}"
            meta_parts: List[str] = []
            if mem.topics:
                meta_parts.append(f"topics={','.join(mem.topics)}")
            if mem.memory_id:
                meta_parts.append(f"id={mem.memory_id}")
            meta_str = f" ({'; '.join(meta_parts)})" if meta_parts else ""
            lines.append(f"{i}. {bullet}{meta_str}")

        return "\n".join(lines)

    async def _build_memory_context(self, request: ModelRequest, user_id: str) -> str:
        """Retrieve memories from MemoryManager per config and build context (async)."""
        query: Optional[str] = None
        if self.retrieval_method == "agentic":
            query = self._extract_user_input(request)
            logger.info(
                f"Retrieving memories with agentic method for user_id={user_id}, "
                f"query={query[:100] if query else None}..."
            )
        else:
            logger.info(
                f"Retrieving memories with {self.retrieval_method} method for user_id={user_id}, "
                f"limit={self.retrieval_limit}"
            )

        try:
            retrieval_method_literal: Literal["last_n", "first_n", "agentic"] | None = None
            if self.retrieval_method in ("last_n", "first_n", "agentic"):
                retrieval_method_literal = self.retrieval_method  # type: ignore[assignment]
            memories = await self.memory_manager.asearch_user_memories(
                query=query,
                limit=self.retrieval_limit,
                retrieval_method=retrieval_method_literal,
                user_id=user_id,
            )
            memory_count = len(memories) if memories else 0
            logger.info(f"Memory retrieval completed for user_id={user_id}: found {memory_count} memories")
        except Exception as e:
            logger.warning(f"Memory retrieval failed for user_id={user_id}: {e}")
            memories = []

        formatted_context = self._format_memories(memories or [])
        if formatted_context:
            logger.debug(f"Formatted memory context length: {len(formatted_context)} characters")
        else:
            logger.debug("No memory context generated")
        return formatted_context

    # ---------------------------
    # Lifecycle Hooks
    # ---------------------------
    def before_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,  # type: ignore[no-untyped-def]
    ) -> dict[str, Any]:  # type: ignore[override]
        """Perform necessary initialization here."""
        user_id = self._get_user_id()
        if user_id:
            logger.debug(f"Initializing MemoryManager for user_id={user_id}")
            try:
                self.memory_manager.initialize(user_id=user_id)
                logger.debug(f"MemoryManager initialized successfully for user_id={user_id}")
            except Exception as e:
                logger.warning(f"MemoryManager initialize failed for user_id={user_id}: {e}")
        else:
            logger.warning("Skipping MemoryManager initialization: no user_id available")

        return {"messages": []}

    async def abefore_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,  # type: ignore[no-untyped-def]
    ) -> dict[str, Any]:  # type: ignore[override]
        return self.before_agent(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject memories before model call; write back memories after call (sync version, uses asyncio.run internally)."""
        user_id = self._get_user_id()

        if not user_id:
            logger.warning("Skipping memory operations: no user_id available")
            return handler(request)

        # build and inject memory context
        # simplified: use asyncio.run() directly for the async method;
        # if already inside an event loop, LangGraph calls awrap_model_call instead
        memory_context = asyncio.run(self._build_memory_context(request, user_id))

        if memory_context:
            # store in state for downstream use or debugging
            try:
                request.state["agent_memory_context"] = memory_context  # type: ignore[typeddict-unknown-key]
            except Exception:
                pass

            logger.info(f"Injecting memory context into system prompt for user_id={user_id}")
            if request.system_prompt:
                request.system_prompt = f"{memory_context}\n\n{request.system_prompt}"  # type: ignore[misc, assignment]
            else:
                request.system_prompt = memory_context  # type: ignore[misc, assignment]
        else:
            logger.debug(f"No memory context to inject for user_id={user_id}")

        # call model
        logger.debug(f"Calling model handler for user_id={user_id}")
        response = handler(request)

        # write back memories: use user input as the basis for memory capture
        if self.enable_writeback:
            logger.info(f"Attempting to write back memory for user_id={user_id}, capture_source={self.capture_source}")
            try:
                message_text: Optional[str] = None
                if self.capture_source == "assistant":
                    # extract assistant response content from ModelResponse
                    message_text = self._extract_assistant_response(response)
                else:
                    # default: capture from user input
                    message_text = self._extract_user_input(request)

                if message_text and message_text.strip():
                    logger.info(
                        f"Writing memory for user_id={user_id}, "
                        f"message_length={len(message_text)}, capture_source={self.capture_source}"
                    )
                    # simplified: use asyncio.run() directly for the async method;
                    # if already inside an event loop, LangGraph calls awrap_model_call instead
                    asyncio.run(self.memory_manager.acreate_user_memories(message=message_text, user_id=user_id))
                    logger.info(f"Memory writeback completed successfully for user_id={user_id}")
                else:
                    logger.debug(f"No message text to write back for user_id={user_id}")
            except Exception as e:
                logger.error(f"Failed to write back memory for user_id={user_id}: {e}", exc_info=True)
        else:
            logger.debug(f"Memory writeback disabled for user_id={user_id}")

        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async version: inject memories before model call; write back memories after call."""
        user_id = self._get_user_id()

        if not user_id:
            logger.warning("Skipping memory operations: no user_id available")
            return await handler(request)

        # build and inject memory context
        memory_context = await self._build_memory_context(request, user_id)
        if memory_context:
            try:
                request.state["agent_memory_context"] = memory_context  # type: ignore[typeddict-unknown-key]
            except Exception:
                pass

            logger.info(f"Injecting memory context into system prompt for user_id={user_id}")
            if request.system_prompt:
                request.system_prompt = f"{memory_context}\n\n{request.system_prompt}"  # type: ignore[misc, assignment]
            else:
                request.system_prompt = memory_context  # type: ignore[misc, assignment]
        else:
            logger.debug(f"No memory context to inject for user_id={user_id}")

        # call model
        logger.debug(f"Calling model handler for user_id={user_id}")
        response = await handler(request)

        # write back memories
        if self.enable_writeback:
            logger.info(f"Attempting to write back memory for user_id={user_id}, capture_source={self.capture_source}")
            try:
                message_text: Optional[str] = None
                if self.capture_source == "assistant":
                    # extract assistant response content from ModelResponse
                    message_text = self._extract_assistant_response(response)
                else:
                    # default: capture from user input
                    message_text = self._extract_user_input(request)

                if message_text and message_text.strip():
                    logger.info(
                        f"Writing memory for user_id={user_id}, "
                        f"message_length={len(message_text)}, capture_source={self.capture_source}"
                    )
                    await self.memory_manager.acreate_user_memories(
                        message=message_text,
                        user_id=user_id,
                    )
                    logger.info(f"Memory writeback completed successfully for user_id={user_id}")
                else:
                    logger.debug(f"No message text to write back for user_id={user_id}")
            except Exception as e:
                logger.error(f"Failed to write back memory for user_id={user_id}: {e}", exc_info=True)
        else:
            logger.debug(f"Memory writeback disabled for user_id={user_id}")

        return response
