"""
Canonical Agent runtime entrypoint.

Runtime (current):
- Frontend launches backend via `backend/agent/run_server.py`
- FastAPI app: `backend/agent/server.py`
- Execution loop: `backend/agent/main.py` (this file)

We intentionally avoid duplicate entrypoints (e.g. the old `agent/core/main.py`)
to keep the codebase DRY and reduce confusion.
"""

from __future__ import annotations

import asyncio
import os
import queue
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger
from mcp import ClientSession

from app.dynamic_agent.agent_core.task_manager import TaskManager
from app.dynamic_agent.core.config import conf
from app.dynamic_agent.core.constants import MCP_TOOL_JOINER, CtfDetectionSource
from app.dynamic_agent.infra.context import docker_manager, tool_registry
from app.dynamic_agent.infra.llm import create_llm_instance
from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.infra.tool_registry import ToolMetadata
from app.dynamic_agent.observability.langfuse import callbacks
from app.dynamic_agent.observability.tracking_processor import TrackingEventProcessor, set_tracking_processor
from app.dynamic_agent.prompts.system_prompts import (
    SceneType,
    detect_scene,
    get_system_prompt_with_scene,
)
from app.dynamic_agent.storage import StorageManager, initialize_storage
from app.dynamic_agent.storage.memory.store import MemoryType
from app.dynamic_agent.storage.session.ctf import get_ctf_session_store
from app.dynamic_agent.tools import (
    TODO_TOOLS,
    agent_tool,
    check_iterations,
    final_response,
    knowledge_search,
    python_coder_tool,
    think_tool,
)
from app.dynamic_agent.tools.awares import get_current_time
from app.dynamic_agent.tools.awares.workspace import workspace_tool
from app.dynamic_agent.tools.base import base_tools, base_tools_for_selection
from app.dynamic_agent.tools.builtin.ask_human_tool import ask_human
from app.dynamic_agent.tools.valid_tools.json_valid_tools import valid_json_array, valid_json_dict
from app.dynamic_agent.utils.mcp_client_helper import MultiMCP

ENABLE_EAGER_RAG = os.getenv("ENABLE_EAGER_RAG", "false").lower() == "true"


async def fetch_tools_from_mcp(session: ClientSession) -> List[Dict[str, Any]]:
    """Fetch available tools from MCP server."""
    result = await session.list_tools()
    tools = []
    for tool in result.tools:
        tools.append(
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
        )
    return tools


# Initialize storage system
storage: Optional[StorageManager] = None


async def init_storage():
    """Initialize storage manager (call once at startup)."""
    global storage
    if storage is None:
        logger.info("🔄 Initializing storage system...")
        try:
            # Add timeout protection (30 seconds)
            llm_provider = create_llm_instance()
            llm_provider.bind(parallel_tool_calls=False)
            storage = await asyncio.wait_for(
                initialize_storage(docker_manager=docker_manager, llm_provider=llm_provider), timeout=30
            )
            logger.info("✅ Storage system initialized successfully")
        except asyncio.TimeoutError:
            logger.error("❌ Storage system initialization timed out (30s)")
            logger.error("💡 Possible causes:")
            logger.error("   - PostgreSQL service not started")
            logger.error("   - Wrong database connection parameters")
            logger.error("   - Network connection issues")
            raise
        except Exception as e:
            logger.error(f"❌ Storage system initialization failed: {e}")
            raise
    return storage


def _is_placeholder_flag(flag: str) -> bool:
    """Filter out common LLM placeholder flags (CTF)."""
    if not flag:
        return True
    lower = flag.lower()
    placeholders = {
        "flag{...}",
        "flag{example}",
        "flag{placeholder}",
        "flag{abc123}",
        "flag{test}",
        "flag{admin}",
        "ctf{...}",
        "ctf{example}",
    }
    if lower in placeholders:
        return True
    suspicious_words = {"bypass", "injection", "exploit", "attack", "vuln", "hack", "pwn", "solved"}
    if any(word in lower for word in suspicious_words):
        return True
    return False


