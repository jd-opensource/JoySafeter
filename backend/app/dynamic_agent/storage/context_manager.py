"""
Session context management.

Manages conversation history, container state, and task tracking for agent sessions.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.dynamic_agent.storage.container.binding import ContainerBindingInfo


@dataclass
class SessionContext:
    """Session context containing all session state."""

    session_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime

    # Conversation history
    messages: List[Dict[str, Any]] = field(default_factory=list)

    # Container context
    container_info: Optional[ContainerBindingInfo] = None

    # Task state
    active_tasks: Dict[str, Any] = field(default_factory=dict)
    completed_tasks: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Scenario information
    scenario: Optional[str] = None  # web_pentest, network_scan, etc.
    target_info: Dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """Context manager for agent sessions."""

    def __init__(self, persistence_backend):
        self.backend = persistence_backend
        self._active_contexts: Dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self, user_id: str, session_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None
    ) -> SessionContext:
        """Create a new session."""
        if session_id is None:
            from uuid import uuid4

            session_id = str(uuid4())

        context = SessionContext(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=metadata or {},
        )

        async with self._lock:
            self._active_contexts[session_id] = context
            await self.backend.save_context(context)

        return context  # type: ignore[return-value]

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Get session context."""

        # Load from persistence
        context: Optional[SessionContext] = await self.backend.load_context(session_id)  # type: ignore[assignment]
        if context:
            async with self._lock:
                self._active_contexts[session_id] = context

        return context

    async def update_session(self, context: SessionContext):
        """Update session context."""
        context.updated_at = datetime.now()
        async with self._lock:
            self._active_contexts[context.session_id] = context
            await self.backend.save_context(context)

    async def add_message(
        self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """Add message to conversation history and return its ID."""
        logger.debug(f"ContextManager.add_message called for session {session_id}")

        logger.debug("Getting session context...")
        context = await self.get_session(session_id)
        if not context:
            logger.error(f"Session {session_id} not found!")
            raise ValueError(f"Session {session_id} not found")
        logger.debug("Session context retrieved")

        # Explicitly save to DB first to get ID
        logger.debug("Calling backend.add_message...")
        message_id: int = await self.backend.add_message(session_id, role, content, metadata)
        logger.debug(f"backend.add_message returned ID: {message_id}")

        message = {
            "message_id": message_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }

        context.messages.append(message)

        # Update session metadata
        # save_context will see message_id and skip re-inserting
        logger.debug("Updating session...")
        await self.update_session(context)
        logger.debug("Session updated successfully")

        return message_id

    # todo delete
    async def add_message_will_delete(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> Optional[int]:
        """
        Add message to conversation history.

        Args:
            session_id: Session identifier
            role: Message role (user, assistant, tool, system)
            content: Message content
            metadata: Optional metadata
            tool_calls: For assistant messages, list of tool calls made
            tool_call_id: For tool messages, the ID of the tool call this responds to
        """

        logger.debug(f"ContextManager.add_message called for session {session_id}")

        logger.debug("Getting session context...")
        context = await self.get_session(session_id)
        if not context:
            logger.error(f"Session {session_id} not found!")
            raise ValueError(f"Session {session_id} not found")
        logger.debug("Session context retrieved")

        # Explicitly save to DB first to get ID
        logger.debug("Calling backend.add_message...")
        message_id: int = await self.backend.add_message(session_id, role, content, metadata)
        logger.debug(f"backend.add_message returned ID: {message_id}")

        message = {
            "message_id": message_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }

        # Add tool_calls for assistant messages (OpenAI format)
        if tool_calls:
            message["tool_calls"] = tool_calls

        # Add tool_call_id for tool messages (OpenAI format)
        if tool_call_id:
            message["tool_call_id"] = tool_call_id

        context.messages.append(message)

        # Update session metadata
        # save_context will see message_id and skip re-inserting
        logger.debug("Updating session...")
        await self.update_session(context)
        logger.debug("Session updated successfully")

        return message_id

    async def get_conversation_history(self, session_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get conversation history."""
        context = await self.get_session(session_id)
        if not context:
            return []

        messages = context.messages
        if limit:
            messages = messages[-limit:]

        return messages  # type: ignore[return-value]

    async def set_container_context(self, session_id: str, container_id: str, working_directory: str = "/"):
        """Set container context."""
        context = await self.get_session(session_id)
        if not context:
            raise ValueError(f"Session {session_id} not found")

        # Update container_info if it exists, otherwise create a new one
        if context.container_info:
            context.container_info.container_id = container_id
            context.container_info.working_directory = working_directory
        else:
            # Create a minimal ContainerBindingInfo
            from app.dynamic_agent.storage.container.binding import ContainerBindingInfo

            context.container_info = ContainerBindingInfo(
                container_id=container_id,
                container_name="",
                binding_id="",
                docker_api=None,
                mcp_api=None,
                reused=False,
                status="active",
                image="",
                command="",
                working_directory=working_directory,
            )
        await self.update_session(context)

    async def identify_scenario(self, session_id: str, user_message: str) -> str:
        """Identify testing scenario from user message."""
        # Simple keyword matching - can be enhanced with LLM
        # NOTE: Order matters! More specific scenarios should come first
        scenarios = [
            # CTF should be checked first (highest priority)
            ("ctf", ["ctf", "ctf:", "flag{", "flag:", "capture the flag", "find flag", "get flag", "capture flag"]),
            # Binary/Reverse
            ("binary_analysis", ["binary", "reverse", "pwn", "elf", "binary", "reverse"]),
            # Cloud
            ("cloud_security", ["cloud", "aws", "azure", "k8s", "docker", "cloud", "kubernetes"]),
            # API
            ("api_test", ["api", "interface", "rest", "graphql", "endpoint"]),
            # Network
            ("network_scan", ["network", "scan", "port", "host", "network", "scan", "port"]),
            # Web (most generic, should be last among specific types)
            ("web_pentest", ["web", "website", "http", "https", "url", "website"]),
        ]

        message_lower = user_message.lower()
        for scenario, keywords in scenarios:
            if any(kw in message_lower for kw in keywords):
                context = await self.get_session(session_id)
                if context:
                    context.scenario = scenario
                    await self.update_session(context)
                return scenario

        return "general"

    async def set_target_info(self, session_id: str, target: str, info: Dict[str, Any]):
        """Set target information."""
        context = await self.get_session(session_id)
        if not context:
            raise ValueError(f"Session {session_id} not found")

        context.target_info[target] = {**info, "updated_at": datetime.now().isoformat()}
        await self.update_session(context)

    async def get_target_info(self, session_id: str, target: str) -> Optional[Dict[str, Any]]:
        """Get target information."""
        context = await self.get_session(session_id)
        if not context:
            return None

        return context.target_info.get(target)  # type: ignore[return-value]

    async def clear_session(self, session_id: str):
        """Clear session from memory (but keep in persistence)."""
        async with self._lock:
            if session_id in self._active_contexts:
                del self._active_contexts[session_id]
