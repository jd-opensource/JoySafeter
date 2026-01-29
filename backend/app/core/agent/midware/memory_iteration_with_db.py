"""MemoryManager 驱动的记忆中间件

在模型调用前：
- 根据当前用户输入检索用户的相关长期记忆（支持 last_n / first_n / agentic）
- 将检索到的记忆以结构化片段注入到系统提示，增强上下文

在模型调用后：
- 将本次用户输入提交给 MemoryManager，由其根据捕获规则判定是否新增/更新/删除记忆
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
    """Agentic Memory 中间件的扩展状态"""

    user_id: NotRequired[str | None]  # type: ignore[valid-type]
    agent_memory_context: NotRequired[str | None]  # type: ignore[valid-type]


class AgentMemoryIterationMiddleware(AgentMiddleware):
    """使用 MemoryManager 的 Agent 记忆中间件

    - before: 从 MemoryManager 检索用户相关记忆并注入系统提示
    - after: 将用户输入交由 MemoryManager 进行记忆写入/更新

    Args:
        memory_manager: 已配置的 MemoryManager 实例（需提供 model/db）
        retrieval_method: 检索方式，支持 "last_n" | "first_n" | "agentic"
        retrieval_limit: 检索条数限制
        context_header: 注入系统提示时的记忆片段标题
        enable_writeback: 是否在模型调用后写入记忆
        capture_source: 写入记忆时的来源，"user" 或 "assistant"，默认 "user"
    """

    priority = 50  # 中等优先级，与技能中间件并行执行
    state_schema = AgenticMemoryState

    def __init__(
        self,
        *,
        memory_manager: MemoryManager,
        retrieval_method: str = "last_n",
        retrieval_limit: int = 5,
        context_header: str = "## 相关用户记忆",
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
        """获取当前用户的 user_id

        Returns:
            user_id 字符串，如果不存在则返回 None
        """
        if not self.user_id:
            logger.warning("No user_id configured in middleware instance")
        return self.user_id

    def _extract_user_input(self, request: ModelRequest) -> Optional[str]:
        """从请求中提取用户输入文本（LangGraph ModelRequest 格式）"""
        # 从消息列表中取最后一个 HumanMessage 消息
        if hasattr(request, "messages") and request.messages:
            try:
                # 从后往前遍历消息列表，找到最后一个 HumanMessage
                for msg in reversed(request.messages):
                    # 检查是否为 HumanMessage 类型
                    if isinstance(msg, HumanMessage):
                        content = getattr(msg, "content", None)
                        if content:
                            # 处理不同类型的 content
                            if isinstance(content, str):
                                extracted = content
                            elif isinstance(content, list):
                                # 处理 content_blocks 格式
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

                    # 兼容性：检查消息的 type 属性（LangChain 消息类型）
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

                    # 兼容性：检查字典格式的消息
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
        """从 ModelResponse 中提取助手响应文本（LangGraph ModelResponse 格式）"""
        # 优先检查 response.content（如果是字符串）
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                if content.strip():
                    logger.debug(f"Extracted assistant response from response.content: {content[:100]}...")
                    return content

        # 从消息列表中取最后一个 AIMessage 消息
        if hasattr(response, "messages") and response.messages:
            try:
                # 从后往前遍历消息列表，找到最后一个 AIMessage
                for msg in reversed(response.messages):
                    # 检查是否为 AIMessage 类型
                    if isinstance(msg, AIMessage):
                        content = getattr(msg, "content", None)
                        if content:
                            # 处理不同类型的 content
                            if isinstance(content, str):
                                extracted = content
                            elif isinstance(content, list):
                                # 处理 content_blocks 格式
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

                    # 兼容性：检查消息的 type 属性（LangChain 消息类型）
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

                    # 兼容性：检查字典格式的消息
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
        """将 UserMemory 列表格式化为系统提示片段"""
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
        """按配置从 MemoryManager 检索记忆并构建上下文（统一使用异步方式）"""
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
        """可在此处进行必要初始化"""
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
        """在模型调用前注入记忆；在调用后按需写入记忆（同步版本，内部使用 asyncio.run）"""
        user_id = self._get_user_id()

        if not user_id:
            logger.warning("Skipping memory operations: no user_id available")
            return handler(request)

        # 构建并注入记忆上下文
        # 简化：直接用 asyncio.run() 运行异步方法
        # 如果已在事件循环中，LangGraph 会调用 awrap_model_call 而不是这里
        memory_context = asyncio.run(self._build_memory_context(request, user_id))

        if memory_context:
            # 记录到状态中，便于下游使用或调试
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

        # 调用模型
        logger.debug(f"Calling model handler for user_id={user_id}")
        response = handler(request)

        # 写入记忆：使用用户输入作为记忆捕获的依据
        if self.enable_writeback:
            logger.info(f"Attempting to write back memory for user_id={user_id}, capture_source={self.capture_source}")
            try:
                message_text: Optional[str] = None
                if self.capture_source == "assistant":
                    # 从 ModelResponse 中提取助手响应内容
                    message_text = self._extract_assistant_response(response)
                else:
                    # 默认从用户输入捕获
                    message_text = self._extract_user_input(request)

                if message_text and message_text.strip():
                    logger.info(
                        f"Writing memory for user_id={user_id}, "
                        f"message_length={len(message_text)}, capture_source={self.capture_source}"
                    )
                    # 简化：直接用 asyncio.run() 运行异步方法
                    # 如果已在事件循环中，LangGraph 会调用 awrap_model_call 而不是这里
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
        """异步版本：在模型调用前注入记忆；在调用后按需写入记忆"""
        user_id = self._get_user_id()

        if not user_id:
            logger.warning("Skipping memory operations: no user_id available")
            return await handler(request)

        # 构建并注入记忆上下文
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

        # 调用模型
        logger.debug(f"Calling model handler for user_id={user_id}")
        response = await handler(request)

        # 写入记忆
        if self.enable_writeback:
            logger.info(f"Attempting to write back memory for user_id={user_id}, capture_source={self.capture_source}")
            try:
                message_text: Optional[str] = None
                if self.capture_source == "assistant":
                    # 从 ModelResponse 中提取助手响应内容
                    message_text = self._extract_assistant_response(response)
                else:
                    # 默认从用户输入捕获
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