def convert_dict_to_langchain_message(msg: Dict[str, Any]) -> BaseMessage:
    """
    Convert a dict-based message to a LangChain message object.

    Ensures tool_calls/tool_call_id are preserved to avoid OpenAI API errors.
    """
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if role == "system":
        return SystemMessage(content=content)
    if role in ("user", "human"):
        return HumanMessage(content=content)
    if role in ("assistant", "ai"):
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            lc_tool_calls = []
            for tc in tool_calls:
                lc_tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    }
                )
            return AIMessage(content=content, tool_calls=lc_tool_calls)
        return AIMessage(content=content)
    if role == "tool":
        tool_call_id = msg.get("tool_call_id", "")
        return ToolMessage(content=content, tool_call_id=tool_call_id)

    # Default fallback
    return HumanMessage(content=content)


def convert_history_to_langchain_messages(history: List[Dict[str, Any]]) -> List[BaseMessage]:
    """Convert dict message list to LangChain messages."""
    return [convert_dict_to_langchain_message(m) for m in history]


def validate_tool_call_pairs(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    OpenAI requires: every assistant tool_call_id must have a corresponding tool message.
    Remove assistant messages that contain orphan tool_calls.
    """
    if not history:
        return history

    responded_tool_call_ids = set()
    for msg in history:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            responded_tool_call_ids.add(msg["tool_call_id"])

    validated: List[Dict[str, Any]] = []
    for msg in history:
        if msg.get("role") in ("assistant", "ai") and msg.get("tool_calls"):
            tool_calls = msg["tool_calls"]
            all_responded = all(tc.get("id") in responded_tool_call_ids for tc in tool_calls)
            if all_responded:
                validated.append(msg)
            else:
                missing_ids = [tc.get("id") for tc in tool_calls if tc.get("id") not in responded_tool_call_ids]
                logger.warning(f"⚠ Removed assistant message with orphaned tool_calls: {missing_ids}")
        else:
            validated.append(msg)

    return validated


async def run(user_message: str, metadata: Dict[str, Any]) -> str:
    """
    Main agent execution loop with context management.

    Handles:
    1. Session context loading (history, container, tasks)
    2. Scenario identification
    3. Tool selection and execution
    4. Result storage and memory management
    """
    # Initialize storage if needed
    global storage
    if storage is None:
        storage = await init_storage()

    response_queue = metadata.get("response_queue")
    session_id = metadata.get("langfuse_session_id", "default_session")
    user_id = metadata.get("langfuse_user_id", "default_user")

    # Load or create session context
    context_result = await storage.context.get_session(session_id)
    if not context_result:
        context = await storage.initialize_session(user_id, session_id, metadata)
        logger.info(f"✓ Created new session: {session_id}")
    else:
        context = context_result
        container_info = await storage.get_container_info(session_id, user_id)
        context.container_info = container_info
        logger.info(f"✓ Loaded existing session: {session_id}")

    # Identify scenario
    # todo
    scenario = await storage.context.identify_scenario(session_id, user_message)
    logger.info(f"✓ Identified scenario: {scenario}")

    # CTF Intent Detection and Session Management (sticky)
    is_ctf = False
    non_ctf_guard = metadata.get("non_ctf_guard", False)

    if conf.CTF_MODE_ENABLED and not non_ctf_guard:
        explicit_ctf = metadata.get("is_ctf", None)
        detection_source = CtfDetectionSource.HEURISTIC

        if explicit_ctf is not None:
            is_ctf = bool(explicit_ctf)
            detection_source = CtfDetectionSource.USER
        elif conf.CTF_AUTO_DETECT and detect_scene(user_message) == SceneType.CTF.value:
            is_ctf = True
            detection_source = CtfDetectionSource.HEURISTIC

        ctf_store = get_ctf_session_store()
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
        except (ValueError, AttributeError):
            session_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(session_id))

        ctf_session = ctf_store.get_or_create_session(
            session_uuid,
            is_ctf=is_ctf,
            challenge_summary=user_message[:512] if is_ctf else "",
            detection_source=detection_source,
            non_ctf_guard=non_ctf_guard,
        )

        # Once enabled, keep enabled until session closes
        if getattr(ctf_session, "is_ctf", False):
            is_ctf = True
        elif is_ctf and not getattr(ctf_session, "is_ctf", False):
            ctf_session.is_ctf = True
            ctf_session.challenge_summary = user_message[:512]
            ctf_session.detection_source = detection_source

        if is_ctf:
            ctf_session.activate()
            logger.info(f"🚩 CTF mode activated (source: {detection_source.value})")

        metadata["ctf_session_id"] = str(ctf_session.session_id)

    metadata["is_ctf"] = is_ctf

    # Initialize TODO display (safe for server; falls back if rich not available)
    try:
        from app.dynamic_agent.infra.todo_display import get_todo_display

        todo_display = get_todo_display()
        todo_display.create_panel(title=f"📋 Todos ({scenario})")
        todo_display.start_display()
        metadata["todo_display"] = todo_display
    except Exception as e:
        logger.debug(f"TODO display init skipped: {e}")

    # Load conversation history (compressed) from storage, then validate tool-call pairs
    history = await storage.context.get_conversation_history(session_id, limit=30)
    compressed_history = await storage.compressor.compress_messages(history, max_messages=15)
    compressed_history = validate_tool_call_pairs(compressed_history)
    logger.info(f"✓ Loaded {len(compressed_history)} messages from history")

    logger.debug("Calling storage.context.add_message for user message...")
    # Save user message immediately to get ID for task linking
    user_message_id = await storage.context.add_message(session_id, "user", user_message, metadata)
    logger.debug(f"User message saved, ID: {user_message_id}")

    # Create Task and get tracking handler
    logger.debug("Creating TaskManager instance...")
    if storage.backend.task_dao is None:
        raise RuntimeError("TaskDAO not initialized")
    task_manager = TaskManager(storage.backend.task_dao)
    logger.debug("TaskManager instance created")

    logger.debug("Calling task_manager.create_task()...")
    task_id, tracking_handler = await task_manager.create_task(
        session_id=session_id, user_input=user_message, message_id=user_message_id, metadata=metadata
    )

    # Add task_id and tracking handler to metadata so sub-agents can access them
    metadata["task_id"] = task_id
    metadata["tracking_handler"] = tracking_handler  # Singleton handler

    # Set metadata in context EARLY so task_id is available for tracking
    MetadataContext.set(metadata)

    # ✅ IMMEDIATELY notify streaming endpoint that task_id is ready (before tool loading)
    if "task_id_holder" in metadata and "task_id_event" in metadata:
        metadata["task_id_holder"]["task_id"] = task_id
        metadata["task_id_event"].set()
        logger.info(f"✅ Task created and event triggered immediately: {task_id}")
    else:
        logger.warning("⚠️ Cannot notify task_id - missing event/holder in metadata")

    # todo: more external mcp servers
    mcp_api_url = context.container_info.mcp_api if context.container_info and context.container_info.mcp_api else ""
    SERVER_CONFIGS: List[Dict[str, str]] = [
        {
            "name": "seclens",
            "url": mcp_api_url,
            "description": "enhanced basic toolkit for web security and more than that",
        },
        # {"name": "seclens", "url": "http://127.0.0.1:8000/sse"},
        # {"name": "serverB", "url": "http://127.0.0.1:8000/sse"},
    ]

    async with MultiMCP(SERVER_CONFIGS, namespace="server", collision_policy="namespace") as mcp:
        # Discover tools
        tools_per = await mcp.discover_tools()
        logger.info("Per-server tools:")
        for server, server_tools in tools_per.items():
            logger.info(f"- {server}: {[t['name'] for t in server_tools]}")

        # Namespaced tools
        # ns_tools = mcp.namespaced_tools()
        # logger.info("\nNamespaced tools:")
        # for t in ns_tools:
        #     logger.info(f"- {t['name']} ({t['server']} -> {t['original_name']})")

        # Export as LangChain tools if needed
        mcp_tools = []
        try:
            # todo: use async for long-running tasks
            mcp_tools = mcp.to_langchain_tools(tool_call_timeout=5 * 3600)
            logger.info(f"\nLangChain tools built: {len(mcp_tools)}")
            # Example integration into Agent: agent = initialize_agent(tools=lc_tools, ...)
            # tool_map = {t.name: t for t in lc_tools}
        except ImportError:
            logger.info("LangChain or pydantic not installed, skipping export.")

        tool_map = {}
        tool_map.update({f"{tool.name}": tool for tool in mcp_tools})

        tool_registry.clear()
        for tool_name, tool in tool_map.items():
            tool_registry.register(
                ToolMetadata(
                    name=tool_name,
                    category="default",
                    description=tool.description,
                    # todo add extra info to tool conf
                    # priority=conf.get('priority', ToolPriority.MEDIUM),
                    # keywords=conf.get('tags', set()),
                    keywords=set(),
                    # dependencies=conf.get('dependencies', set()),
                    # scenarios=conf.get('scenarios', set()),
                    scenarios=set(),
                    # cost_estimate=conf.get('cost_estimate', 5),
                    cost_estimate=5,
                ),
                tool,
            )

        # ------------------------------------------------------------------
        # Tools for Sub-Agent selection (used by agent_tool executor)
        # ------------------------------------------------------------------
        from langchain_core.tools import BaseTool

        sub_agent_tools: List[BaseTool] = [
            think_tool,
            valid_json_array,
            valid_json_dict,
            workspace_tool,
            get_current_time,
        ]

        base_tools.clear()
        base_tools.extend(
            [
                *sub_agent_tools,
                python_coder_tool,
                knowledge_search,
                # ask_human,
                # *TODO_TOOLS,
            ]
        )

        base_tools_for_selection.clear()
        tool1 = tool_registry.get_tool(f"{conf.NAME}{MCP_TOOL_JOINER}list_all_tool_categories")
        tool2 = tool_registry.get_tool(f"{conf.NAME}{MCP_TOOL_JOINER}list_tools_by_categories")
        # Filter out None tools
        tools_for_selection: List[BaseTool] = [t for t in [*sub_agent_tools, tool1, tool2] if t is not None]
        base_tools_for_selection.extend(tools_for_selection)
        # Remove None tools to avoid LangChain errors
        base_tools_for_selection[:] = [t for t in base_tools_for_selection if t is not None]

        # Metadata already set earlier (after task creation)
        try:
            # ------------------------------------------------------------------
            # Main Agent toolset: keep small, delegate execution to Sub-Agent.
            # ------------------------------------------------------------------
            tool_instances: List[Any]
            if is_ctf:
                tool_instances = [
                    *base_tools,
                    agent_tool,
                    think_tool,
                    final_response,
                    check_iterations,
                    ask_human,
                    *TODO_TOOLS,
                ]
            else:
                tool_instances = [
                    *base_tools,
                    agent_tool,
                    think_tool,
                    final_response,
                    check_iterations,
                    # ask_human,
                    # *TODO_TOOLS,
                ]

            # Also expose basic validators/utility tools (tiny, high-signal)
            # tool_instances.extend([valid_json_array, valid_json_dict, workspace_tool, get_current_time])

            # Dedupe by tool name
            seen = set()
            deduped = []
            for t in tool_instances:
                name = getattr(t, "name", None)
                if not name or name in seen:
                    continue
                seen.add(name)
                deduped.append(t)
            tool_instances = deduped

            llm = create_llm_instance()
            llm.bind(parallel_tool_calls=False)

            # Scene-specific system prompt
            system_prompt = (
                get_system_prompt_with_scene(scene="ctf")
                if is_ctf
                else get_system_prompt_with_scene(scene=metadata.get("mode", ""))
            )

            # Build final user message (optionally inject hints)
            context_enriched_message = (
                f"IMPORTANT: Your task is to {user_message}" if not compressed_history else user_message
            )
            hint_summary = metadata.get("hint_summary", "")
            if hint_summary:
                context_enriched_message = f"{context_enriched_message}\n\n{hint_summary}"

            lc_history = convert_history_to_langchain_messages(compressed_history)
            messages_with_context = lc_history + [HumanMessage(content=context_enriched_message)]

            # Update task metadata with tools list
            await update_task_tools(task_id, task_manager, tool_instances)

            main_agent: Any = create_agent(model=llm, tools=tool_instances, system_prompt=system_prompt)
            main_agent = main_agent.bind(llm={"parallel_tool_calls": False})

            callback_list = [tracking_handler] + callbacks() if tracking_handler else callbacks()

            result = await main_agent.ainvoke(
                {"messages": messages_with_context},  # type: ignore[arg-type]
                config={
                    "callbacks": callback_list,
                    "metadata": {k: v for k, v in metadata.items() if k not in ("callbacks", "tracking_handler")},
                    "recursion_limit": int(os.getenv("AGENT_MAX_INTERACTIVE_STEPS", 64)),
                },
            )
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                content = last_message.content if hasattr(last_message, "content") else str(last_message)
                if isinstance(content, list):
                    reply = " ".join(str(item) for item in content)
                else:
                    reply = str(content) if content is not None else ""
            else:
                reply = ""

            # Mark task complete
            await task_manager.complete_task(task_id, result_summary=reply[:5000])

            # Save conversation to context(User message already saved)
            await storage.context.add_message(session_id, "assistant", reply)
            logger.info("✓ Saved conversation to context")

            # Store important findings (if any)
            # todo
            if any(keyword in reply.lower() for keyword in ["vulnerability", "found", "discovered", "exploit"]):
                # Extract target from user message (simple heuristic)
                target = "unknown"
                for word in user_message.split():
                    if ":" in word or "." in word:
                        target = word
                        break

                await storage.memory.store(
                    session_id=session_id,
                    key=f"finding:{target}",
                    value={"message": user_message, "result": reply[:5000]},
                    memory_type=MemoryType.FACT,
                    importance=0.9,
                    tags=["finding", scenario],
                    category="security_assessment",
                    source="agent_execution",
                )
                logger.info(f"✓ Stored security finding for {target}")

            # Put response into queue (streaming chunks)
            if response_queue is not None:
                # Split reply into chunks for streaming (e.g., by sentences or fixed size)
                chunk_size = 500  # Characters per chunk
                for i in range(0, len(reply), chunk_size):
                    chunk = reply[i : i + chunk_size]
                    response_queue.put({"status": "success", "data": chunk})
                    logger.info(f"✓ Chunk {i // chunk_size + 1} put into queue: {len(chunk)} chars")

                # Send completion signal
                response_queue.put({"status": "complete"})
                logger.info("✓ Response stream completed")

            return reply
        except Exception as e:
            # Send error signal to queue on exception
            logger.error(f"❌ Error in run(): {e}")
            try:
                await task_manager.fail_task(task_id, error_message=str(e))
            except Exception:
                logger.debug("Failed to mark task as failed", exc_info=True)
            if response_queue is not None:
                response_queue.put({"status": "error", "data": str(e)})
                response_queue.put({"status": "complete"})
            raise
        finally:
            # Always clear metadata to prevent context leaks
            MetadataContext.clear()


async def update_task_tools(task_id: uuid.UUID, task_manager: TaskManager, tool_instances: list[Any]):
    try:
        # Extract tool names and descriptions
        tool_list = []
        for tool in tool_instances:
            if hasattr(tool, "name") and hasattr(tool, "description"):
                tool_list.append({"name": tool.name, "description": tool.description})

        # Update task metadata with tools information
        await task_manager.update_task_metadata(
            task_id=task_id, metadata_updates={"tools": tool_list, "tools_count": len(tool_list)}
        )
        logger.info(f"Updated task {task_id} metadata with {len(tool_list)} tools")
    except Exception as e:
        logger.warning(f"Failed to update task metadata with tools list: {e}")


async def startup():
    """Startup initialization."""
    logger.info("Initializing storage system...")
    await init_storage()
    logger.info("✓ Storage system initialized\n")

    # Initialize tracking event processor
    if storage and storage.backend and storage.backend.task_dao:
        logger.info("Initializing tracking event processor...")
        tracking_processor = TrackingEventProcessor(
            task_dao=storage.backend.task_dao, batch_size=100, flush_interval=1.0
        )
        await tracking_processor.start()
        set_tracking_processor(tracking_processor)
        logger.info("✓ Tracking event processor started\n")
    else:
        logger.warning("Storage backend not available, skipping tracking processor initialization")


async def shutdown():
    """Cleanup and shutdown."""
    logger.info("\nShutting down...")

    # Stop tracking event processor
    from app.dynamic_agent.observability.tracking_processor import get_tracking_processor

    tracking_processor = get_tracking_processor()
    if tracking_processor:
        logger.info("Stopping tracking event processor...")
        await tracking_processor.stop()
        logger.info("✓ Tracking event processor stopped")

    logger.info("Shutdown complete\n")


async def do_main():
    try:
        # Initialize storage at startup
        await startup()

        response_queue_obj = queue.Queue()
        metadata = {
            # "langfuse_user_id": f"test_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "langfuse_user_id": "test_1234",
            "langfuse_session_id": f"test_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "langfuse_tags": ["test"],
            "response_queue": response_queue_obj,
        }

        say = input("Input task: ")
        while True:
            try:
                logger.info(f"\n{'=' * 60}")
                logger.info(f"User: {say}")
                logger.info(f"{'=' * 60}\n")

                # Run agent in background task
                run_task = asyncio.create_task(run(say, metadata))

                # Collect streaming responses from queue (both intermediate and final)
                reply_parts = []
                intermediate_messages = []
                timeout_per_chunk = 10
                total_timeout = 2 * 3600  # 2 hours total timeout
                start_time = asyncio.get_event_loop().time()
                stream_complete = False

                while not stream_complete:
                    try:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        remaining_timeout = total_timeout - elapsed

                        if remaining_timeout <= 0:
                            logger.error("❌ Total timeout exceeded waiting for response from queue")
                            break

                        # Get next chunk from queue with per-chunk timeout
                        chunk_timeout = min(timeout_per_chunk, int(remaining_timeout))
                        try:
                            response_data = await asyncio.wait_for(
                                asyncio.to_thread(response_queue_obj.get, timeout=chunk_timeout),
                                timeout=chunk_timeout + 1,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"⏱️ Timeout waiting for chunk (timeout={chunk_timeout}s), continuing...")
                            continue
                        except queue.Empty:
                            logger.info("Queue empty, waiting for more data...")
                            continue

                        status = response_data.get("status", "")
                        data = response_data.get("data", "")
                        data_type = response_data.get("type", "")

                        if status == "complete":
                            logger.info("✓ Stream completed")
                            stream_complete = True
                            break
                        elif status == "error":
                            logger.error(f"❌ Agent error: {data}")
                            print(f"\n❌ Error: {data}")
                            stream_complete = True
                            break
                        elif status == "success":
                            if "intermediate" == data_type:
                                # Check if this is intermediate message or final reply chunk
                                # Intermediate messages typically contain special markers like 🔧, 🟢, etc.
                                # if any(marker in data for marker in ["🔧", "🟢", "thinking:", "Input:", "Output:"]):
                                intermediate_messages.append(data)
                                logger.info(f"✓ Intermediate: {len(data)} chars")
                                # print(f"\n[AGENT] {data}")
                            else:
                                # Final reply chunk
                                reply_parts.append(data)
                                logger.info(f"✓ Reply chunk: {len(data)} chars")
                                # print(data, end='', flush=True)  # Real-time output

                    except Exception as e:
                        logger.error(f"❌ Unexpected error in stream loop: {e}")
                        break

                reply = "".join(reply_parts)

                # Wait for run task to complete
                try:
                    await asyncio.wait_for(run_task, timeout=300)
                except asyncio.TimeoutError:
                    logger.warning("Run task did not complete within timeout")

                logger.info(f"\n{'=' * 60}")
                logger.info(f"Assistant: {reply[:200]}..." if len(reply) > 200 else f"Assistant: {reply}")
                logger.info(f"{'=' * 60}\n")

                say = input("You: ")
                if not say or say.lower() in ["exit", "quit", "q"]:
                    logger.info("\nGoodbye!")
                    break
            except KeyboardInterrupt:
                logger.info("\n\nInterrupted by user. Goodbye!")
                break
            except Exception as e:
                logger.info(f"\n❌ Error: {e}")
                traceback.print_exc()
                say = input("You: ")
    finally:
        # Always cleanup on exit
        await shutdown()


if __name__ == "__main__":
    asyncio.run(do_main())
