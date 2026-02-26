from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Callable, Dict, List, Literal, Optional, Type, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages.chat import ChatMessage as Message
from langchain_openai import ChatOpenAI
from loguru import logger
from pydantic import BaseModel, Field

from app.core.agent.memory.strategies import (
    MemoryOptimizationStrategy,
    MemoryOptimizationStrategyFactory,
    MemoryOptimizationStrategyType,
)

# Import DEFAULT_USER_ID for consistent user_id handling
from app.core.constants import DEFAULT_USER_ID
from app.core.settings import get_default_model_config
from app.core.tools.tool import EnhancedTool
from app.schemas.memory import UserMemory
from app.services.memory_service import MemoryService
from app.utils.datetime import utc_now
from app.utils.prompts import get_json_output_prompt
from app.utils.string import parse_response_model_str


class MemorySearchResponse(BaseModel):
    """Model for Memory Search Response."""

    memory_ids: List[str] = Field(
        ...,
        description="The IDs of the memories that are most semantically similar to the query.",
    )


@dataclass
class MemoryManager:
    """Memory Manager"""

    # Model used for memory management
    model: Optional[BaseChatModel] = None

    # Provide the system message for the manager as a string. If not provided, the default system message will be used.
    system_message: Optional[str] = None
    # Provide the memory capture instructions for the manager as a string. If not provided, the default memory capture instructions will be used.
    memory_capture_instructions: Optional[str] = None
    # Additional instructions for the manager. These instructions are appended to the default system message.
    additional_instructions: Optional[str] = None

    # Whether memories were created in the last run
    memories_updated: bool = False

    # ----- db tools ---------
    # Whether to delete memories
    delete_memories: bool = True
    # Whether to clear memories
    clear_memories: bool = True
    # Whether to update memories
    update_memories: bool = True
    # whether to add memories
    add_memories: bool = True

    # The database to store memories
    db: Optional[Union[MemoryService]] = None

    debug_mode: bool = False

    def __init__(
        self,
        model: Optional[Union[BaseChatModel, str]] = None,
        system_message: Optional[str] = None,
        memory_capture_instructions: Optional[str] = None,
        additional_instructions: Optional[str] = None,
        db: Optional[Union[MemoryService]] = None,
        delete_memories: bool = False,
        update_memories: bool = True,
        add_memories: bool = True,
        clear_memories: bool = False,
        debug_mode: bool = False,
    ):
        self.model = model  # type: ignore[assignment]
        self.system_message = system_message
        self.memory_capture_instructions = memory_capture_instructions
        self.additional_instructions = additional_instructions
        self.db = db
        self.delete_memories = delete_memories
        self.update_memories = update_memories
        self.add_memories = add_memories
        self.clear_memories = clear_memories
        self.debug_mode = debug_mode

        # TODO not impl model config
        # if self.model is not None:
        #    self.model = get_model(self.model)

    def get_model(self) -> BaseChatModel:
        if self.model is None:
            try:
                config = get_default_model_config()
                if not config:
                    raise ValueError("Default model configuration is missing")
                self.model = ChatOpenAI(
                    model=config["model"],
                    api_key=config.get("api_key"),
                    base_url=config.get("base_url"),
                    timeout=config.get("timeout", 30),
                    streaming=False,
                    callbacks=[],
                )
            except Exception as e:
                logger.error(f"Failed to get default model from settings: {e}")
                raise ValueError("无法获取默认模型配置，请先在系统中配置默认模型")
        return self.model

    def _get_message_content_string(self, msg: Message) -> str:
        """Extract content string from message, supporting both get_content_string() and content attribute.

        This method handles different message types:
        - Messages with get_content_string() method (e.g., app.models.message.Message)
        - Messages with content attribute (e.g., langchain_core.messages.chat.ChatMessage)
        """
        if hasattr(msg, "get_content_string"):
            result = msg.get_content_string()
            return str(result) if result is not None else ""
        elif hasattr(msg, "content"):
            content = msg.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle content_blocks format
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                return " ".join(text_parts) if text_parts else str(content)
            else:
                return str(content) if content else ""
        return ""

    def read_from_db(self, user_id: Optional[str] = None):
        if self.db:
            # If no user_id is provided, read all memories
            if user_id is None:
                all_memories: List[UserMemory] = self.db.get_user_memories()  # type: ignore
            else:
                all_memories = self.db.get_user_memories(user_id=user_id)  # type: ignore

            memories: Dict[str, List[UserMemory]] = {}
            for memory in all_memories:
                if memory.user_id is not None and memory.memory_id is not None:
                    memories.setdefault(memory.user_id, []).append(memory)

            return memories
        return None

    async def aread_from_db(self, user_id: Optional[str] = None):
        if self.db:
            if isinstance(self.db, MemoryService):
                # If no user_id is provided, read all memories
                if user_id is None:
                    all_memories: List[UserMemory] = await self.db.get_user_memories()  # type: ignore
                else:
                    all_memories = await self.db.get_user_memories(user_id=user_id)  # type: ignore
            else:
                if user_id is None:
                    all_memories = self.db.get_user_memories()  # type: ignore
                else:
                    all_memories = self.db.get_user_memories(user_id=user_id)  # type: ignore

            memories: Dict[str, List[UserMemory]] = {}
            for memory in all_memories:
                if memory.user_id is not None and memory.memory_id is not None:
                    memories.setdefault(memory.user_id, []).append(memory)

            return memories
        return None

    def set_log_level(self):
        # TODO not impl
        pass
        """
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
        else:
            set_log_level_to_info()
        """

    def initialize(self, user_id: Optional[str] = None):
        self.set_log_level()

    def _build_tool_map(self, tools: List[Callable]) -> Dict[str, Callable]:
        """Build a mapping from tool name to tool callable.

        Supports both:
        - EnhancedTool/BaseTool objects (with .name attribute)
        - Regular functions (with __name__ attribute)
        """
        tool_map = {}
        for tool in tools:
            if hasattr(tool, "name"):  # EnhancedTool or BaseTool
                tool_map[tool.name] = tool
            elif hasattr(tool, "__name__"):  # Regular function
                tool_map[tool.__name__] = tool
        return tool_map

    def _execute_tool_calls(self, tool_calls: List[Dict], tool_map: Dict[str, Callable]) -> bool:
        """Execute tool calls synchronously.

        Args:
            tool_calls: List of tool call dicts with 'name' and 'args' keys
            tool_map: Mapping from tool name to tool callable

        Returns:
            True if any tools were executed
        """
        if not tool_calls:
            return False

        logger.info(f"Executing {len(tool_calls)} tool calls...")
        executed = False

        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})

            if tool_name not in tool_map:
                logger.warning(f"Unknown tool: {tool_name}")
                continue

            try:
                logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                tool = tool_map[tool_name]

                # Handle different tool types
                if hasattr(tool, "invoke"):
                    result = tool.invoke(tool_args)
                elif hasattr(tool, "run"):
                    result = tool.run(**tool_args)
                elif callable(tool):
                    result = tool(**tool_args)
                else:
                    result = f"Tool {tool_name} is not callable"

                logger.info(f"Tool {tool_name} result: {result}")
                executed = True
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")

        return executed

    async def _aexecute_tool_calls(self, tool_calls: List[Dict], tool_map: Dict[str, Callable]) -> bool:
        """Execute tool calls asynchronously.

        Args:
            tool_calls: List of tool call dicts with 'name' and 'args' keys
            tool_map: Mapping from tool name to tool callable

        Returns:
            True if any tools were executed
        """
        if not tool_calls:
            return False

        logger.info(f"Executing {len(tool_calls)} tool calls (async)...")
        executed = False

        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})

            if tool_name not in tool_map:
                logger.warning(f"Unknown tool: {tool_name}")
                continue

            try:
                logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                tool = tool_map[tool_name]

                # Handle different tool types - prefer async methods
                if hasattr(tool, "ainvoke"):
                    result = await tool.ainvoke(tool_args)
                elif hasattr(tool, "invoke"):
                    result = tool.invoke(tool_args)
                elif hasattr(tool, "run"):
                    result = tool.run(**tool_args)
                elif callable(tool):
                    result = tool(**tool_args)
                else:
                    result = f"Tool {tool_name} is not callable"

                logger.info(f"Tool {tool_name} result: {result}")
                executed = True
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")

        return executed

    # -*- Public Functions
    def get_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        """Get the user memories for a given user id"""
        if self.db:
            if user_id is None:
                user_id = DEFAULT_USER_ID
            # Refresh from the Db
            memories = self.read_from_db(user_id=user_id)
            if memories is None:
                return []
            result = memories.get(user_id, [])
            return result if isinstance(result, list) else []
        else:
            logger.warning("Memory Db not provided.")
            return []

    async def aget_user_memories(self, user_id: Optional[str] = None) -> Optional[List[UserMemory]]:
        """Get the user memories for a given user id"""
        if self.db:
            if user_id is None:
                user_id = DEFAULT_USER_ID
            # Refresh from the Db
            memories = await self.aread_from_db(user_id=user_id)
            if memories is None:
                return []
            result = memories.get(user_id, [])
            return result if isinstance(result, list) else []
        else:
            logger.warning("Memory Db not provided.")
            return []

    def get_user_memory(self, memory_id: str, user_id: Optional[str] = None) -> Optional[UserMemory]:
        """Get the user memory for a given user id"""
        if self.db:
            if user_id is None:
                user_id = DEFAULT_USER_ID
            # Refresh from the DB
            memories = self.read_from_db(user_id=user_id)
            if memories is None:
                return None
            memories_for_user = memories.get(user_id, [])
            if not isinstance(memories_for_user, list):
                return None
            for memory in memories_for_user:
                if memory.memory_id == memory_id:
                    return memory  # type: ignore[no-any-return]
            return None
        else:
            logger.warning("Memory Db not provided.")
            return None

    def add_user_memory(
        self,
        memory: UserMemory,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Add a user memory for a given user id
        Args:
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """
        if self.db:
            if memory.memory_id is None:
                from uuid import uuid4

                memory_id = memory.memory_id or str(uuid4())
                memory.memory_id = memory_id

            if user_id is None:
                user_id = DEFAULT_USER_ID
            memory.user_id = user_id

            if not memory.updated_at:
                memory.updated_at = int(utc_now().timestamp())

            self._upsert_db_memory(memory=memory)
            return memory.memory_id

        else:
            logger.warning("Memory Db not provided.")
            return None

    def replace_user_memory(
        self,
        memory_id: str,
        memory: UserMemory,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """Replace a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to replace
            memory (UserMemory): The memory to add
            user_id (Optional[str]): The user id to add the memory to. If not provided, the memory is added to the "default" user.
        Returns:
            str: The id of the memory
        """
        if self.db:
            if user_id is None:
                user_id = DEFAULT_USER_ID

            if not memory.updated_at:
                memory.updated_at = int(utc_now().timestamp())

            memory.memory_id = memory_id
            memory.user_id = user_id

            self._upsert_db_memory(memory=memory)

            return memory.memory_id
        else:
            logger.warning("Memory Db not provided.")
            return None

    def clear(self) -> None:
        """Clears the memory."""
        if self.db:
            result = self.db.clear_memories()
            if hasattr(result, "__await__"):
                import asyncio

                asyncio.create_task(result)  # type: ignore[unused-coroutine]

    def delete_user_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Delete a user memory for a given user id
        Args:
            memory_id (str): The id of the memory to delete
            user_id (Optional[str]): The user id to delete the memory from. If not provided, the memory is deleted from the "default" user.
        """
        if user_id is None:
            user_id = "default"

        if self.db:
            self._delete_db_memory(memory_id=memory_id, user_id=user_id)
        else:
            logger.warning("Memory DB not provided.")
            return None

    def clear_user_memories(self, user_id: Optional[str] = None) -> None:
        """Clear all memories for a specific user.

        Args:
            user_id (Optional[str]): The user id to clear memories for. If not provided, clears memories for the "default" user.
        """
        if user_id is None:
            logger.warning("Using default user id.")
            user_id = "default"

        if not self.db:
            logger.warning("Memory DB not provided.")
            return

        if isinstance(self.db, MemoryService):
            raise ValueError(
                "clear_user_memories() is not supported with an async DB. Please use aclear_user_memories() instead."
            )

        # TODO: This is inefficient - we fetch all memories just to get their IDs.
        # Extend delete_user_memories() to accept just user_id and delete all memories
        # for that user directly without requiring a list of memory_ids.
        memories = self.get_user_memories(user_id=user_id)
        if not memories:
            logger.debug(f"No memories found for user {user_id}")
            return

        # Extract memory IDs
        memory_ids = [mem.memory_id for mem in memories if mem.memory_id]

        if memory_ids:
            # Delete all memories in a single batch operation
            self.db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)
            logger.debug(f"Cleared {len(memory_ids)} memories for user {user_id}")

    async def aclear_user_memories(self, user_id: Optional[str] = None) -> None:
        """Clear all memories for a specific user (async).

        Args:
            user_id (Optional[str]): The user id to clear memories for. If not provided, clears memories for the "default" user.
        """
        if user_id is None:
            user_id = "default"

        if not self.db:
            logger.warning("Memory DB not provided.")
            return

        if isinstance(self.db, MemoryService):
            memories = await self.aget_user_memories(user_id=user_id)
        else:
            memories = self.get_user_memories(user_id=user_id)

        if not memories:
            logger.debug(f"No memories found for user {user_id}")
            return

        # Extract memory IDs
        memory_ids = [mem.memory_id for mem in memories if mem.memory_id]

        if memory_ids:
            # Delete all memories in a single batch operation
            if isinstance(self.db, MemoryService):
                await self.db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)
            else:
                self.db.delete_user_memories(memory_ids=memory_ids, user_id=user_id)
            logger.debug(f"Cleared {len(memory_ids)} memories for user {user_id}")

    # -*- Agent Functions
    def create_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()

        if self.db is None:
            logger.warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if isinstance(self.db, MemoryService):
            raise ValueError(
                "create_user_memories() is not supported with an async DB. Please use acreate_user_memories() instead."
            )

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if user_id is None:
            user_id = "default"

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        response = self.create_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            db=self.db,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
        )

        # We refresh from the DB
        self.read_from_db(user_id=user_id)
        return response

    async def acreate_user_memories(
        self,
        message: Optional[str] = None,
        messages: Optional[List[Message]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        logger.info(
            f"Creating memories for user {user_id}, message: {message}, messages: {messages}, agent_id: {agent_id}, team_id: {team_id}"
        )
        """Creates memories from multiple messages and adds them to the memory db."""
        self.set_log_level()

        if self.db is None:
            logger.warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if not messages and not message:
            raise ValueError("You must provide either a message or a list of messages")

        if message:
            messages = [Message(role="user", content=message)]

        if not messages or not isinstance(messages, list):
            raise ValueError("Invalid messages list")

        if user_id is None:
            user_id = "default"

        if isinstance(self.db, MemoryService):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]

        response = await self.acreate_or_update_memories(  # type: ignore
            messages=messages,
            existing_memories=existing_memories,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            db=self.db,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
        )

        # We refresh from the DB
        if isinstance(self.db, MemoryService):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)

        return response

    def update_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""

        if not self.db:
            logger.warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if not isinstance(self.db, MemoryService):
            raise ValueError(
                "update_memory_task() is not supported with an async DB. Please use aupdate_memory_task() instead."
            )

        if user_id is None:
            user_id = "default"

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        # The memory manager updates the DB directly
        response = self.run_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        self.read_from_db(user_id=user_id)

        return response

    async def aupdate_memory_task(self, task: str, user_id: Optional[str] = None) -> str:
        """Updates the memory with a task"""
        self.set_log_level()

        if not self.db:
            logger.warning("MemoryDb not provided.")
            return "Please provide a db to store memories"

        if user_id is None:
            user_id = "default"

        if isinstance(self.db, MemoryService):
            memories = await self.aread_from_db(user_id=user_id)
        else:
            memories = self.read_from_db(user_id=user_id)

        if memories is None:
            memories = {}

        existing_memories = memories.get(user_id, [])  # type: ignore
        existing_memories = [{"memory_id": memory.memory_id, "memory": memory.memory} for memory in existing_memories]
        # The memory manager updates the DB directly
        response = await self.arun_memory_task(  # type: ignore
            task=task,
            existing_memories=existing_memories,
            user_id=user_id,
            db=self.db,
            delete_memories=self.delete_memories,
            update_memories=self.update_memories,
            add_memories=self.add_memories,
            clear_memories=self.clear_memories,
        )

        # We refresh from the DB
        if isinstance(self.db, MemoryService):
            await self.aread_from_db(user_id=user_id)
        else:
            self.read_from_db(user_id=user_id)

        return response

    # -*- Memory Db Functions
    def _upsert_db_memory(self, memory: UserMemory) -> str:
        """Use this function to add a memory to the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")
            result = self.db.upsert_user_memory(memory=memory)
            if hasattr(result, "__await__"):
                import asyncio

                asyncio.create_task(result)  # type: ignore[unused-coroutine]
            return "Memory added successfully"
        except Exception as e:
            logger.warning(f"Error storing memory in db: {e}")
            return f"Error adding memory: {e}"

    def _delete_db_memory(self, memory_id: str, user_id: Optional[str] = None) -> str:
        """Use this function to delete a memory from the database."""
        try:
            if not self.db:
                raise ValueError("Memory db not initialized")

            if user_id is None:
                user_id = DEFAULT_USER_ID

            result = self.db.delete_user_memory(memory_id=memory_id, user_id=user_id)
            if hasattr(result, "__await__"):
                import asyncio

                asyncio.create_task(result)  # type: ignore[unused-coroutine]
            return "Memory deleted successfully"
        except Exception as e:
            logger.warning(f"Error deleting memory in db: {e}")
            return f"Error deleting memory: {e}"

    # -*- Utility Functions
    def search_user_memories(
        self,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        retrieval_method: Optional[Literal["last_n", "first_n", "agentic"]] = None,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Search through user memories using the specified retrieval method.

        Args:
            query: The search query for agentic search. Required if retrieval_method is "agentic".
            limit: Maximum number of memories to return. Defaults to self.retrieval_limit if not specified. Optional.
            retrieval_method: The method to use for retrieving memories. Defaults to self.retrieval if not specified.
                - "last_n": Return the most recent memories
                - "first_n": Return the oldest memories
                - "agentic": Return memories most similar to the query, but using an agentic approach
            user_id: The user to search for. Optional.

        Returns:
            A list of UserMemory objects matching the search criteria.
        """

        if user_id is None:
            user_id = "default"

        self.set_log_level()

        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        # Use default retrieval method if not specified
        retrieval_method = retrieval_method
        # Use default limit if not specified
        limit = limit

        # Handle different retrieval methods
        if retrieval_method == "agentic":
            if not query:
                raise ValueError("Query is required for agentic search")

            return self._search_user_memories_agentic(user_id=user_id, query=query, limit=limit)

        elif retrieval_method == "first_n":
            return self._get_first_n_memories(user_id=user_id, limit=limit)

        else:  # Default to last_n
            return self._get_last_n_memories(user_id=user_id, limit=limit)

    def _get_response_format(self) -> Union[Dict[str, Any], Type[BaseModel]]:
        """Get response format for structured output.

        Note: This method is deprecated for LangChain models.
        Use with_structured_output() instead.
        """
        # LangChain models use with_structured_output() directly
        # This method is kept for backwards compatibility
        return MemorySearchResponse

    def _search_user_memories_agentic(self, user_id: str, query: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Search through user memories using agentic search."""
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        model = self.get_model()

        response_format = self._get_response_format()

        logger.debug("Searching for memories", center=True)

        # Get all memories as a list
        user_memories: List[UserMemory] = memories[user_id]
        system_message_str = "Your task is to search through user memories and return the IDs of the memories that are related to the query.\n"
        system_message_str += "\n<user_memories>\n"
        for memory in user_memories:
            system_message_str += f"ID: {memory.memory_id}\n"
            system_message_str += f"Memory: {memory.memory}\n"
            if memory.topics:
                system_message_str += f"Topics: {','.join(memory.topics)}\n"
            system_message_str += "\n"
        system_message_str = system_message_str.strip()
        system_message_str += "\n</user_memories>\n\n"
        system_message_str += "REMEMBER: Only return the IDs of the memories that are related to the query."

        if response_format == {"type": "json_object"}:
            # MemorySearchResponse is a class, not a type, so pass it directly
            system_message_str += "\n" + get_json_output_prompt(MemorySearchResponse)  # type: ignore[arg-type]  # type: ignore

        messages_for_model = [
            Message(role="system", content=system_message_str),
            Message(
                role="user",
                content=f"Return the IDs of the memories related to the following query: {query}",
            ),
        ]

        # Generate a response from the Model using LangChain API
        # Use with_structured_output for structured responses
        memory_search: Optional[MemorySearchResponse] = None
        try:
            model_with_structure = model.with_structured_output(MemorySearchResponse)
            memory_search_raw = model_with_structure.invoke(messages_for_model)
            if isinstance(memory_search_raw, MemorySearchResponse):
                memory_search = memory_search_raw
            elif isinstance(memory_search_raw, BaseModel):
                memory_search = memory_search_raw  # type: ignore[assignment]
            else:
                memory_search = None
        except Exception:
            # Fallback to regular invoke and parse response
            try:
                response = model.invoke(messages_for_model)
                if isinstance(response.content, str):
                    memory_search = parse_response_model_str(response.content, MemorySearchResponse)  # type: ignore
                else:
                    memory_search = None
            except Exception as e:
                logger.warning(f"Failed to search memories: {e}")
                return []

        if memory_search is None:
            logger.warning("Failed to convert memory_search response to MemorySearchResponse")
            return []

        memories_to_return = []
        if memory_search:
            for memory_id in memory_search.memory_ids:
                for memory in user_memories:
                    if memory.memory_id == memory_id:
                        memories_to_return.append(memory)
        return memories_to_return[:limit]

    def _get_last_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the most recent user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the most recent UserMemory objects.
        """
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        memories_list = memories.get(user_id, [])

        # Sort memories by updated_at timestamp if available
        if memories_list:
            # Sort memories by updated_at timestamp (newest first)
            # If updated_at is None, place at the beginning of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda m: m.updated_at if m.updated_at is not None else 0,
            )
        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[-limit:]

        return sorted_memories_list

    def _get_first_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Get the oldest user memories.

        Args:
            limit: Maximum number of memories to return.

        Returns:
            A list of the oldest UserMemory objects.
        """
        memories = self.read_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        MAX_UNIX_TS = 2**63 - 1
        memories_list = memories.get(user_id, [])
        # Sort memories by updated_at timestamp if available
        if memories_list:
            # Sort memories by updated_at timestamp (oldest first)
            # If updated_at is None, place at the end of the list
            sorted_memories_list = sorted(
                memories_list,
                key=lambda m: m.updated_at if m.updated_at is not None else MAX_UNIX_TS,
            )

        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[:limit]

        return sorted_memories_list

    # -*- Async Utility Functions for search_user_memories
    async def asearch_user_memories(
        self,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        retrieval_method: Optional[Literal["last_n", "first_n", "agentic"]] = None,
        user_id: Optional[str] = None,
    ) -> List[UserMemory]:
        """Async version: Search through user memories using the specified retrieval method.

        Args:
            query: The search query for agentic search. Required if retrieval_method is "agentic".
            limit: Maximum number of memories to return. Defaults to self.retrieval_limit if not specified. Optional.
            retrieval_method: The method to use for retrieving memories. Defaults to self.retrieval if not specified.
                - "last_n": Return the most recent memories
                - "first_n": Return the oldest memories
                - "agentic": Return memories most similar to the query, but using an agentic approach
            user_id: The user to search for. Optional.

        Returns:
            A list of UserMemory objects matching the search criteria.
        """
        if user_id is None:
            user_id = "default"

        self.set_log_level()

        memories = await self.aread_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        # Handle different retrieval methods
        if retrieval_method == "agentic":
            if not query:
                raise ValueError("Query is required for agentic search")

            return await self._asearch_user_memories_agentic(user_id=user_id, query=query, limit=limit)

        elif retrieval_method == "first_n":
            return await self._aget_first_n_memories(user_id=user_id, limit=limit)

        else:  # Default to last_n
            return await self._aget_last_n_memories(user_id=user_id, limit=limit)

    async def _aget_last_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Async version: Get the most recent user memories."""
        memories = await self.aread_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        memories_list = memories.get(user_id, [])

        if memories_list:
            sorted_memories_list = sorted(
                memories_list,
                key=lambda m: m.updated_at if m.updated_at is not None else 0,
            )
        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[-limit:]

        return sorted_memories_list

    async def _aget_first_n_memories(self, user_id: str, limit: Optional[int] = None) -> List[UserMemory]:
        """Async version: Get the oldest user memories."""
        memories = await self.aread_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        MAX_UNIX_TS = 2**63 - 1
        memories_list = memories.get(user_id, [])

        if memories_list:
            sorted_memories_list = sorted(
                memories_list,
                key=lambda m: m.updated_at if m.updated_at is not None else MAX_UNIX_TS,
            )
        else:
            sorted_memories_list = []

        if limit is not None and limit > 0:
            sorted_memories_list = sorted_memories_list[:limit]

        return sorted_memories_list

    async def _asearch_user_memories_agentic(
        self, user_id: str, query: str, limit: Optional[int] = None
    ) -> List[UserMemory]:
        """Async version: Search through user memories using agentic search."""
        memories = await self.aread_from_db(user_id=user_id)
        if memories is None:
            memories = {}

        if not memories:
            return []

        model = self.get_model()
        response_format = self._get_response_format()

        logger.debug("Searching for memories (async)", center=True)

        user_memories: List[UserMemory] = memories.get(user_id, [])
        if not user_memories:
            return []

        system_message_str = "Your task is to search through user memories and return the IDs of the memories that are related to the query.\n"
        system_message_str += "\n<user_memories>\n"
        for memory in user_memories:
            system_message_str += f"ID: {memory.memory_id}\n"
            system_message_str += f"Memory: {memory.memory}\n"
            if memory.topics:
                system_message_str += f"Topics: {','.join(memory.topics)}\n"
            system_message_str += "\n"
        system_message_str = system_message_str.strip()
        system_message_str += "\n</user_memories>\n\n"
        system_message_str += "REMEMBER: Only return the IDs of the memories that are related to the query."

        if response_format == {"type": "json_object"}:
            # MemorySearchResponse is a class, not a type, so pass it directly
            system_message_str += "\n" + get_json_output_prompt(MemorySearchResponse)  # type: ignore[arg-type]

        messages_for_model = [
            Message(role="system", content=system_message_str),
            Message(
                role="user",
                content=f"Return the IDs of the memories related to the following query: {query}",
            ),
        ]

        # Generate a response from the Model using LangChain API
        # Use with_structured_output for structured responses
        memory_search: Optional[MemorySearchResponse] = None
        try:
            model_with_structure = model.with_structured_output(MemorySearchResponse)
            memory_search_raw = await model_with_structure.ainvoke(messages_for_model)
            if isinstance(memory_search_raw, MemorySearchResponse):
                memory_search = memory_search_raw
            elif isinstance(memory_search_raw, BaseModel):
                memory_search = memory_search_raw  # type: ignore[assignment]
            else:
                memory_search = None
        except Exception:
            # Fallback to regular ainvoke and parse response
            try:
                response = await model.ainvoke(messages_for_model)
                if isinstance(response.content, str):
                    memory_search_parsed = parse_response_model_str(response.content, MemorySearchResponse)
                    if isinstance(memory_search_parsed, MemorySearchResponse):
                        memory_search = memory_search_parsed
                    else:
                        memory_search = None  # type: ignore[assignment]
                else:
                    memory_search = None
            except Exception as e:
                logger.warning(f"Failed to search memories (async): {e}")
                return []

        if memory_search is None:
            logger.warning("Failed to convert memory_search response to MemorySearchResponse")
            return []

        memories_to_return = []
        if memory_search:
            for memory_id in memory_search.memory_ids:
                for memory in user_memories:
                    if memory.memory_id == memory_id:
                        memories_to_return.append(memory)
        return memories_to_return[:limit]

    def optimize_memories(
        self,
        user_id: Optional[str] = None,
        strategy: Union[
            MemoryOptimizationStrategyType, MemoryOptimizationStrategy
        ] = MemoryOptimizationStrategyType.SUMMARIZE,
        apply: bool = True,
    ) -> List[UserMemory]:
        """Optimize user memories using the specified strategy.

        Args:
            user_id: User ID to optimize memories for. Defaults to "default".
            strategy: Optimization strategy. Can be:
                - Enum: MemoryOptimizationStrategyType.SUMMARIZE
                - Instance: Custom MemoryOptimizationStrategy instance
            apply: If True, automatically replace memories in database.

        Returns:
            List of optimized UserMemory objects.
        """
        if user_id is None:
            user_id = "default"

        if isinstance(self.db, MemoryService):
            raise ValueError(
                "optimize_memories() is not supported with an async DB. Please use aoptimize_memories() instead."
            )

        # Get user memories
        memories = self.get_user_memories(user_id=user_id)
        if not memories:
            logger.debug("No memories to optimize")
            return []

        # Get strategy instance
        if isinstance(strategy, MemoryOptimizationStrategyType):
            strategy_instance = MemoryOptimizationStrategyFactory.create_strategy(strategy)
        else:
            # Already a strategy instance
            strategy_instance = strategy

        # Optimize memories using strategy
        optimization_model = self.get_model()
        optimized_memories = strategy_instance.optimize(memories=memories, model=optimization_model)  # type: ignore[arg-type]

        # Apply to database if requested
        if apply:
            logger.debug(f"Applying optimized memories to database for user {user_id}")

            if not self.db:
                logger.warning("Memory DB not provided. Cannot apply optimized memories.")
                return optimized_memories

            # Clear all existing memories for the user
            self.clear_user_memories(user_id=user_id)

            # Add all optimized memories
            for opt_mem in optimized_memories:
                # Ensure memory has an ID (generate if needed for new memories)
                if not opt_mem.memory_id:
                    from uuid import uuid4

                    opt_mem.memory_id = str(uuid4())

                self.db.upsert_user_memory(memory=opt_mem)

        optimized_tokens = strategy_instance.count_tokens(optimized_memories)
        logger.debug(f"Optimization complete. New token count: {optimized_tokens}")

        return optimized_memories

    async def aoptimize_memories(
        self,
        user_id: Optional[str] = None,
        strategy: Union[
            MemoryOptimizationStrategyType, MemoryOptimizationStrategy
        ] = MemoryOptimizationStrategyType.SUMMARIZE,
        apply: bool = True,
    ) -> List[UserMemory]:
        """Async version of optimize_memories.

        Args:
            user_id: User ID to optimize memories for. Defaults to "default".
            strategy: Optimization strategy. Can be:
                - Enum: MemoryOptimizationStrategyType.SUMMARIZE
                - Instance: Custom MemoryOptimizationStrategy instance
            apply: If True, automatically replace memories in database.

        Returns:
            List of optimized UserMemory objects.
        """
        if user_id is None:
            user_id = "default"

        # Get user memories - handle both sync and async DBs
        if isinstance(self.db, MemoryService):
            memories = await self.aget_user_memories(user_id=user_id)
        else:
            memories = self.get_user_memories(user_id=user_id)

        if not memories:
            logger.debug("No memories to optimize")
            return []

        # Get strategy instance
        if isinstance(strategy, MemoryOptimizationStrategyType):
            strategy_instance = MemoryOptimizationStrategyFactory.create_strategy(strategy)
        else:
            # Already a strategy instance
            strategy_instance = strategy

        # Optimize memories using strategy (async)
        optimization_model = self.get_model()
        optimized_memories = await strategy_instance.aoptimize(memories=memories, model=optimization_model)  # type: ignore[arg-type]

        # Apply to database if requested
        if apply:
            logger.debug(f"Optimizing memories for user {user_id}")

            if not self.db:
                logger.warning("Memory DB not provided. Cannot apply optimized memories.")
                return optimized_memories

            # Clear all existing memories for the user
            await self.aclear_user_memories(user_id=user_id)

            # Add all optimized memories
            for opt_mem in optimized_memories:
                # Ensure memory has an ID (generate if needed for new memories)
                if not opt_mem.memory_id:
                    from uuid import uuid4

                    opt_mem.memory_id = str(uuid4())

                if isinstance(self.db, MemoryService):
                    await self.db.upsert_user_memory(memory=opt_mem)
                elif isinstance(self.db, MemoryService):
                    self.db.upsert_user_memory(memory=opt_mem)

        optimized_tokens = strategy_instance.count_tokens(optimized_memories)
        logger.debug(f"Memory optimization complete. New token count: {optimized_tokens}")

        return optimized_memories

    # --Memory Manager Functions--
    def determine_tools_for_model(self, tools: List[Callable]) -> List[Union[EnhancedTool, dict]]:
        # Have to reset each time, because of different user IDs
        _function_names = []
        _functions: List[Union[EnhancedTool, dict]] = []

        for tool in tools:
            try:
                function_name = tool.__name__
                if function_name in _function_names:
                    continue
                _function_names.append(function_name)
                func = EnhancedTool.from_callable(
                    tool,
                    name=function_name,
                    description=tool.__doc__,
                )
                _functions.append(func)
                logger.debug(f"Added function {func.name}")
            except Exception as e:
                logger.warning(f"Could not add function {tool}: {e}")
        return _functions

    def get_system_message(
        self,
        existing_memories: Optional[List[Dict[str, Any]]] = None,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        enable_update_memory: bool = True,
        enable_add_memory: bool = True,
    ) -> Message:
        if self.system_message is not None:
            return Message(role="system", content=self.system_message)

        memory_capture_instructions = self.memory_capture_instructions or dedent(
            """\
            Memories should capture personal information about the user that is relevant to the current conversation, such as:
            - Personal facts: name, age, occupation, location, interests, and preferences
            - Opinions and preferences: what the user likes, dislikes, enjoys, or finds frustrating
            - Significant life events or experiences shared by the user
            - Important context about the user's current situation, challenges, or goals
            - Any other details that offer meaningful insight into the user's personality, perspective, or needs
        """
        )

        # -*- Return a system message for the memory manager
        system_prompt_lines = [
            "You are a Memory Manager that is responsible for managing information and preferences about the user. "
            "You will be provided with a criteria for memories to capture in the <memories_to_capture> section and a list of existing memories in the <existing_memories> section.",
            "",
            "## When to add or update memories",
            "- Your first task is to decide if a memory needs to be added, updated, or deleted based on the user's message OR if no changes are needed.",
            "- If the user's message meets the criteria in the <memories_to_capture> section and that information is not already captured in the <existing_memories> section, you should capture it as a memory.",
            "- If the users messages does not meet the criteria in the <memories_to_capture> section, no memory updates are needed.",
            "- If the existing memories in the <existing_memories> section capture all relevant information, no memory updates are needed.",
            "",
            "## How to add or update memories",
            "- If you decide to add a new memory, create memories that captures key information, as if you were storing it for future reference.",
            "- Memories should be a brief, third-person statements that encapsulate the most important aspect of the user's input, without adding any extraneous information.",
            "  - Example: If the user's message is 'I'm going to the gym', a memory could be `John Doe goes to the gym regularly`.",
            "  - Example: If the user's message is 'My name is John Doe', a memory could be `User's name is John Doe`.",
            "- Don't make a single memory too long or complex, create multiple memories if needed to capture all the information.",
            "- Don't repeat the same information in multiple memories. Rather update existing memories if needed.",
            "- If a user asks for a memory to be updated or forgotten, remove all reference to the information that should be forgotten. Don't say 'The user used to like ...`",
            "- When updating a memory, append the existing memory with new information rather than completely overwriting it.",
            "- When a user's preferences change, update the relevant memories to reflect the new preferences but also capture what the user's preferences used to be and what has changed.",
            "",
            "## Criteria for creating memories",
            "Use the following criteria to determine if a user's message should be captured as a memory.",
            "",
            "<memories_to_capture>",
            memory_capture_instructions,
            "</memories_to_capture>",
            "",
            "## Updating memories",
            "You will also be provided with a list of existing memories in the <existing_memories> section. You can:",
            "  - Decide to make no changes.",
        ]
        if enable_add_memory:
            system_prompt_lines.append("  - Decide to add a new memory, using the `add_memory` tool.")
        if enable_update_memory:
            system_prompt_lines.append("  - Decide to update an existing memory, using the `update_memory` tool.")
        if enable_delete_memory:
            system_prompt_lines.append("  - Decide to delete an existing memory, using the `delete_memory` tool.")
        if enable_clear_memory:
            system_prompt_lines.append("  - Decide to clear all memories, using the `clear_memory` tool.")

        system_prompt_lines += [
            "You can call multiple tools in a single response if needed. ",
            "Only add or update memories if it is necessary to capture key information provided by the user.",
        ]

        if existing_memories and len(existing_memories) > 0:
            system_prompt_lines.append("\n<existing_memories>")
            for existing_memory in existing_memories:
                system_prompt_lines.append(f"ID: {existing_memory['memory_id']}")
                system_prompt_lines.append(f"Memory: {existing_memory['memory']}")
                system_prompt_lines.append("")
            system_prompt_lines.append("</existing_memories>")

        if self.additional_instructions:
            system_prompt_lines.append(self.additional_instructions)

        return Message(role="system", content="\n".join(system_prompt_lines))

    def create_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryService,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            logger.error("No model provided for memory manager")
            return "No model provided for memory manager"

        logger.debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = self._get_message_content_string(messages[0])
        else:
            input_string = f"{', '.join([self._get_message_content_string(m) for m in messages if m.role == 'user' and m.content])}"

        # Use original model directly - response() method doesn't modify model state
        # and LangChain models are thread-safe
        model_copy = self.model
        # Update the Model (set defaults, add logit etc.)
        _tools = self.determine_tools_for_model(
            self._get_db_tools(
                user_id,
                db,
                input_string,
                agent_id=agent_id,
                team_id=team_id,
                enable_add_memory=add_memories,
                enable_update_memory=update_memories,
                enable_delete_memory=True,
                enable_clear_memory=False,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
                enable_delete_memory=True,
                enable_clear_memory=False,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        # Use LangChain API: bind_tools() + invoke()
        model_with_tools = model_copy.bind_tools(_tools) if _tools else model_copy
        response = model_with_tools.invoke(messages_for_model)

        # Execute tool calls if present
        if response.tool_calls is not None and len(response.tool_calls) > 0:
            logger.info(f"Model returned {len(response.tool_calls)} tool calls, executing...")
            # Build a map of tool name -> tool (supports both functions and EnhancedTool objects)
            tool_map = {}
            for tool in _tools:
                if hasattr(tool, "name"):  # EnhancedTool or BaseTool
                    tool_map[tool.name] = tool
                elif hasattr(tool, "__name__"):  # Regular function
                    tool_map[tool.__name__] = tool

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})

                if tool_name in tool_map:
                    try:
                        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                        tool = tool_map[tool_name]
                        # Handle both callable functions and tool objects with invoke/run
                        if hasattr(tool, "invoke"):
                            result = tool.invoke(tool_args)
                        elif hasattr(tool, "run"):
                            result = tool.run(**tool_args)
                        elif callable(tool):
                            result = tool(**tool_args)
                        else:
                            result = f"Tool {tool_name} is not callable"
                        logger.info(f"Tool {tool_name} result: {result}")
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                else:
                    logger.warning(f"Unknown tool: {tool_name}")

            self.memories_updated = True
        else:
            logger.debug("Model did not return any tool calls")

        logger.debug("MemoryManager End", center=True)

        content = response.content if hasattr(response, "content") else "No response from model"
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content) if content is not None else "No response from model"

    async def acreate_or_update_memories(
        self,
        messages: List[Message],
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: Union[MemoryService],
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            logger.error("No model provided for memory manager")
            return "No model provided for memory manager"

        logger.debug("MemoryManager Start", center=True)

        if len(messages) == 1:
            input_string = self._get_message_content_string(messages[0])
        else:
            input_string = f"{', '.join([self._get_message_content_string(m) for m in messages if m.role == 'user' and m.content])}"

        # Use original model directly - response() method doesn't modify model state
        # and LangChain models are thread-safe
        model_copy = self.model
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, MemoryService):
            _tools = self.determine_tools_for_model(
                await self._aget_db_tools(
                    user_id,
                    db,
                    input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                    enable_add_memory=add_memories,
                    enable_update_memory=update_memories,
                    enable_delete_memory=True,
                    enable_clear_memory=False,
                ),
            )
        else:
            _tools = self.determine_tools_for_model(
                self._get_db_tools(
                    user_id,
                    db,
                    input_string,
                    agent_id=agent_id,
                    team_id=team_id,
                    enable_add_memory=add_memories,
                    enable_update_memory=update_memories,
                    enable_delete_memory=True,
                    enable_clear_memory=False,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories=existing_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
                enable_delete_memory=True,
                enable_clear_memory=False,
            ),
            *messages,
        ]

        # Generate a response from the Model (includes running function calls)
        # Use LangChain API: bind_tools() + ainvoke()
        model_with_tools = model_copy.bind_tools(_tools) if _tools else model_copy
        response = await model_with_tools.ainvoke(messages_for_model)

        # Execute tool calls if present
        if response.tool_calls is not None and len(response.tool_calls) > 0:
            logger.info(f"Model returned {len(response.tool_calls)} tool calls, executing...")
            # Build a map of tool name -> tool (supports both functions and EnhancedTool objects)
            tool_map = {}
            for tool in _tools:
                if hasattr(tool, "name"):  # EnhancedTool or BaseTool
                    tool_map[tool.name] = tool
                elif hasattr(tool, "__name__"):  # Regular function
                    tool_map[tool.__name__] = tool

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})

                if tool_name in tool_map:
                    try:
                        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                        tool = tool_map[tool_name]
                        # Handle both callable functions and tool objects with invoke/ainvoke
                        if hasattr(tool, "ainvoke"):
                            result = await tool.ainvoke(tool_args)
                        elif hasattr(tool, "invoke"):
                            result = tool.invoke(tool_args)
                        elif hasattr(tool, "run"):
                            result = tool.run(**tool_args)
                        elif callable(tool):
                            result = tool(**tool_args)
                        else:
                            result = f"Tool {tool_name} is not callable"
                        logger.info(f"Tool {tool_name} result: {result}")
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                else:
                    logger.warning(f"Unknown tool: {tool_name}")

            self.memories_updated = True
        else:
            logger.debug("Model did not return any tool calls")

        logger.debug("MemoryManager End", center=True)

        content = response.content if hasattr(response, "content") else "No response from model"
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content) if content is not None else "No response from model"

    def run_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: MemoryService,
        delete_memories: bool = True,
        update_memories: bool = True,
        add_memories: bool = True,
        clear_memories: bool = True,
    ) -> str:
        if self.model is None:
            logger.error("No model provided for memory manager")
            return "No model provided for memory manager"

        logger.debug("MemoryManager Start", center=True)

        # Use original model directly - response() method doesn't modify model state
        # and LangChain models are thread-safe
        model_copy = self.model
        # Update the Model (set defaults, add logit etc.)
        _tools = self.determine_tools_for_model(
            self._get_db_tools(
                user_id,
                db,
                task,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
        )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        # Use LangChain API: bind_tools() + invoke()
        model_with_tools = model_copy.bind_tools(_tools) if _tools else model_copy
        response = model_with_tools.invoke(messages_for_model)

        # Execute tool calls if present
        if response.tool_calls is not None and len(response.tool_calls) > 0:
            logger.info(f"Model returned {len(response.tool_calls)} tool calls, executing...")
            # Build a map of tool name -> tool (supports both functions and EnhancedTool objects)
            tool_map = {}
            for tool in _tools:
                if hasattr(tool, "name"):  # EnhancedTool or BaseTool
                    tool_map[tool.name] = tool
                elif hasattr(tool, "__name__"):  # Regular function
                    tool_map[tool.__name__] = tool

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})

                if tool_name in tool_map:
                    try:
                        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                        tool = tool_map[tool_name]
                        # Handle both callable functions and tool objects with invoke/run
                        if hasattr(tool, "invoke"):
                            result = tool.invoke(tool_args)
                        elif hasattr(tool, "run"):
                            result = tool.run(**tool_args)
                        elif callable(tool):
                            result = tool(**tool_args)
                        else:
                            result = f"Tool {tool_name} is not callable"
                        logger.info(f"Tool {tool_name} result: {result}")
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                else:
                    logger.warning(f"Unknown tool: {tool_name}")

            self.memories_updated = True
        else:
            logger.debug("Model did not return any tool calls")

        logger.debug("MemoryManager End", center=True)

        content = response.content if hasattr(response, "content") else "No response from model"
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content) if content is not None else "No response from model"

    async def arun_memory_task(
        self,
        task: str,
        existing_memories: List[Dict[str, Any]],
        user_id: str,
        db: Union[MemoryService],
        delete_memories: bool = True,
        clear_memories: bool = True,
        update_memories: bool = True,
        add_memories: bool = True,
    ) -> str:
        if self.model is None:
            logger.error("No model provided for memory manager")
            return "No model provided for memory manager"

        logger.debug("MemoryManager Start", center=True)

        # Use original model directly - response() method doesn't modify model state
        # and LangChain models are thread-safe
        model_copy = self.model
        # Update the Model (set defaults, add logit etc.)
        if isinstance(db, MemoryService):
            _tools = self.determine_tools_for_model(
                await self._aget_db_tools(
                    user_id,
                    db,
                    task,
                    enable_delete_memory=delete_memories,
                    enable_clear_memory=clear_memories,
                    enable_update_memory=update_memories,
                    enable_add_memory=add_memories,
                ),
            )
        else:
            _tools = self.determine_tools_for_model(
                self._get_db_tools(
                    user_id,
                    db,
                    task,
                    enable_delete_memory=delete_memories,
                    enable_clear_memory=clear_memories,
                    enable_update_memory=update_memories,
                    enable_add_memory=add_memories,
                ),
            )

        # Prepare the List of messages to send to the Model
        messages_for_model: List[Message] = [
            self.get_system_message(
                existing_memories,
                enable_delete_memory=delete_memories,
                enable_clear_memory=clear_memories,
                enable_update_memory=update_memories,
                enable_add_memory=add_memories,
            ),
            # For models that require a non-system message
            Message(role="user", content=task),
        ]

        # Generate a response from the Model (includes running function calls)
        # Use LangChain API: bind_tools() + ainvoke()
        model_with_tools = model_copy.bind_tools(_tools) if _tools else model_copy
        response = await model_with_tools.ainvoke(messages_for_model)

        # Execute tool calls if present
        if response.tool_calls is not None and len(response.tool_calls) > 0:
            logger.info(f"Model returned {len(response.tool_calls)} tool calls, executing...")
            # Build a map of tool name -> tool (supports both functions and EnhancedTool objects)
            tool_map = {}
            for tool in _tools:
                if hasattr(tool, "name"):  # EnhancedTool or BaseTool
                    tool_map[tool.name] = tool
                elif hasattr(tool, "__name__"):  # Regular function
                    tool_map[tool.__name__] = tool

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})

                if tool_name in tool_map:
                    try:
                        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                        tool = tool_map[tool_name]
                        # Handle both callable functions and tool objects with invoke/ainvoke
                        if hasattr(tool, "ainvoke"):
                            result = await tool.ainvoke(tool_args)
                        elif hasattr(tool, "invoke"):
                            result = tool.invoke(tool_args)
                        elif hasattr(tool, "run"):
                            result = tool.run(**tool_args)
                        elif callable(tool):
                            result = tool(**tool_args)
                        else:
                            result = f"Tool {tool_name} is not callable"
                        logger.info(f"Tool {tool_name} result: {result}")
                    except Exception as e:
                        logger.error(f"Error executing tool {tool_name}: {e}")
                else:
                    logger.warning(f"Unknown tool: {tool_name}")

            self.memories_updated = True
        else:
            logger.debug("Model did not return any tool calls")

        logger.debug("MemoryManager End", center=True)

        content = response.content if hasattr(response, "content") else "No response from model"
        if isinstance(content, list):
            return " ".join(str(item) for item in content)
        return str(content) if content is not None else "No response from model"

    # -*- DB Functions
    def _get_db_tools(
        self,
        user_id: str,
        db: MemoryService,
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        def _run_async(coro):
            """Helper to run async code in sync context"""
            import asyncio

            try:
                # Event loop is running, need to use a different approach
                import threading

                result = None
                exception = None

                def run_in_thread():
                    nonlocal result, exception
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        result = new_loop.run_until_complete(coro)
                        new_loop.close()
                    except Exception as e:
                        exception = e

                thread = threading.Thread(target=run_in_thread)
                thread.start()
                thread.join()

                if exception:
                    raise exception
                return result
            except RuntimeError:
                # No event loop running, safe to use asyncio.run
                return asyncio.run(coro)

        def add_memory(memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            import asyncio
            from uuid import uuid4

            from app.schemas.memory import UserMemory

            try:
                memory_id = str(uuid4())
                # Run async method in sync context
                try:
                    # Event loop is running, schedule coroutine
                    import nest_asyncio

                    nest_asyncio.apply()
                    asyncio.run(
                        db.upsert_user_memory(
                            UserMemory(
                                memory_id=memory_id,
                                user_id=user_id,
                                agent_id=agent_id,
                                team_id=team_id,
                                memory=memory,
                                topics=topics,
                                input=input_string,
                            )
                        )
                    )
                except RuntimeError:
                    # No event loop running, safe to use asyncio.run
                    asyncio.run(
                        db.upsert_user_memory(
                            UserMemory(
                                memory_id=memory_id,
                                user_id=user_id,
                                agent_id=agent_id,
                                team_id=team_id,
                                memory=memory,
                                topics=topics,
                                input=input_string,
                            )
                        )
                    )
                logger.debug(f"Memory added: {memory_id}")
                return "Memory added successfully"
            except Exception as e:
                logger.warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def update_memory(memory_id: str, memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was updated successfully or not.
            """
            from app.schemas.memory import UserMemory

            if memory == "":
                return "Can't update memory with empty string. Use the delete memory function if available."

            try:
                _run_async(
                    db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            user_id=user_id,
                            input=input_string,
                        )
                    )
                )
                logger.debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                logger.warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                _run_async(db.delete_user_memory(memory_id=memory_id, user_id=user_id))
                logger.debug("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                logger.warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        def clear_memory() -> str:
            """Use this function to remove all (or clear all) memories from the database.

            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            _run_async(db.clear_memories())
            logger.debug("Memory cleared")
            return "Memory cleared successfully"

        functions: List[Callable] = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions

    async def _aget_db_tools(
        self,
        user_id: str,
        db: Union[MemoryService],
        input_string: str,
        enable_add_memory: bool = True,
        enable_update_memory: bool = True,
        enable_delete_memory: bool = True,
        enable_clear_memory: bool = True,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> List[Callable]:
        async def add_memory(memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to add a memory to the database.
            Args:
                memory (str): The memory to be added.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was added successfully or not.
            """
            from uuid import uuid4

            from app.schemas.memory import UserMemory

            try:
                memory_id = str(uuid4())
                if isinstance(db, MemoryService):
                    await db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            user_id=user_id,
                            agent_id=agent_id,
                            team_id=team_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                else:
                    db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            user_id=user_id,
                            agent_id=agent_id,
                            team_id=team_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                logger.debug(f"Memory added: {memory_id}")
                return "Memory added successfully"
            except Exception as e:
                logger.warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        async def update_memory(memory_id: str, memory: str, topics: Optional[List[str]] = None) -> str:
            """Use this function to update an existing memory in the database.
            Args:
                memory_id (str): The id of the memory to be updated.
                memory (str): The updated memory.
                topics (Optional[List[str]]): The topics of the memory (e.g. ["name", "hobbies", "location"]).
            Returns:
                str: A message indicating if the memory was updated successfully or not.
            """
            from app.schemas.memory import UserMemory

            if memory == "":
                return "Can't update memory with empty string. Use the delete memory function if available."

            try:
                if isinstance(db, MemoryService):
                    await db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                else:
                    db.upsert_user_memory(
                        UserMemory(
                            memory_id=memory_id,
                            memory=memory,
                            topics=topics,
                            input=input_string,
                        )
                    )
                logger.debug("Memory updated")
                return "Memory updated successfully"
            except Exception as e:
                logger.warning(f"Error storing memory in db: {e}")
                return f"Error adding memory: {e}"

        async def delete_memory(memory_id: str) -> str:
            """Use this function to delete a single memory from the database.
            Args:
                memory_id (str): The id of the memory to be deleted.
            Returns:
                str: A message indicating if the memory was deleted successfully or not.
            """
            try:
                if isinstance(db, MemoryService):
                    await db.delete_user_memory(memory_id=memory_id, user_id=user_id)
                else:
                    db.delete_user_memory(memory_id=memory_id, user_id=user_id)
                logger.debug("Memory deleted")
                return "Memory deleted successfully"
            except Exception as e:
                logger.warning(f"Error deleting memory in db: {e}")
                return f"Error deleting memory: {e}"

        async def clear_memory() -> str:
            """Use this function to remove all (or clear all) memories from the database.

            Returns:
                str: A message indicating if the memory was cleared successfully or not.
            """
            if isinstance(db, MemoryService):
                await db.clear_memories()
            else:
                db.clear_memories()
            logger.debug("Memory cleared")
            return "Memory cleared successfully"

        functions: List[Callable] = []
        if enable_add_memory:
            functions.append(add_memory)
        if enable_update_memory:
            functions.append(update_memory)
        if enable_delete_memory:
            functions.append(delete_memory)
        if enable_clear_memory:
            functions.append(clear_memory)
        return functions
